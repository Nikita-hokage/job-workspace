from html import escape
import re

from .domain import EFFECTS, ROLES


STAGES = {
    "planning": "Планирование",
    "awaiting_plan": "Согласование",
    "implementation": "В работе",
    "paused": "На паузе",
    "review": "На ревью",
    "done": "Завершена",
}


def inline(value):
    text = " ".join(str(value).splitlines())
    return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", escape(text, quote=False))


def paragraph(value):
    return "\n".join("> " + inline(line) for line in value.splitlines())


def bullets(values):
    return "\n".join("- " + inline(value) for value in values)


def export_job(record):
    job = record["job"]
    parts = [
        f"# {job['code']} — {inline(job['title'])}",
        f"**Состояние** {STAGES[job['stage']]}",
        f"**Ревизия** {job['revision']}",
        f"**Создана** {job['createdAt']}",
        f"**Обновлена** {job['updatedAt']}",
        "## Описание задачи",
        paragraph(job["brief"]),
        "## Текущие роли",
        "\n".join(f"- **{ROLES[role]}** {inline(name)}" for role, name in job["team"].items()),
    ]
    draft = job.get("planDraft")
    if draft and not job["plans"]:
        parts.extend([
            "## Черновик плана из шаблона",
            paragraph(draft["summary"]),
            "**Ресурсы**\n\n" + bullets(draft["resources"]),
            "**Критерии приёмки**\n\n" + bullets(draft["criteria"]),
        ])

    parts.append("## Версии плана")
    decisions = {item["hash"]: item for item in job["planDecisions"]}
    for plan in job["plans"]:
        parts.extend([
            f"### План, версия {plan['version']}",
            f"**SHA-256** `{plan['hash']}`",
            f"**Отправлен** {plan['createdAt']}",
            paragraph(plan["summary"]),
            "**Ресурсы**\n\n" + bullets(plan["resources"]),
            "**Критерии приёмки**\n\n" + bullets(plan["criteria"]),
        ])
        decision = decisions.get(plan["hash"])
        if decision:
            label = "Одобрен" if decision["decision"] == "approve" else "Возвращён на доработку"
            parts.append(f"**Решение** {label} · {decision['at']}")
            if decision["note"]:
                parts.append(paragraph(decision["note"]))
    if not job["plans"]:
        parts.append("План ещё не отправляли на согласование.")

    parts.append("## Запросы на действия")
    for request in job["effects"]:
        parts.extend([
            f"### Запрос {request['id']} — {EFFECTS[request['kind']]}",
            f"**Ресурс** {inline(request['target'])}",
            f"**SHA-256 запроса** `{request['hash']}`",
            f"**SHA-256 плана** `{request['planHash']}`",
            f"**Создан** {request['requestedAt']}",
            paragraph(request["reason"]),
        ])
        decision = request["decision"]
        if decision:
            label = "Одобрено" if decision["value"] == "approve" else "Отклонено"
            parts.append(f"**Решение** {label} · {decision['at']}")
            if decision["note"]:
                parts.append(paragraph(decision["note"]))
        else:
            parts.append("Ожидает решения.")
        if request["resumedAt"]:
            parts.append(f"**Работа продолжена** {request['resumedAt']}")
    if not job["effects"]:
        parts.append("Запросов пока нет.")

    parts.append("## Результаты и ревью")
    reviews = {item["hash"]: item for item in job["reviews"]}
    for result in job["submissions"]:
        parts.extend([
            f"### Результат, версия {result['version']}",
            f"**SHA-256 результата** `{result['hash']}`",
            f"**SHA-256 плана** `{result['planHash']}`",
            f"**Отправлен** {result['submittedAt']}",
            paragraph(result["summary"]),
            "**Материалы для проверки**\n\n" + bullets(result["evidence"]),
        ])
        if result.get("author"):
            parts.append(f"**Автор результата** {inline(result['author'])}")
        review = reviews.get(result["hash"])
        if review:
            label = "Принят" if review["decision"] == "accept" else "Возвращён на доработку"
            parts.append(f"**Ревью** {label} · {review['at']}")
            if review["note"]:
                parts.append(paragraph(review["note"]))
    if not job["submissions"]:
        parts.append("Результат ещё не передавали на ревью.")

    parts.append("## Обсуждение")
    for message in job["comments"]:
        parts.extend([
            f"### {ROLES[message['role']]} — {inline(message['actor'])}",
            message["at"],
            paragraph(message["body"]),
        ])
    if not job["comments"]:
        parts.append("Сообщений пока нет.")

    parts.append("## Журнал событий")
    for entry in reversed(record["events"]):
        parts.extend([
            f"### {inline(entry['title'])}",
            f"**Ревизия** {entry['revision']} · {entry['at']}",
            f"**Участник** {inline(entry['actor'])} · {ROLES[entry['role']]}",
        ])
        if entry["detail"]:
            parts.append(paragraph(entry["detail"]))
    return "\n\n".join(parts) + "\n"
