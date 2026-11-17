from datetime import datetime, timedelta, timezone
from uuid import NAMESPACE_URL, uuid5


def seed_demo(store):
    if store.overview()["jobs"]:
        return

    now = datetime.now(timezone.utc)

    def timestamp(minutes_ago):
        return (now - timedelta(minutes=minutes_ago)).isoformat(timespec="seconds")

    def create(slug, title, brief, minutes):
        return store.create(
            str(uuid5(NAMESPACE_URL, f"job-workspace/demo/{slug}")),
            {"title": title, "brief": brief},
            at=timestamp(minutes),
        )

    def apply(job, command, data, minutes):
        return store.apply(
            job["id"], str(uuid5(NAMESPACE_URL, f"job-workspace/demo/{job['id']}/{job['revision']}")),
            job["revision"], command, data, at=timestamp(minutes),
        )

    report = create(
        "report", "Пересобрать шаблон отчёта",
        "Собрать короткий шаблон еженедельного отчёта с итогами, рисками и решениями.", 3200,
    )
    report = apply(report, "propose_plan", {
        "summary": "Взять два последних отчёта, выделить повторяющиеся разделы и подготовить пример заполнения.",
        "resources": ["Внутренняя база знаний", "Архив командных отчётов"],
        "criteria": ["Есть разделы для итогов, рисков и решений", "У шаблона есть пример заполнения"],
    }, 3070)
    report = apply(report, "decide_plan", {"decision": "approve", "hash": report["plans"][-1]["hash"]}, 2900)
    apply(report, "submit_review", {
        "summary": "Новый шаблон готов. Добавлены три постоянных раздела и заполненный пример.",
        "evidence": ["reports/weekly-template.md", "reports/weekly-example.md"],
    }, 970)

    create(
        "catalog", "Подготовить каталог компонентов",
        "Описать общие компоненты интерфейса и собрать ссылки на их исходники.", 1260,
    )

    onboarding = create(
        "onboarding", "Обновить онбординг команды",
        "Собрать единый маршрут для новых сотрудников с доступами, первыми шагами и критериями готовности.", 580,
    )
    onboarding = apply(onboarding, "update_team", {
        "planner": "Анна Волкова", "coder": "Михаил Лебедев", "reviewer": "Елена Орлова",
    }, 550)
    onboarding = apply(onboarding, "propose_plan", {
        "summary": "Свести разрозненные инструкции в один маршрут. Описать подготовку до первого дня, затем доступы, первую задачу и встречу с наставником.",
        "resources": ["База знаний / Онбординг", "Репозиторий / onboarding-guide"],
        "criteria": [
            "Есть чек-лист для первого дня и первой недели",
            "У каждого доступа указан ответственный",
            "Наставник может пройти маршрут по инструкции",
        ],
    }, 275)
    onboarding = apply(onboarding, "decide_plan", {
        "decision": "approve", "hash": onboarding["plans"][-1]["hash"],
    }, 198)
    onboarding = apply(onboarding, "comment", {
        "role": "planner", "body": "Добавила в критерии проверку маршрута наставником. Ответственных по доступам сверили с командой.",
    }, 142)
    apply(onboarding, "request_effect", {
        "kind": "publish", "target": "База знаний / Онбординг",
        "reason": "Опубликовать обновлённую памятку в базе знаний. Она заменит памятку, которую команда использует сейчас.",
    }, 24)
