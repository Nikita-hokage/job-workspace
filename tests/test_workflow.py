from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from uuid import uuid4

from job_workspace.demo import seed_demo
from job_workspace.domain import Rejected
from job_workspace.store import Store
from job_workspace.templates import TEMPLATES


PLAN = {"summary": "Update the introduction", "resources": ["docs/intro.md"], "criteria": ["Introduction links to the tutorial"]}
RESULT = {"summary": "Added an introduction", "evidence": ["docs/intro.md"]}


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        temp = TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / "workspace.db"
        self.store = Store(self.path)
        self.job = self.store.create(str(uuid4()), {"title": "Docs refresh", "brief": "Improve onboarding"})

    def command(self, kind, data, *, op_id=None, at=None):
        self.job = self.store.apply(self.job["id"], op_id or str(uuid4()), self.job["revision"], kind, data, at=at)
        return self.job

    def approve_plan(self):
        self.command("propose_plan", PLAN)
        self.command("decide_plan", {"decision": "approve", "hash": self.job["plans"][-1]["hash"]})

    def assert_rejected(self, code, kind, data):
        revision = self.job["revision"]
        with self.assertRaises(Rejected) as error:
            self.command(kind, data)
        self.assertEqual(error.exception.code, code)
        self.assertEqual(self.store.detail(self.job["id"])["job"]["revision"], revision)

    def test_replaced_plan_cannot_be_approved(self):
        self.assert_rejected("wrong_stage", "submit_review", RESULT)
        self.command("propose_plan", PLAN)
        first = self.job["plans"][0]
        self.command("propose_plan", {**PLAN, "summary": "Include setup instructions"})
        self.assertEqual(self.job["plans"][0], first)
        self.assert_rejected("plan_changed", "decide_plan", {"decision": "approve", "hash": first["hash"]})
        second = self.job["plans"][1]
        self.command("decide_plan", {"decision": "approve", "hash": second["hash"]})
        self.assertEqual(self.job["stage"], "implementation")

    def test_effect_pause_survives_reopen_and_needs_a_decision(self):
        self.approve_plan()
        self.assert_rejected("outside_scope", "request_effect", {"kind": "publish", "target": "private.md", "reason": "Archive"})
        self.command("request_effect", {"kind": "publish", "target": "docs/intro.md", "reason": "Update handbook"})
        job_id = self.job["id"]
        effect = self.job["effects"][-1]
        self.store = Store(self.path)
        self.job = self.store.detail(job_id)["job"]
        self.assertEqual(self.job["stage"], "paused")
        self.assert_rejected("decision_required", "resume_work", {"hash": effect["hash"]})
        self.assert_rejected("wrong_stage", "submit_review", RESULT)
        self.assert_rejected("effect_changed", "decide_effect", {"hash": "wrong", "decision": "approve"})
        self.command("decide_effect", {"hash": effect["hash"], "decision": "deny", "note": "Keep draft internal"})
        self.assertEqual(self.job["stage"], "paused")
        self.assert_rejected("already_decided", "decide_effect", {"hash": effect["hash"], "decision": "approve"})
        self.command("resume_work", {"hash": effect["hash"]})
        self.assertEqual(self.job["id"], job_id)
        self.assertEqual(self.job["stage"], "implementation")
        self.assertEqual(self.job["effects"][-1]["decision"]["value"], "deny")

    def test_review_can_return_then_accept_current_submission(self):
        self.approve_plan()
        self.command("submit_review", RESULT)
        old = self.job["submissions"][0]
        self.command("decide_review", {"hash": old["hash"], "decision": "revise", "note": "Show the tutorial link"})
        self.assertEqual(self.job["stage"], "implementation")
        self.command("submit_review", {**RESULT, "summary": "Added the tutorial link"})
        self.assert_rejected("submission_changed", "decide_review", {"hash": old["hash"], "decision": "accept"})
        self.command("decide_review", {"hash": self.job["submissions"][-1]["hash"], "decision": "accept"})
        self.assertEqual(self.job["stage"], "done")
        self.assertEqual(self.job["submissions"][0], old)
        self.assert_rejected("wrong_stage", "submit_review", RESULT)

    def test_retries_add_only_one_event(self):
        op_id = str(uuid4())
        job_id, initial = self.job["id"], self.job["revision"]
        self.command("propose_plan", PLAN, op_id=op_id)
        repeat = Store(self.path).apply(job_id, op_id, initial, "propose_plan", PLAN)
        self.assertEqual(repeat, self.job)
        self.assertEqual(len(self.store.detail(job_id)["events"]), 2)
        with self.assertRaises(Rejected) as error:
            self.store.apply(job_id, op_id, initial, "propose_plan", {**PLAN, "summary": "Changed"})
        self.assertEqual(error.exception.code, "operation_conflict")

    def test_reassigned_reviewer_cannot_accept_their_own_submission(self):
        self.approve_plan()
        self.command("submit_review", RESULT)
        result = self.job["submissions"][-1]
        self.command("update_team", {**self.job["team"], "coder": "Новый исполнитель", "reviewer": result["author"]})
        self.assert_rejected("same_reviewer", "decide_review", {"hash": result["hash"], "decision": "accept"})

    def test_competing_tabs_cannot_both_write_same_revision(self):
        job_id, revision = self.job["id"], self.job["revision"]

        def write(title):
            try:
                self.store.apply(job_id, str(uuid4()), revision, "propose_plan", {**PLAN, "summary": title})
                return "ok"
            except Rejected as exc:
                return exc.code

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(write, ["Plan A", "Plan B"]))
        self.assertCountEqual(outcomes, ["ok", "stale_revision"])
        self.assertEqual(len(self.store.detail(job_id)["events"]), 2)

    def test_demo_seeds_empty_store_once(self):
        store = Store(self.path.with_name("demo.db"))
        seed_demo(store)
        seed_demo(store)
        self.assertEqual(len(store.overview()["jobs"]), 3)
        self.assertEqual(store.overview()["jobs"][0]["stage"], "paused")

    def test_templates_save_a_draft_without_approving_it(self):
        for template in TEMPLATES:
            with self.subTest(template=template["id"]):
                operation_id = str(uuid4())
                data = {"title": "Своё название", "brief": "Своя цель", "templateId": template["id"]}
                job = self.store.create(operation_id, data)
                restored = Store(self.path).detail(job["id"])
                self.assertEqual(restored["job"]["title"], data["title"])
                self.assertEqual(restored["job"]["planDraft"], template["plan"])
                self.assertEqual(restored["job"]["stage"], "planning")
                self.assertEqual(restored["job"]["plans"], [])
                self.assertEqual(restored["job"]["planDecisions"], [])
                self.assertEqual(self.store.create(operation_id, data), job)
                self.assertEqual(len(restored["events"]), 1)
                with self.assertRaises(Rejected) as error:
                    self.store.apply(job["id"], str(uuid4()), job["revision"], "submit_review", RESULT)
                self.assertEqual(error.exception.code, "wrong_stage")
                job["planDraft"]["criteria"].append("Локальное изменение")
                self.assertEqual(self.store.detail(job["id"])["job"]["planDraft"], template["plan"])

    def test_unknown_template_does_not_create_a_job(self):
        initial = self.store.overview()
        with self.assertRaises(Rejected) as error:
            self.store.create(str(uuid4()), {"title": "Test", "brief": "Test", "templateId": "missing"})
        self.assertEqual(error.exception.code, "unknown_template")
        self.assertEqual(self.store.overview(), initial)

    def pending(self):
        return self.store.overview()["jobs"][0]["pendingAction"]

    def test_queue_tracks_only_the_current_plan_and_result(self):
        self.assertIsNone(self.pending())
        first = "2026-08-01T08:00:00+00:00"
        second = "2026-08-02T12:00:00+00:00"
        self.command("propose_plan", PLAN, at=first)
        self.command("propose_plan", PLAN, at=second)
        self.command("comment", {"role": "planner", "body": "Ready"})
        self.assertEqual(self.pending(), {
            "kind": "plan", "role": "owner", "context": "Версия плана 2", "since": second,
        })
        self.command("decide_plan", {"hash": self.job["plans"][-1]["hash"], "decision": "revise", "note": "More detail"})
        self.assertIsNone(self.pending())
        self.approve_plan()
        self.assertIsNone(self.pending())
        self.command("submit_review", RESULT)
        self.command("decide_review", {"hash": self.job["submissions"][-1]["hash"], "decision": "revise", "note": "Add example"})
        self.assertIsNone(self.pending())
        self.command("submit_review", RESULT, at=second)
        self.command("update_team", {**self.job["team"], "reviewer": "Анна"})
        self.assertEqual(self.pending(), {
            "kind": "review", "role": "reviewer", "context": "Версия результата 2", "since": second,
        })
        self.command("decide_review", {"hash": self.job["submissions"][-1]["hash"], "decision": "accept"})
        self.assertIsNone(self.pending())

    def test_effect_handoff_survives_restart_and_both_decisions(self):
        self.approve_plan()
        for value, label in (("approve", "Одобрено"), ("deny", "Отклонено")):
            with self.subTest(decision=value):
                requested = "2026-08-01T11:00:00+00:00"
                decided = "2026-08-02T13:00:00+00:00"
                self.command("request_effect", {"kind": "publish", "target": "docs/intro.md", "reason": "Publish"}, at=requested)
                self.assertEqual(self.pending(), {"kind": "effect", "role": "owner", "since": requested,
                                                  "context": "Публикация · docs/intro.md"})
                effect_hash = self.job["effects"][-1]["hash"]
                self.command("decide_effect", {"hash": effect_hash, "decision": value, "note": "Reviewed"}, at=decided)
                self.store = Store(self.path)
                self.assertEqual(self.pending(), {"kind": "resume", "role": "coder", "since": decided,
                                                  "context": f"{label} · Публикация · docs/intro.md"})
                self.command("resume_work", {"hash": effect_hash})
                self.assertIsNone(self.pending())

    def test_old_snapshot_and_three_role_client_keep_the_correct_owner(self):
        self.command("propose_plan", PLAN)
        job_id = self.job["id"]
        del self.job["team"]["owner"]
        legacy = json.dumps(self.job)
        with self.store.connection(write=True) as db:
            db.execute("UPDATE jobs SET snapshot = ? WHERE id = ?", (legacy, job_id))
        self.store = Store(self.path)
        before = self.store.detail(job_id)
        self.assertEqual(before["job"]["team"]["owner"], "Владелец задачи")
        self.assertEqual(self.store.overview()["jobs"][0]["team"], before["job"]["team"])
        with self.store.connection() as db:
            self.assertEqual(db.execute("SELECT snapshot FROM jobs WHERE id = ?", (job_id,)).fetchone()[0], legacy)

        old_payload = self.job["team"].copy()
        self.command("update_team", {**old_payload, "owner": "Мария"})
        self.command("update_team", {**old_payload, "planner": "Ирина"})
        self.assertEqual(self.job["team"]["owner"], "Мария")
        self.command("decide_plan", {"hash": self.job["plans"][-1]["hash"], "decision": "approve"})
        events = self.store.detail(job_id)["events"]
        self.assertEqual([item["actor"] for item in events[:3]], ["Мария", "Мария", "Владелец задачи"])
        self.assertEqual(events[3:], before["events"])
