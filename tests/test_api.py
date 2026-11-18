from http.client import HTTPConnection
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from uuid import uuid4

from job_workspace.server import WorkspaceServer
from job_workspace.store import Store


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        temp = TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        cls.server = WorkspaceServer(("127.0.0.1", 0), Store(Path(temp.name) / "http.sqlite3"))
        cls.addClassCleanup(cls.server.server_close)
        worker = Thread(target=cls.server.serve_forever, daemon=True)
        worker.start()
        cls.addClassCleanup(worker.join, 5)
        cls.addClassCleanup(cls.server.shutdown)

    def request(self, method, path, payload=None, extra_headers=None):
        client = HTTPConnection(*self.server.server_address, timeout=4)
        try:
            headers = dict(extra_headers or {})
            body = None
            if payload is not None:
                headers["Content-Type"] = "application/json"
                body = json.dumps(payload)
            client.request(method, path, body=body, headers=headers)
            response = client.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            client.close()

    def test_static_assets_have_content_policy(self):
        for path in ("/", "/app.js", "/styles.css", "/favicon.png"):
            with self.subTest(path=path):
                code, headers, body = self.request("GET", path)
                self.assertEqual(code, 200)
                self.assertGreater(len(body), 0)
                self.assertIn("frame-ancestors 'none'", dict(headers)["Content-Security-Policy"])

    def test_create_and_read_detail(self):
        payload = {"operationId": str(uuid4()), "data": {"title": "Translate copy", "brief": "Translate UI"}}
        code, _, body = self.request("POST", "/api/jobs", payload)
        self.assertEqual(code, 201)
        created = json.loads(body)
        self.assertEqual(created["job"]["stage"], "planning")
        self.assertEqual(len(created["events"]), 1)
        code, _, detail = self.request("GET", f"/api/jobs/{created['job']['id']}")
        self.assertEqual(code, 200)
        self.assertEqual(json.loads(detail), created)

    def test_cross_origin_write_is_rejected(self):
        code, _, body = self.request("POST", "/api/jobs", {"data": {}}, {"Origin": "https://example.com"})
        self.assertEqual(code, 403)
        self.assertEqual(json.loads(body)["code"], "invalid_origin")

    def test_template_catalog_can_create_a_job(self):
        code, _, body = self.request("GET", "/api/templates")
        self.assertEqual(code, 200)
        templates = json.loads(body)["templates"]
        self.assertEqual({item["id"] for item in templates}, {"documentation", "onboarding", "release"})
        payload = {"operationId": str(uuid4()), "data": {
            "title": "Свой выпуск", "brief": "Подготовить выпуск", "templateId": "release",
        }}
        code, _, body = self.request("POST", "/api/jobs", payload)
        self.assertEqual(code, 201)
        job = json.loads(body)["job"]
        template = next(item for item in templates if item["id"] == "release")
        self.assertEqual(job["planDraft"], template["plan"])
        self.assertEqual(job["title"], "Свой выпуск")

    def test_export_contains_versions_decisions_and_only_the_selected_job(self):
        store = self.server.store
        job = store.create(str(uuid4()), {"title": "Подготовка инструкции", "brief": "Проверить запуск"})
        other = store.create(str(uuid4()), {"title": "Посторонняя задача", "brief": "Личный комментарий другой задачи"})
        store.apply(other["id"], str(uuid4()), other["revision"], "comment", {
            "role": "owner", "body": "Сообщение из другой задачи",
        })

        def command(kind, data):
            nonlocal job
            job = store.apply(job["id"], str(uuid4()), job["revision"], kind, data)

        plan = {"summary": "Проверить команды", "resources": ["docs/install.md"], "criteria": ["Запуск проверен"]}
        command("propose_plan", plan)
        command("decide_plan", {"hash": job["plans"][-1]["hash"], "decision": "revise", "note": "Добавить проверку Windows"})
        command("propose_plan", {**plan, "summary": "Проверить команды на Linux и Windows"})
        command("decide_plan", {"hash": job["plans"][-1]["hash"], "decision": "approve"})
        command("request_effect", {"kind": "publish", "target": "docs/install.md", "reason": "Обновить руководство"})
        effect = job["effects"][-1]
        command("decide_effect", {"hash": effect["hash"], "decision": "deny", "note": "Дождаться ревью"})
        command("resume_work", {"hash": effect["hash"]})
        command("submit_review", {"summary": "Первый результат", "evidence": ["docs/install.md"]})
        command("decide_review", {"hash": job["submissions"][-1]["hash"], "decision": "revise", "note": "Нужен пример запуска"})
        command("submit_review", {"summary": "Добавлен пример запуска", "evidence": ["docs/install.md"]})
        command("decide_review", {"hash": job["submissions"][-1]["hash"], "decision": "accept"})
        command("comment", {"role": "reviewer", "body": "# Комментарий\n<script>alert(1)</script>\n[ссылка](https://example.com)"})

        before = store.detail(job["id"])
        path = f"/api/jobs/{job['id']}/export"
        code, headers, body = self.request("GET", path)
        self.assertEqual(code, 200)
        self.assertEqual(dict(headers)["Content-Type"], "text/markdown; charset=utf-8")
        self.assertEqual(dict(headers)["Content-Disposition"], f'attachment; filename="{job["code"]}.md"')
        report = body.decode("utf-8")
        for text in ("**Состояние** Завершена", "### План, версия 1", "### План, версия 2",
                     "**Решение** Одобрен", "**Решение** Отклонено", "Дождаться ревью",
                     "### Результат, версия 1", "### Результат, версия 2", "Нужен пример запуска",
                     "**Ревью** Принят", "> \\# Комментарий", "&lt;script&gt;", r"\[ссылка\]"):
            self.assertIn(text, report)
        for item in job["plans"] + job["effects"] + job["submissions"]:
            self.assertIn(item["hash"], report)
        self.assertNotIn("<script>", report)
        self.assertNotIn("Сообщение из другой задачи", report)
        self.assertNotIn("Посторонняя задача", report)
        timeline = report.split("## Журнал событий\n", 1)[1]
        self.assertLess(timeline.index("### Задача создана"), timeline.index("### Результат принят"))
        self.assertEqual(store.detail(job["id"]), before)
        self.assertEqual(self.request("GET", path)[2], body)
        code, head_headers, empty = self.request("HEAD", path)
        self.assertEqual(code, 200)
        self.assertEqual(empty, b"")
        self.assertEqual(int(dict(head_headers)["Content-Length"]), len(body))

    def test_export_supports_old_jobs_and_template_drafts(self):
        for template_id in ("", "documentation"):
            with self.subTest(template=template_id):
                payload = {"operationId": str(uuid4()), "data": {
                    "title": "Ранняя задача", "brief": "Задача на этапе планирования", "templateId": template_id,
                }}
                _, _, body = self.request("POST", "/api/jobs", payload)
                job = json.loads(body)["job"]
                if not template_id:
                    self.assertNotIn("planDraft", job)
                code, _, body = self.request("GET", f"/api/jobs/{job['id']}/export")
                self.assertEqual(code, 200)
                report = body.decode("utf-8")
                self.assertIn("План ещё не отправляли на согласование", report)
                self.assertEqual("## Черновик плана из шаблона" in report, bool(template_id))
        code, _, body = self.request("GET", "/api/jobs/999999/export")
        self.assertEqual(code, 404)
        self.assertEqual(json.loads(body)["code"], "not_found")
