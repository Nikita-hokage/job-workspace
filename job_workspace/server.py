import argparse
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import urlsplit

from .demo import seed_demo
from .domain import Rejected
from .export import export_job
from .store import Store
from .templates import TEMPLATES


STATIC = Path(__file__).with_name("static")
ASSETS = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/favicon.png": ("favicon.png", "image/png"),
}
JOB_PATH = re.compile(r"/api/jobs/([1-9][0-9]{0,17})(/commands|/export)?\Z")
MAX_BODY = 32 * 1024


class WorkspaceServer(ThreadingHTTPServer):
    def __init__(self, address, store):
        self.store = store
        super().__init__(address, Handler)
        port = self.server_address[1]
        self.allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}


class Handler(BaseHTTPRequestHandler):
    timeout = 12

    def log_message(self, format, *args):
        if format != '"%s" %s %s' or int(args[1]) >= 400:
            super().log_message(format, *args)

    def respond(self, status, content_type, body, *, attachment=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        if attachment:
            self.send_header("Content-Disposition", f'attachment; filename="{attachment}"')
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header(
            "Content-Security-Policy",
            "default-src 'self'; img-src 'self' data:; object-src 'none'; "
            "base-uri 'none'; frame-ancestors 'none'; form-action 'self'",
        )
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def json(self, value, status=HTTPStatus.OK):
        self.respond(status, "application/json; charset=utf-8", json.dumps(value, ensure_ascii=False).encode("utf-8"))

    def payload(self):
        if self.headers.get_content_type() != "application/json":
            raise Rejected("Используйте application/json.", status=415, code="unsupported_media_type")
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError as exc:
            raise Rejected("Некорректная длина запроса.") from exc
        if length < 1 or length > MAX_BODY:
            raise Rejected("Превышен допустимый размер запроса или запрос пуст.", status=413, code="invalid_size")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")
        except (ValueError, RecursionError) as exc:
            raise Rejected("Не удалось прочитать JSON.") from exc
        if not isinstance(value, dict) or not isinstance(value.get("data"), dict):
            raise Rejected("Запрос должен содержать объект data.")
        return value

    def do_GET(self):
        self.handle_workspace_request(write=False)

    def do_HEAD(self):
        self.do_GET()

    def do_POST(self):
        self.handle_workspace_request(write=True)

    def handle_workspace_request(self, *, write):
        try:
            host = self.headers.get("Host", "").lower()
            origin = self.headers.get("Origin")
            if host not in self.server.allowed_hosts or (write and origin not in (None, f"http://{host}")):
                raise Rejected("Откройте приложение по локальному адресу.", status=403, code="invalid_origin")
            path = urlsplit(self.path).path
            self.dispatch(path, write=write)
        except Rejected as exc:
            self.json({"error": str(exc), "code": exc.code}, exc.status)
        except sqlite3.OperationalError as exc:
            self.log_error("SQLite: %s", exc)
            self.json({"error": "Хранилище временно недоступно. Повторите запрос.", "code": "store_unavailable"}, 503)
        except (BrokenPipeError, ConnectionResetError, TimeoutError):
            # A disconnected client can retry the same operation ID.
            return

    def dispatch(self, path, *, write):
        store = self.server.store
        if not write and path in ASSETS:
            filename, content_type = ASSETS[path]
            self.respond(HTTPStatus.OK, content_type, (STATIC / filename).read_bytes())
            return
        if not write and path == "/api/activity":
            self.json(store.activity())
            return
        if not write and path == "/api/templates":
            self.json({"templates": TEMPLATES})
            return
        if path == "/api/jobs":
            if write:
                payload = self.payload()
                job = store.create(payload.get("operationId"), payload["data"])
                self.json(store.detail(job["id"]), HTTPStatus.CREATED)
            else:
                self.json(store.overview())
            return
        match = JOB_PATH.fullmatch(path)
        if match:
            job_id = int(match[1])
            if write and match[2] == "/commands":
                payload = self.payload()
                store.apply(job_id, payload.get("operationId"), payload.get("revision"), payload.get("type"), payload["data"])
                self.json(store.detail(job_id))
                return
            if not write and match[2] == "/export":
                record = store.detail(job_id)
                self.respond(
                    HTTPStatus.OK, "text/markdown; charset=utf-8", export_job(record).encode("utf-8"),
                    attachment=record["job"]["code"] + ".md",
                )
                return
            if not write and not match[2]:
                self.json(store.detail(job_id))
                return
        raise Rejected("Страница не найдена.", status=404, code="not_found")


def main():
    parser = argparse.ArgumentParser(description="Запуск Job Workspace")
    parser.add_argument("--port", type=int, default=8765, help="локальный порт HTTP (по умолчанию 8765)")
    parser.add_argument("--db", type=Path, default=Path(".data/workspace.sqlite3"), help="путь к базе SQLite")
    parser.add_argument("--demo", action="store_true", help="добавить примеры в пустую базу")
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error("--port должен быть от 1 до 65535")
    store = Store(args.db)
    if args.demo:
        seed_demo(store)
    with WorkspaceServer(("127.0.0.1", args.port), store) as server:
        print(f"Job Workspace: http://127.0.0.1:{args.port}", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
