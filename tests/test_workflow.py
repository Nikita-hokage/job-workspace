from concurrent.futures import ThreadPoolExecutor
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

    def command(self, kind, data, *, op_id=None):
        self.job = self.store.apply(self.job["id"], op_id or str(uuid4()), self.job["revision"], kind, data)
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
