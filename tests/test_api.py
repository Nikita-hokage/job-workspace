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
