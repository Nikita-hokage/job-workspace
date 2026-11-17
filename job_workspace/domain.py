import hashlib
import json


class Rejected(Exception):
    def __init__(self, message, *, status=400, code="invalid_request"):
        super().__init__(message)
        self.status = status
        self.code = code


ROLES = {
    "planner": "Планировщик",
    "coder": "Исполнитель",
    "reviewer": "Ревьюер",
    "owner": "Владелец задачи",
}

EFFECTS = {
    "publish": "Публикация",
    "access": "Изменение доступа",
    "delete": "Удаление данных",
    "external": "Другое внешнее действие",
}


def digest(value):
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def field(data, key, label, limit, *, optional=False):
    value = data.get(key, "")
    if not isinstance(value, str):
        raise Rejected(f"{label} должно быть текстом.")
    value = value.strip()
    if len(value) > limit or (not optional and not value):
        raise Rejected(f"Заполните поле «{label}». Максимум {limit} символов.")
    return value


def lines(data, key, label, *, limit=12):
    value = data.get(key)
    if not isinstance(value, list) or not 1 <= len(value) <= limit:
        raise Rejected(f"Укажите от 1 до {limit} строк в поле «{label}».")
    result = []
    for item in value:
        if not isinstance(item, str) or not 1 <= len(item.strip()) <= 240:
            raise Rejected(f"Каждая строка в поле «{label}» должна содержать от 1 до 240 символов.")
        result.append(item.strip())
    if len(result) != len(set(result)):
        raise Rejected(f"Удалите повторяющиеся строки в поле «{label}».")
    return result


def require_stage(job, *stages):
    if job["stage"] not in stages:
        raise Rejected("Действие недоступно на текущем этапе задачи.", status=409, code="wrong_stage")


def event(job, role, kind, title, detail=""):
    return {
        "role": role,
        "actor": job["team"].get(role, ROLES[role]),
        "kind": kind,
        "title": title,
        "detail": detail,
    }


def create_job(job_id, data, at):
    title = field(data, "title", "Название", 96)
    brief = field(data, "brief", "Описание задачи", 1600)
    team = {role: label for role, label in ROLES.items() if role != "owner"}
    job = {
        "id": job_id,
        "code": f"JW-{job_id:03d}",
        "title": title,
        "brief": brief,
        "stage": "planning",
        "team": team,
        "plans": [],
        "planDecisions": [],
        "effects": [],
        "submissions": [],
        "reviews": [],
        "comments": [],
        "createdAt": at,
        "updatedAt": at,
        "revision": 1,
    }
    return job, event(job, "owner", "created", "Задача создана")


def update_team(job, data, at):
    require_stage(job, "planning", "awaiting_plan", "implementation", "paused", "review")
    team = {role: field(data, role, ROLES[role], 72) for role in job["team"]}
    if team["coder"].casefold() == team["reviewer"].casefold():
        raise Rejected("Исполнитель и ревьюер должны различаться.")
    job["team"] = team
    detail = "\n".join(f"{ROLES[role]} — {name}" for role, name in team.items())
    return event(job, "owner", "team", "Роли обновлены", detail)


def propose_plan(job, data, at):
    require_stage(job, "planning", "awaiting_plan")
    plan = {
        "version": len(job["plans"]) + 1,
        "summary": field(data, "summary", "План работы", 2400),
        "resources": lines(data, "resources", "Ресурсы"),
        "criteria": lines(data, "criteria", "Критерии приёмки"),
    }
    plan["hash"] = digest({"jobId": job["id"], **plan})
    plan["createdAt"] = at
    job["plans"].append(plan)
    job["stage"] = "awaiting_plan"
    return event(job, "planner", "plan", "План отправлен на согласование", f"Версия {plan['version']}")


def latest_plan(job, supplied_hash):
    if not job["plans"] or job["plans"][-1]["hash"] != supplied_hash:
        raise Rejected("Откройте актуальную версию плана.", status=409, code="plan_changed")
    return job["plans"][-1]


def decide_plan(job, data, at):
    require_stage(job, "awaiting_plan")
    plan = latest_plan(job, data.get("hash"))
    decision = data.get("decision")
    if decision not in ("approve", "revise"):
        raise Rejected("Выберите решение по плану.")
    note = field(data, "note", "Комментарий", 1600, optional=decision == "approve")
    job["planDecisions"].append({"hash": plan["hash"], "decision": decision, "note": note, "at": at})
    job["stage"] = "implementation" if decision == "approve" else "planning"
    title = "План одобрен" if decision == "approve" else "План возвращён на доработку"
    return event(job, "owner", "plan_decision", title, note or f"Версия {plan['version']}")


def approved_plan(job):
    plan = job["plans"][-1] if job["plans"] else None
    if not plan or not any(
        d["hash"] == plan["hash"] and d["decision"] == "approve" for d in job["planDecisions"]
    ):
        raise Rejected("Для продолжения нужен одобренный план.", status=409, code="missing_approval")
    return plan


def request_effect(job, data, at):
    require_stage(job, "implementation")
    plan = approved_plan(job)
    kind = field(data, "kind", "Тип действия", 32)
    if kind not in EFFECTS:
        raise Rejected("Выберите тип действия.")
    target = field(data, "target", "Ресурс", 240)
    if target not in plan["resources"]:
        raise Rejected("Запрос должен относиться к ресурсу из одобренного плана.", status=422, code="outside_scope")
    item = {
        "id": len(job["effects"]) + 1,
        "kind": kind,
        "target": target,
        "reason": field(data, "reason", "Описание действия", 1600),
        "planHash": plan["hash"],
    }
    item["hash"] = digest({"jobId": job["id"], **item})
    item.update(requestedAt=at, decision=None, resumedAt=None)
    job["effects"].append(item)
    job["stage"] = "paused"
    return event(job, "coder", "effect", "Запрошено одобрение действия", EFFECTS[kind])


def paused_effect(job, data):
    require_stage(job, "paused")
    plan = approved_plan(job)
    item = job["effects"][-1] if job["effects"] else None
    if not item or item["hash"] != data.get("hash") or item["planHash"] != plan["hash"]:
        raise Rejected("Откройте актуальный запрос.", status=409, code="effect_changed")
    return item


def decide_effect(job, data, at):
    item = paused_effect(job, data)
    if item["decision"] is not None:
        raise Rejected("Решение по запросу уже записано.", status=409, code="already_decided")
    decision = data.get("decision")
    if decision not in ("approve", "deny"):
        raise Rejected("Выберите решение по действию.")
    note = field(data, "note", "Комментарий", 1600, optional=decision == "approve")
    item["decision"] = {"value": decision, "note": note, "at": at}
    title = "Действие одобрено" if decision == "approve" else "Действие отклонено"
    return event(job, "owner", "effect_decision", title, note or EFFECTS[item["kind"]])


def resume_work(job, data, at):
    item = paused_effect(job, data)
    if item["decision"] is None:
        raise Rejected("Сначала примите решение по действию.", status=409, code="decision_required")
    item["resumedAt"] = at
    job["stage"] = "implementation"
    return event(job, "coder", "resumed", "Работа продолжена")


def submit_review(job, data, at):
    require_stage(job, "implementation")
    plan = approved_plan(job)
    result = {
        "version": len(job["submissions"]) + 1,
        "planHash": plan["hash"],
        "author": job["team"]["coder"],
        "summary": field(data, "summary", "Результат", 2400),
        "evidence": lines(data, "evidence", "Материалы для проверки"),
        "submittedAt": at,
    }
    result["hash"] = digest({"jobId": job["id"], **result})
    job["submissions"].append(result)
    job["stage"] = "review"
    return event(job, "coder", "submission", "Результат передан на ревью", f"Версия {result['version']}")


def decide_review(job, data, at):
    require_stage(job, "review")
    plan = approved_plan(job)
    result = job["submissions"][-1]
    if data.get("hash") != result["hash"] or result["planHash"] != plan["hash"]:
        raise Rejected("Откройте актуальную версию результата.", status=409, code="submission_changed")
    author = result.get("author", job["team"]["coder"])
    if author.casefold() == job["team"]["reviewer"].casefold():
        raise Rejected("Назначьте ревьюера, который не отправлял этот результат.", status=409, code="same_reviewer")
    decision = data.get("decision")
    if decision not in ("accept", "revise"):
        raise Rejected("Выберите решение по результату.")
    note = field(data, "note", "Комментарий ревью", 1600, optional=decision == "accept")
    job["reviews"].append({"hash": result["hash"], "decision": decision, "note": note, "at": at})
    job["stage"] = "done" if decision == "accept" else "implementation"
    title = "Результат принят" if decision == "accept" else "Результат возвращён на доработку"
    return event(job, "reviewer", "review", title, note)


def post_comment(job, data, at):
    role = field(data, "role", "Роль", 16)
    if role not in ROLES:
        raise Rejected("Выберите роль автора.")
    body = field(data, "body", "Сообщение", 1600)
    message = event(job, role, "comment", "Добавлено сообщение")
    job["comments"].append({"role": role, "actor": message["actor"], "body": body, "at": at})
    return message


COMMANDS = {
    "update_team": update_team,
    "propose_plan": propose_plan,
    "decide_plan": decide_plan,
    "request_effect": request_effect,
    "decide_effect": decide_effect,
    "resume_work": resume_work,
    "submit_review": submit_review,
    "decide_review": decide_review,
    "comment": post_comment,
}
