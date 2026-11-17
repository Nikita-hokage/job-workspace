from contextlib import contextmanager
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from uuid import UUID

from .domain import COMMANDS, Rejected, create_job, digest


SCHEMA = """
PRAGMA journal_mode = WAL;
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY,
    revision INTEGER NOT NULL,
    updated_at TEXT NOT NULL,
    snapshot TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS operations (
    id TEXT PRIMARY KEY,
    fingerprint TEXT NOT NULL,
    job_id INTEGER NOT NULL REFERENCES jobs(id)
);
CREATE TABLE IF NOT EXISTS events (
    seq INTEGER PRIMARY KEY,
    job_id INTEGER NOT NULL REFERENCES jobs(id),
    revision INTEGER NOT NULL,
    at TEXT NOT NULL,
    actor TEXT NOT NULL,
    role TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    detail TEXT NOT NULL,
    UNIQUE (job_id, revision)
);
"""


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def operation_id(value):
    try:
        return str(UUID(value))
    except (AttributeError, TypeError, ValueError) as exc:
        raise Rejected("Идентификатор операции должен быть UUID.") from exc


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript(SCHEMA)

    @contextmanager
    def connection(self, *, write=False):
        db = sqlite3.connect(self.path, isolation_level=None, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys = ON")
            if write:
                db.execute("BEGIN IMMEDIATE")
            yield db
            if write:
                db.commit()
        except BaseException:
            if write:
                db.rollback()
            raise
        finally:
            db.close()

    @staticmethod
    def _job(db, job_id):
        row = db.execute("SELECT snapshot FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise Rejected("Задача не найдена.", status=404, code="not_found")
        return json.loads(row["snapshot"])

    @staticmethod
    def _receipt(db, op_id, fingerprint):
        row = db.execute("SELECT fingerprint, job_id FROM operations WHERE id = ?", (op_id,)).fetchone()
        if row is None:
            return None
        if row["fingerprint"] != fingerprint:
            raise Rejected("Этот идентификатор уже использован другой операцией.", status=409, code="operation_conflict")
        return row["job_id"]

    @staticmethod
    def _save(db, job, item, op_id, fingerprint):
        at = job["updatedAt"]
        db.execute(
            "UPDATE jobs SET revision = ?, updated_at = ?, snapshot = ? WHERE id = ?",
            (job["revision"], at, json.dumps(job, ensure_ascii=False), job["id"]),
        )
        db.execute(
            "INSERT INTO events(job_id, revision, at, actor, role, kind, title, detail) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (job["id"], job["revision"], at, item["actor"], item["role"], item["kind"], item["title"], item["detail"]),
        )
        db.execute("INSERT INTO operations VALUES (?, ?, ?)", (op_id, fingerprint, job["id"]))

    def create(self, op_id, data, *, at=None):
        op_id = operation_id(op_id)
        fingerprint = digest({"action": "create", "data": data})
        at = at or utc_now()
        with self.connection(write=True) as db:
            existing_id = self._receipt(db, op_id, fingerprint)
            if existing_id is not None:
                return self._job(db, existing_id)
            job_id = db.execute(
                "INSERT INTO jobs(revision, updated_at, snapshot) VALUES (1, ?, '{}')", (at,)
            ).lastrowid
            job, item = create_job(job_id, data, at)
            self._save(db, job, item, op_id, fingerprint)
            return job

    def apply(self, job_id, op_id, revision, kind, data, *, at=None):
        if type(revision) is not int or revision < 1:
            raise Rejected("Укажите текущую ревизию задачи.")
        op_id = operation_id(op_id)
        command = COMMANDS.get(kind) if isinstance(kind, str) else None
        if command is None:
            raise Rejected("Неизвестная команда.")
        fingerprint = digest({"jobId": job_id, "revision": revision, "kind": kind, "data": data})
        at = at or utc_now()
        with self.connection(write=True) as db:
            if self._receipt(db, op_id, fingerprint) is not None:
                return self._job(db, job_id)
            job = self._job(db, job_id)
            if job["revision"] != revision:
                raise Rejected("Задача уже изменилась. Обновите её и повторите действие.", status=409, code="stale_revision")
            item = command(job, data, at)
            job["revision"] += 1
            job["updatedAt"] = at
            self._save(db, job, item, op_id, fingerprint)
            return job

    def detail(self, job_id):
        with self.connection() as db:
            db.execute("BEGIN")
            job = self._job(db, job_id)
            events = db.execute("SELECT * FROM events WHERE job_id = ? ORDER BY seq DESC", (job_id,))
            return {"job": job, "events": [dict(row) for row in events]}

    def overview(self):
        with self.connection() as db:
            db.execute("BEGIN")
            jobs = [json.loads(row["snapshot"]) for row in db.execute("SELECT snapshot FROM jobs ORDER BY updated_at DESC, id DESC")]
            fields = ("id", "code", "title", "brief", "stage", "team", "updatedAt")
            return {"jobs": [{key: job[key] for key in fields} for job in jobs]}

    def activity(self):
        with self.connection() as db:
            rows = db.execute("""
                SELECT events.*, json_extract(jobs.snapshot, '$.title') AS job_title
                FROM events JOIN jobs ON events.job_id = jobs.id
                ORDER BY seq DESC
            """)
            return {"events": [dict(row) for row in rows]}
