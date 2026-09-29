"""Структура workflow-файлов ревьюера и снимка задания (без YAML-библиотеки).

В reviewer-ci.yml файлы .github/workflows есть в checkout, и тесты обязательны
(REVIEWER_WORKFLOW_TESTS=required); в openai-wif-test.yml их нет — пропуск.
"""

import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import reviewer_lib as rl  # noqa: E402

WF = os.path.normpath(os.path.join(HERE, "..", "..", "workflows"))
REQUIRED = os.environ.get("REVIEWER_WORKFLOW_TESTS") == "required"


def read(name):
    with open(os.path.join(WF, name), encoding="utf-8") as fh:
        return fh.read()


def job_block(text, job):
    m = re.search(rf"^  {re.escape(job)}:\n(.*?)(?=^  [A-Za-z0-9_-]+:\n|\Z)", text, re.S | re.M)
    assert m, f"job {job} not found"
    return m.group(1)


@unittest.skipUnless(REQUIRED or os.path.isfile(os.path.join(WF, "reviewer.yml")), "workflow files not checked out")
class Workflows(unittest.TestCase):
    def test_reviewer_trigger(self):
        t = read("reviewer.yml")
        self.assertIn("workflow_run:\n    workflows: [agent, canary-trigger]\n    types: [completed]\n    branches: [main]", t)
        self.assertRegex(t, r"(?m)^permissions: \{\}$")
        self.assertRegex(read("agent.yml"), r"(?m)^name: agent$")
        self.assertRegex(read("canary-trigger.yml"), r"(?m)^name: canary-trigger$")

    def test_reviewer_token_scopes(self):
        t = read("reviewer.yml")
        fk = t[t.index("Mint reviewer token (factory-knowledge"):t.index("Mint reviewer token (probe")]
        self.assertIn("repositories: factory-knowledge", fk)
        self.assertEqual(re.findall(r"permission-[a-z-]+: \w+", fk), ["permission-contents: read"])
        pr = t[t.index("Mint reviewer token (probe"):t.index("- name: Review\n")]
        self.assertEqual(sorted(re.findall(r"permission-[a-z-]+: \w+", pr)),
                         ["permission-issues: write", "permission-pull-requests: read"])

    def test_review_concurrency_and_gate(self):
        r = job_block(read("reviewer.yml"), "review")
        self.assertIn("group: review-${{ needs.resolve.outputs.pr }}-${{ needs.resolve.outputs.head_sha }}", r)
        self.assertIn("cancel-in-progress: false", r)
        self.assertIn("if: needs.resolve.outputs.outcome == 'REVIEW'", r)

    def test_no_untrusted_expressions_in_run(self):
        for name in ("reviewer.yml", "reviewer-ci.yml", "canary-trigger.yml"):
            t = read(name)
            self.assertNotRegex(t, r"github\.event\.(pull_request|workflow_run)\.(title|body|head_commit|display_title)", name)

    def test_task_snapshot_before_role_from_inputs(self):
        t = read("agent.yml")
        snap = job_block(t, "task-snapshot")
        self.assertIn("TASK: ${{ inputs.task }}", snap)
        self.assertIn("printf '%s' \"$TASK\"", snap)
        self.assertNotIn("actions/checkout", snap)
        self.assertIn("name: ${{ steps.snap.outputs.artifact }}", snap)
        self.assertIn("artifact=agent-task-$sha", snap)
        role = job_block(t, "role")
        self.assertRegex(role, r"(?m)^    needs: task-snapshot$")
        self.assertNotIn("agent-task", role)

    def test_worker_probe_before_role(self):
        role = job_block(read("agent.yml"), "role")
        self.assertLess(role.index("Worker token cannot read factory-knowledge"), role.index("- name: Run role"))
        self.assertLess(role.index("Mint app installation token"), role.index("Worker token cannot read factory-knowledge"))

    def test_ci_paths_match_lib(self):
        t = read("reviewer-ci.yml")
        self.assertIn(f"for path in {rl.PROMPT_PATH} {rl.FORMAT_PATH}; do", t)
        self.assertEqual((rl.PROMPT_PATH, rl.FORMAT_PATH), ("prompts/05-review.md", "standards/findings-format.md"))
        self.assertIn("if: ${{ !startsWith(github.head_ref, 'agent/') }}", t)
        self.assertIn('grep -qF "standards/findings-format.md"', t)
        self.assertIn("UNKNOWN(prompt_without_format_ref)", t)

    def test_canary_trigger_snapshot_and_push_probe(self):
        t = read("canary-trigger.yml")
        self.assertRegex(t, r"(?m)^permissions: \{\}$")
        self.assertNotIn("actions/checkout", t)
        self.assertIn(rl.CANARY_EXPECTED["file"], t)
        snap = job_block(t, "snapshot")
        self.assertNotIn("secrets.", snap)
        probe = job_block(t, "push-probe")
        # Только ключ исполнителя и только contents:write на probe; ключа ревьюера здесь нет.
        self.assertEqual(re.findall(r"secrets\.[A-Z_]+", t), ["secrets.FACTORY_APP_PRIVATE_KEY"])
        self.assertEqual(re.findall(r"permission-[a-z-]+: \w+", probe), ["permission-contents: write"])
        self.assertIn('grep -q "GH013"', probe)
        self.assertIn("refs/heads/canary/known-defect", probe)
        self.assertIn("--allow-empty", probe)
        # bash -e раннера иначе завершит шаг молча на неудачном push (прогон 36516855926).
        self.assertRegex(probe, r"(?m)^          set \+e$")
        self.assertLess(probe.index("set +e"), probe.index('g push "$url"'))
        self.assertLess(probe.index("fetch -q --depth 1"), probe.index('g push "$url"'))

    def test_reviewer_has_no_worker_key(self):
        self.assertNotIn("FACTORY_APP_PRIVATE_KEY", read("reviewer.yml"))

    def test_report_permissions(self):
        r = job_block(read("reviewer.yml"), "report")
        self.assertIn("permissions:\n      actions: read\n      contents: read\n", r)

    def test_subset_token_test(self):
        t = read("reviewer-app-token-test.yml")
        self.assertIn('{"repositories":["factory-knowledge"],"permissions":{"contents":"read"}}', t)
        self.assertIn("del(.token)", t)
        self.assertIn("trap cleanup EXIT", t)
        self.assertRegex(t, r"(?m)^  workflow_dispatch:$")


if __name__ == "__main__":
    unittest.main()
