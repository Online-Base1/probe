"""Симуляция ревьюера без сети: все исходы resolve/review/report (D-101..D-103).

python3 -m unittest discover -s .github/reviewer/tests
"""

import json
import os
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import fakes as F  # noqa: E402
import reviewer as rv  # noqa: E402
import reviewer_lib as rl  # noqa: E402

EXPECTED = os.path.join(HERE, "..", "expected-models.json")
CANARY_PR = 50
PROBE_ISSUE = 42


class Base(unittest.TestCase):
    def setUp(self):
        self._saved = (rl.CANARY_PR, rl.WRITE_PROBE_ISSUE)
        rl.CANARY_PR, rl.WRITE_PROBE_ISSUE = CANARY_PR, PROBE_ISSUE
        self.w = F.World()
        self.w.prs.append(F.World.agent_pr(CANARY_PR, sha="d" * 40, ref="canary/known-defect", base="canary-base"))
        self.w.commit_dates["d" * 40] = "2026-01-01T00:00:00Z"
        self.w.comments[CANARY_PR] = []

    def tearDown(self):
        rl.CANARY_PR, rl.WRITE_PROBE_ISSUE = self._saved

    def gh(self):
        return rv.GitHub("tok", transport=self.w.transport)

    def resolve(self, **kw):
        return rv.resolve(F.workflow_run(**kw), self.gh(), F.REPO)

    def review(self, client=None, trigger="agent", pr=7, head=F.HEAD):
        self.client = client or F.FakeOpenAI()
        self.ctx = {"repo": F.REPO, "pr": str(pr), "head_sha": head, "run_id": str(F.RUN_ID), "trigger": trigger,
                    "gh_read": self.gh(), "gh_probe": self.gh(), "gh_knowledge": self.gh(),
                    "openai_factory": lambda: self.client, "expected_models": EXPECTED}
        return rv.review(self.ctx)


class Resolve(Base):
    def test_one_pr(self):
        out = self.resolve()
        self.assertEqual((out["outcome"], out["pr"], out["head_sha"]), ("REVIEW", "7", F.HEAD))

    def test_run_id_from_event(self):
        self.assertEqual(self.resolve()["run_id"], str(F.RUN_ID))

    def test_no_artifact(self):
        self.w.artifacts = []
        self.assertEqual((self.resolve()["outcome"], self.resolve()["reason"]), ("UNKNOWN", "no_task_artifact"))

    def test_two_artifacts(self):
        self.w.artifacts.append({"id": 12, "name": F.artifact_name(b"other"), "expired": False})
        self.assertEqual(self.resolve()["reason"], "multiple_task_artifacts:2")

    def test_hash_mismatch(self):
        self.w.artifact_zip[11] = F.task_zip(b"Add clamp() -- tampered\n")
        out = self.resolve()
        self.assertEqual((out["outcome"], out["reason"]), ("UNKNOWN", "task_hash_mismatch"))

    def test_artifact_other_file(self):
        self.w.artifact_zip[11] = F.task_zip(self.w.task, name="other.txt")
        self.assertTrue(self.resolve()["reason"].startswith("task_artifact_content"))

    def test_bad_artifact_name(self):
        self.w.artifacts[0]["name"] = "agent-task-latest"
        self.assertEqual(self.resolve()["reason"], "bad_task_artifact_name")

    def test_expired(self):
        self.w.artifacts[0]["expired"] = True
        self.assertEqual(self.resolve()["reason"], "task_artifact_expired")

    def test_redirect_drops_authorization(self):
        self.resolve()
        self.assertEqual(self.w.redirect_auth, [False])

    def test_zero_prs_success_unknown(self):
        self.w.prs = []
        out = self.resolve()
        self.assertEqual((out["outcome"], out["reason"]), ("UNKNOWN", "no_agent_pr"))

    def test_zero_prs_failure_incomplete(self):
        self.w.prs = []
        out = self.resolve(conclusion="failure")
        self.assertEqual((out["outcome"], out["reason"]), ("AGENT_RUN_INCOMPLETE", "failure"))

    def test_failure_with_pr_reviews(self):
        self.assertEqual(self.resolve(conclusion="failure")["outcome"], "REVIEW")

    def test_two_prs(self):
        self.w.prs.append(F.World.agent_pr(8, sha="e" * 40, ref="agent/other"))
        self.w.commit_dates["e" * 40] = "2026-09-28T10:10:00Z"
        out = self.resolve()
        self.assertEqual((out["outcome"], out["reason"]), ("UNKNOWN", "multiple_agent_prs:2"))
        self.assertEqual(self.w.posted, [])

    def test_window_not_widened(self):
        self.w.commit_dates[F.HEAD] = "2026-09-28T10:20:01Z"
        self.assertEqual(self.resolve()["reason"], "no_agent_pr")

    def test_foreign_author_or_branch_ignored(self):
        self.w.prs = [F.World.agent_pr(7, login="MartynPin"), F.World.agent_pr(9, ref="feature/x")]
        self.assertEqual(self.resolve()["reason"], "no_agent_pr")

    def test_cancelled_and_timed_out(self):
        for c in ("cancelled", "timed_out"):
            out = self.resolve(conclusion=c)
            self.assertEqual((out["outcome"], out["reason"]), ("AGENT_RUN_INCOMPLETE", c))

    def test_unexpected_workflow(self):
        self.assertTrue(self.resolve(path=".github/workflows/ci.yml")["reason"].startswith("unexpected_workflow"))

    def test_canary_trigger(self):
        out = self.resolve(path=".github/workflows/canary-trigger.yml")
        self.assertEqual((out["outcome"], out["pr"], out["trigger"]), ("REVIEW", "50", "canary"))

    def test_canary_wrong_base(self):
        self.w.prs[-1]["base"]["ref"] = "main"
        self.assertEqual(self.resolve(path=".github/workflows/canary-trigger.yml")["reason"], "canary_pr_base")

    def test_canary_not_configured(self):
        rl.CANARY_PR = None
        self.assertEqual(self.resolve(path=".github/workflows/canary-trigger.yml")["reason"], "canary_pr_not_configured")


class Review(Base):
    def test_done_zero_findings(self):
        st = self.review()
        self.assertEqual((st["result"], st["findings"], st["prompt_sha"], st["format_sha"]), ("DONE", 0, F.PROMPT_SHA, F.FORMAT_SHA))
        (pr, body), = self.w.posted
        self.assertEqual(pr, 7)
        self.assertIn(rl.done_marker(F.HEAD), body)
        self.assertIn("Находок нет", body)
        self.assertIn(F.PROMPT_SHA, body)
        self.assertIn(F.FORMAT_SHA, body)

    def test_instructions_carry_prompt_and_format(self):
        self.review()
        req = next(r for r in self.client.requests if "instructions" in r)
        self.assertTrue(req["instructions"].startswith("You are the reviewer."))
        self.assertIn("# Формат находок", req["instructions"])

    def test_request_whitelist_canary(self):
        self.review()
        req = next(r for r in self.client.requests if "instructions" in r)
        blob = json.dumps(req, ensure_ascii=False)
        self.assertNotIn(F.CANARY, blob, "body/title/commit message/check output leaked into the request")
        self.assertEqual(req["model"], "gpt-5.3-codex")

    def test_task_bytes_crlf_non_ascii(self):
        task = "Сделай clamp()\r\nи тесты: ≤ ≥ — ✓\r\n".encode("utf-8")
        self.w.task = task
        self.w.artifacts = [{"id": 11, "name": F.artifact_name(task), "expired": False}]
        self.w.artifact_zip[11] = F.task_zip(task)
        self.assertEqual(self.review()["result"], "DONE")
        sent = self.ctx["sent"][0][0]["content"][0]["text"].encode("utf-8")
        self.assertEqual(sent, task)
        self.assertEqual(F.artifact_name(sent), self.w.artifacts[0]["name"])

    def test_task_not_utf8(self):
        task = b"\xff\xfe bad"
        self.w.artifacts = [{"id": 11, "name": F.artifact_name(task), "expired": False}]
        self.w.artifact_zip[11] = F.task_zip(task)
        self.assertEqual(self.review()["result"], "UNKNOWN(task_not_utf8)")

    def test_already_reviewed(self):
        self.w.comments[7] = [{"user": {"login": rl.REVIEWER_LOGIN}, "body": rl.done_marker(F.HEAD)}]
        st = self.review()
        self.assertTrue(st["skipped"])
        self.assertEqual(self.client.requests, [])
        self.assertEqual(self.w.posted, [])

    def test_marker_by_other_user_ignored(self):
        self.w.comments[7] = [{"user": {"login": rl.WORKER_LOGIN}, "body": rl.done_marker(F.HEAD)}]
        st = self.review()
        self.assertFalse(st["skipped"])
        self.assertEqual(st["result"], "DONE")

    def test_prompt_missing(self):
        self.w.prompt = None
        self.assertEqual(self.review()["result"], "UNKNOWN(prompt_missing)")
        self.assertEqual(self.w.posted, [])

    def test_format_missing(self):
        self.w.format = None
        self.assertEqual(self.review()["result"], "UNKNOWN(format_missing)")

    def test_format_without_json_block(self):
        self.w.format = b"# Format\n\nNo schema here.\n"
        self.assertEqual(self.review()["result"], "UNKNOWN(format_schema_blocks:0)")

    def test_format_two_json_blocks(self):
        self.w.format = F.format_md(F.SCHEMA, blocks=2)
        self.assertEqual(self.review()["result"], "UNKNOWN(format_schema_blocks:2)")

    def test_format_block_not_json(self):
        self.w.format = b"```json\n{not json\n```\n"
        self.assertEqual(self.review()["result"], "UNKNOWN(format_schema_not_json)")

    def test_schema_contract(self):
        self.w.format = F.format_md({"type": "object", "properties": {"items": {"type": "array"}}})
        self.assertEqual(self.review()["result"], "UNKNOWN(schema_contract)")

    def test_schema_unsupported_keyword(self):
        s = json.loads(json.dumps(F.SCHEMA))
        s["properties"]["findings"]["items"]["properties"]["file"]["pattern"] = "^lib/"
        self.w.format = F.format_md(s)
        self.assertTrue(self.review()["result"].startswith("UNKNOWN(schema_unsupported"))

    def test_models_list_wrong(self):
        st = self.review(F.FakeOpenAI(models=("gpt-5.3-codex", "gpt-4.1-nano")))
        self.assertEqual(st["result"], "UNKNOWN(openai_boundary:(в)=FAIL)")
        self.assertEqual(self.w.posted, [])

    def test_nano_answered(self):
        self.assertEqual(self.review(F.FakeOpenAI(nano_ok=True))["result"], "UNKNOWN(openai_boundary:(д)=FAIL)")

    def test_response_not_schema(self):
        bad = json.dumps({"findings": [{"file": "lib/x.ts", "line": "7", "message": "m"}]})
        self.assertTrue(self.review(F.FakeOpenAI(review_text=bad))["result"].startswith("UNKNOWN(response_schema"))
        self.assertEqual(self.w.posted, [])

    def test_response_not_json(self):
        self.assertEqual(self.review(F.FakeOpenAI(review_text="looks fine"))["result"], "UNKNOWN(response_not_json)")

    def test_response_incomplete(self):
        self.assertEqual(self.review(F.FakeOpenAI(review_status="incomplete"))["result"], "UNKNOWN(response_status:incomplete)")

    def test_usage_zero(self):
        self.assertEqual(self.review(F.FakeOpenAI(usage=(1200, 0)))["result"], "UNKNOWN(usage_missing_or_zero)")

    def test_findings_listed_and_sanitized(self):
        text = json.dumps({"findings": [{"file": "lib/x.ts", "line": 2, "message": "ping @owner ```x``` ghs_abcdef1234567890"}]})
        st = self.review(F.FakeOpenAI(review_text=text))
        self.assertEqual((st["result"], st["findings"]), ("DONE", 1))
        body = self.w.posted[0][1]
        self.assertNotIn("@owner", body)
        self.assertNotIn("ghs_abcdef", body)
        self.assertNotIn("```x```", body)

    def test_p1_write_allowed(self):
        self.w.p1_status = 201
        self.assertEqual(self.review()["result"], "UNKNOWN(p1_knowledge_comment:write_allowed:201)")
        self.assertEqual(self.w.deleted, [555])
        self.assertEqual(self.client.requests, [])

    def test_p2_approve_allowed(self):
        self.w.p2_status = 200
        self.assertEqual(self.review()["result"], "UNKNOWN(p2_canary_approve:write_allowed:200)")
        self.assertEqual(self.client.requests, [])

    def test_probe_other_status(self):
        self.w.p1_status = 404
        self.assertEqual(self.review()["result"], "UNKNOWN(p1_knowledge_comment:unexpected_status:404)")

    def test_p2_targets_canary_pr_only(self):
        self.review()
        approvals = [u for m, u in self.w.calls if m == "POST" and u.endswith("/reviews")]
        self.assertEqual(approvals, [f"https://api.github.com/repos/{F.REPO}/pulls/{CANARY_PR}/reviews"])

    def test_probes_not_configured(self):
        rl.WRITE_PROBE_ISSUE = None
        self.assertEqual(self.review()["result"], "UNKNOWN(write_probe_issue_not_configured)")

    def test_comment_post_refused(self):
        self.w.comment_status = 403
        self.assertEqual(self.review()["result"], "UNKNOWN(comment_post:403)")

    def test_head_moved(self):
        self.assertEqual(self.review(head="f" * 40)["result"], "UNKNOWN(head_moved)")

    def test_canary_missed(self):
        st = self.review(trigger="canary", pr=CANARY_PR, head="d" * 40)
        self.assertEqual((st["result"], st["canary"]), ("UNKNOWN(canary_missed)", "FAIL"))

    def test_canary_found(self):
        text = json.dumps({"findings": [
            {"file": "tests/unit/paginate.test.ts", "line": 3, "message": "no test with a remainder"},
            {"file": "lib/paginate.ts", "line": 9, "message": "Math.floor drops the last partial page"}]})
        st = self.review(F.FakeOpenAI(review_text=text), trigger="canary", pr=CANARY_PR, head="d" * 40)
        self.assertEqual((st["result"], st["canary"]), ("DONE", "PASS"))
        self.assertIn(rl.done_marker("d" * 40, str(F.RUN_ID)), self.w.posted[0][1])

    def test_canary_only_missing_test_finding_is_fail(self):
        text = json.dumps({"findings": [{"file": "tests/unit/paginate.test.ts", "line": 3, "message": "no test with a remainder"}]})
        st = self.review(F.FakeOpenAI(review_text=text), trigger="canary", pr=CANARY_PR, head="d" * 40)
        self.assertEqual((st["result"], st["canary"]), ("UNKNOWN(canary_missed)", "FAIL"))

    def test_canary_reviewed_every_night(self):
        # Вчерашний комментарий того же head_sha, но другого прогона canary-trigger
        # не выключает сегодняшнее ревью (D-105 §a).
        self.w.comments[CANARY_PR] = [{"user": {"login": rl.REVIEWER_LOGIN}, "body": rl.done_marker("d" * 40, "899999")}]
        text = json.dumps({"findings": [{"file": "lib/paginate.ts", "line": 9, "message": "floor"}]})
        st = self.review(F.FakeOpenAI(review_text=text), trigger="canary", pr=CANARY_PR, head="d" * 40)
        self.assertFalse(st["skipped"])
        self.assertEqual(st["canary"], "PASS")

    def test_canary_same_run_skipped(self):
        self.w.comments[CANARY_PR] = [{"user": {"login": rl.REVIEWER_LOGIN}, "body": rl.done_marker("d" * 40, str(F.RUN_ID))}]
        st = self.review(trigger="canary", pr=CANARY_PR, head="d" * 40)
        self.assertTrue(st["skipped"])

    def test_canary_wrong_line(self):
        text = json.dumps({"findings": [{"file": "lib/paginate.ts", "line": 8, "message": "x"}]})
        st = self.review(F.FakeOpenAI(review_text=text), trigger="canary", pr=CANARY_PR, head="d" * 40)
        self.assertEqual(st["canary"], "FAIL")


class Report(unittest.TestCase):
    def run_report(self, **env):
        return rv.report(env)

    def test_done(self):
        lines, code = self.run_report(RESOLVE_OUTCOME="REVIEW", RESOLVE_TRIGGER="agent", REVIEW_RESULT="DONE",
                                      REVIEW_FINDINGS="0", REVIEW_PROMPT_SHA=F.PROMPT_SHA, REVIEW_MODEL="gpt-5.3-codex",
                                      REVIEW_CANARY="n/a")
        self.assertEqual(code, 0)
        self.assertIn("REVIEW_RESULT=DONE", lines)
        self.assertIn("FINDINGS=0 — находок нет", lines)
        self.assertIn("CANARY=n/a", lines)

    def test_record_line_fixed_form(self):
        lines, _ = self.run_report(RESOLVE_OUTCOME="REVIEW", RESOLVE_TRIGGER="agent", RESOLVE_PR="7",
                                   RESOLVE_HEAD_SHA=F.HEAD, REVIEW_RESULT="DONE", REVIEW_FINDINGS="2",
                                   REVIEW_PROMPT_SHA=F.PROMPT_SHA, REVIEW_FORMAT_SHA=F.FORMAT_SHA,
                                   REVIEW_MODEL="gpt-5.3-codex", REVIEW_CANARY="n/a")
        self.assertEqual(lines[-1], f"REVIEW_RECORD KIND=agent PR=7 HEAD_SHA={F.HEAD} RESULT=DONE FINDINGS=2 "
                                    f"PROMPT_SHA={F.PROMPT_SHA} FORMAT_SHA={F.FORMAT_SHA} MODEL=gpt-5.3-codex CANARY=n/a")

    def test_record_line_unknown(self):
        lines, _ = self.run_report(RESOLVE_OUTCOME="UNKNOWN", RESOLVE_REASON="multiple_agent_prs:2", RESOLVE_TRIGGER="agent")
        self.assertEqual(lines[-1], "REVIEW_RECORD KIND=agent PR=n/a HEAD_SHA=n/a RESULT=UNKNOWN(multiple_agent_prs:2) "
                                    "FINDINGS=n/a PROMPT_SHA=n/a FORMAT_SHA=n/a MODEL=n/a CANARY=n/a")

    def test_incomplete_not_red(self):
        lines, code = self.run_report(RESOLVE_OUTCOME="AGENT_RUN_INCOMPLETE", RESOLVE_REASON="cancelled")
        self.assertEqual((lines[0], code), ("REVIEW_RESULT=AGENT_RUN_INCOMPLETE(cancelled)", 0))

    def test_unknown_red(self):
        lines, code = self.run_report(RESOLVE_OUTCOME="UNKNOWN", RESOLVE_REASON="no_task_artifact")
        self.assertEqual((lines[0], code), ("REVIEW_RESULT=UNKNOWN(no_task_artifact)", 1))

    def test_review_job_crashed(self):
        lines, code = self.run_report(RESOLVE_OUTCOME="REVIEW", RESOLVE_TRIGGER="agent", REVIEW_JOB_RESULT="failure")
        self.assertEqual((lines[0], code), ("REVIEW_RESULT=UNKNOWN(review_job_failure)", 1))

    def test_resolve_job_crashed(self):
        lines, code = self.run_report(RESOLVE_JOB_RESULT="failure")
        self.assertEqual((lines[0], code), ("REVIEW_RESULT=UNKNOWN(resolve_job_failure)", 1))

    def test_canary_fail_red(self):
        lines, code = self.run_report(RESOLVE_OUTCOME="REVIEW", RESOLVE_TRIGGER="canary",
                                      REVIEW_RESULT="UNKNOWN(canary_missed)", REVIEW_CANARY="FAIL")
        self.assertEqual(code, 1)
        self.assertIn("CANARY=FAIL", lines)

    def test_canary_fail_red_even_if_done(self):
        _, code = self.run_report(RESOLVE_OUTCOME="REVIEW", RESOLVE_TRIGGER="canary",
                                  REVIEW_RESULT="DONE", REVIEW_CANARY="FAIL")
        self.assertEqual(code, 1)

    def test_canary_unknown_before_review_is_fail(self):
        lines, code = self.run_report(RESOLVE_OUTCOME="UNKNOWN", RESOLVE_REASON="no_task_artifact", RESOLVE_TRIGGER="canary")
        self.assertIn("CANARY=FAIL", lines)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
