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
        for name in ("reviewer.yml", "reviewer-ci.yml", "canary-trigger.yml", "digest.yml"):
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
        self.assertRegex(role, r"(?m)^    needs: \[task-snapshot, test-author, stub-check\]$")
        self.assertNotIn("agent-task", role)

    def test_test_author_job(self):
        # D-174 §e.E: только снимок задания на входе, артефакт agent-tests-<sha> на
        # выходе; WIF автора тестов; factory-knowledge — узким токеном ревьюера;
        # записи в GitHub нет и токена исполнителя нет.
        t = read("agent.yml")
        ta_ = job_block(t, "test-author")
        self.assertRegex(ta_, r"(?m)^    needs: task-snapshot$")
        perms = re.search(r"(?m)^    permissions:\n((?:      .*\n)+)", ta_).group(1)
        self.assertEqual(sorted(perms.split()), sorted(["contents:", "read", "id-token:", "write"]))
        self.assertIn("name: ${{ needs.task-snapshot.outputs.artifact }}", ta_)
        self.assertIn("OPENAI_TEST_AUTHOR_SERVICE_ACCOUNT_ID: ${{ vars.OPENAI_TEST_AUTHOR_SERVICE_ACCOUNT_ID }}", ta_)
        self.assertNotIn("OPENAI_REVIEWER_SERVICE_ACCOUNT_ID", ta_)
        self.assertNotIn("FACTORY_APP_PRIVATE_KEY", ta_)          # токен исполнителя не выпускается
        self.assertEqual(ta_.count("create-github-app-token@"), 1)
        mint = ta_[ta_.index("create-github-app-token@"):ta_.index("- name: Run test author")]
        self.assertIn("repositories: factory-knowledge", mint)
        self.assertIn("permission-contents: read", mint)
        self.assertNotIn("write", mint)
        self.assertIn("persist-credentials: false", ta_)
        self.assertIn(".github/reviewer/test_author.py author", ta_)
        self.assertIn('echo "artifact=agent-tests-$(sha256sum "$OUT" | cut -d\' \' -f1)"', ta_)
        self.assertIn("name: ${{ steps.author.outputs.artifact }}", ta_)

    def test_stub_check_job_has_no_credentials(self):
        # Здесь исполняется код модели: ни токенов, ни id-token, ни учётных данных git.
        sc = job_block(read("agent.yml"), "stub-check")
        self.assertRegex(sc, r"(?m)^    needs: test-author$")
        self.assertRegex(sc, r"(?m)^    permissions: \{\}$")
        self.assertNotIn("create-github-app-token", sc)
        self.assertNotIn("secrets.", sc)
        self.assertNotIn("if:", sc.replace("if: github.ref != 'refs/heads/main'", ""))   # вне условий
        self.assertIn("persist-credentials: false", sc)
        self.assertIn("STUB: \"1\"", sc)
        self.assertIn("npm ci --ignore-scripts", sc)
        self.assertIn("--reporter=json", sc)
        self.assertIn("test_author.py stub-verdict || exit 1", sc)
        self.assertLess(sc.index("npm ci --ignore-scripts"), sc.index("vitest run"))

    def test_role_freezes_tests_before_coder(self):
        role = job_block(read("agent.yml"), "role")
        freeze = self.step_block(role, "Freeze tests (branch, one commit, tree)")
        self.assertLess(role.index("- name: Environment check (runtime)"), role.index("- name: Freeze tests"))
        self.assertLess(role.index("- name: Freeze tests"), role.index("- name: Run role"))
        self.assertNotIn("if:", freeze.split("run: |")[0])
        self.assertIn('[ "$TESTS_ARTIFACT" != "$STUB_CHECKED" ]', freeze)
        self.assertIn("STUB_CHECKED: ${{ needs.stub-check.outputs.artifact }}", freeze)
        self.assertIn('branch="agent/${TODAY}-$(python3 .github/reviewer/test_author.py slug)-${RUN_NUMBER}"', freeze)
        self.assertIn("grep -v '^?? tests/unit/'", freeze)
        self.assertEqual(freeze.count("commit -q -m"), 1)
        self.assertIn('tree="$(git rev-parse HEAD:tests)"', freeze)
        self.assertIn('echo "tree=$tree" >> "$GITHUB_OUTPUT"', freeze)

    def test_coder_writes_product_paths_only(self):
        role = job_block(read("agent.yml"), "role")
        allowed = re.search(r'--allowedTools "([^"]*)"', role).group(1).split(",")
        self.assertNotIn("Edit", allowed)
        self.assertNotIn("Write", allowed)
        writes = sorted(a for a in allowed if a.startswith(("Edit(", "Write(")))
        self.assertEqual(writes, sorted(f"{t}({p}/**)" for t in ("Edit", "Write")
                                        for p in ("app", "lib", "components", "prisma")))
        self.assertNotIn("Bash(git checkout -b:*)", allowed)
        self.assertIn('--disallowedTools "Edit(tests/**),Write(tests/**)"', role)
        prompt = role[role.index("prompt: |"):]
        self.assertIn("${{ steps.freeze.outputs.branch }}", prompt)
        self.assertIn("Тесты в tests/ ЗАМОРОЖЕНЫ", prompt)
        self.assertNotIn("--body-file", prompt)
        self.assertIn("tests/unit/agent-tests-canary-{0}.txt", prompt)

    def test_tests_canary_and_tree_check(self):
        role = job_block(read("agent.yml"), "role")
        sd = self.step_block(role, "Surface permission denials")
        self.assertIn('contains("agent-tests-canary-" + $rid)', sd)
        self.assertIn("select((is_canary or is_tests_canary) | not)", sd)
        vp = self.step_block(role, "Verify path scoping (tests canary)")
        self.assertIn("if: always()", vp)
        self.assertIn("tests_canary_found == true", vp)
        ve = self.step_block(role, "Verify envelope via GitHub API")
        self.assertIn("FROZEN_TREE: ${{ steps.freeze.outputs.tree }}", ve)
        self.assertIn('now_tree="$(git rev-parse FETCH_HEAD:tests)"', ve)
        self.assertIn('[ "$now_tree" != "$FROZEN_TREE" ]', ve)
        self.assertIn('[ "$branch" != "$BRANCH" ]', ve)

    def test_role_sets_pr_body_at_create_never_edits(self):
        # BB-47: тело — в gh pr create; gh pr edit не выдаётся (шире: base,
        # reviewers, labels) и запрещён промптом, а не правами.
        role = job_block(read("agent.yml"), "role")
        allowed = re.search(r'--allowedTools "([^"]*)"', role).group(1)
        self.assertIn("Bash(gh pr create --draft:*)", allowed.split(","))
        self.assertNotIn("gh pr edit", allowed)
        prompt = role[role.index("prompt: |"):]
        self.assertIn("`--body", prompt)
        self.assertIn("`gh pr edit` не вызывай никогда", prompt)

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
        self.assertEqual(set(re.findall(r"secrets\.[A-Z_]+", t)), {"secrets.FACTORY_APP_PRIVATE_KEY"})
        self.assertEqual(re.findall(r"permission-[a-z-]+: \w+", probe), ["permission-contents: write"])
        self.assertIn('grep -q "GH013"', probe)
        self.assertIn("refs/heads/canary/known-defect", probe)
        self.assertIn("--allow-empty", probe)
        # bash -e раннера иначе завершит шаг молча на неудачном push (прогон 36516855926).
        self.assertRegex(probe, r"(?m)^          set \+e$")
        self.assertLess(probe.index("set +e"), probe.index('g push "$url"'))
        self.assertLess(probe.index("fetch -q --depth 1"), probe.index('g push "$url"'))

    def test_ff_probe(self):
        t = read("canary-trigger.yml")
        probe = job_block(t, "ff-probe")
        self.assertIn("branch=agent/canary-ff-probe", probe)
        self.assertEqual(re.findall(r"permission-[a-z-]+: \w+", probe), ["permission-contents: write"])
        self.assertRegex(probe, r"(?m)^          set \+e$")
        # положительная пара раньше отрицательной, и отказ сверяется по GH013
        self.assertLess(probe.index("fast-forward (must be accepted)"), probe.index('g push --force "$url"'))
        self.assertIn('grep -q "GH013"', probe)
        self.assertEqual(re.findall(r"secrets\.[A-Z_]+", t), ["secrets.FACTORY_APP_PRIVATE_KEY"] * 2)

    def test_reviewer_has_no_worker_key(self):
        self.assertNotIn("FACTORY_APP_PRIVATE_KEY", read("reviewer.yml"))

    def test_report_permissions(self):
        r = job_block(read("reviewer.yml"), "report")
        self.assertIn("permissions:\n      actions: read\n      contents: read\n", r)

    def test_digest_trigger_is_own_schedule(self):
        # D-121 §c: не job ночного прогона и не workflow_run от него — сводка
        # обязана выйти и тогда, когда ночной прогон не запустился.
        t = read("digest.yml")
        on = t[t.index("\non:\n"):t.index("\npermissions:")]
        self.assertEqual(re.findall(r"(?m)^  ([a-z_]+):", on), ["schedule", "workflow_dispatch"])
        self.assertNotIn("workflow_run", t.split("\nname: digest\n", 1)[1])
        self.assertRegex(t, r"(?m)^permissions: \{\}$")
        self.assertNotIn("digest", read("canary-trigger.yml"))
        # D-133 d: расписание не является временем; построение «через N минут
        # после» недействительно — сводка в 12:00 UTC, окно от прошлой сводки.
        self.assertEqual(re.findall(r'cron: "([^"]+)"', t), ["0 12 * * *"])

    def test_digest_token_scopes(self):
        t = read("digest.yml")
        read_step = "Mint reviewer token (factory-knowledge, contents:read, pull-requests:read)"
        issues = t[t.index("Mint reviewer token (factory-knowledge, issues:write)"):t.index(read_step)]
        self.assertIn("repositories: factory-knowledge", issues)
        self.assertEqual(re.findall(r"permission-[a-z-]+: \w+", issues), ["permission-issues: write"])
        self.assertNotIn("continue-on-error", issues)
        # Чтение factory-knowledge: строка ПРАВИЛА (contents) и заявки коммитов в
        # строке ВЛИВАНИЯ (pull-requests, D-139 решение; площадка: pull_requests=read).
        fk = t[t.index(read_step):t.index("- name: Digest\n")]
        self.assertIn("repositories: factory-knowledge", fk)
        self.assertEqual(sorted(re.findall(r"permission-[a-z-]+: \w+", fk)),
                         ["permission-contents: read", "permission-pull-requests: read"])
        job = job_block(t, "digest")
        self.assertIn("permissions:\n      actions: read\n      contents: read\n      pull-requests: read\n    steps:", job)
        self.assertEqual(set(re.findall(r"secrets\.[A-Z_]+", t)), {"secrets.FACTORY_REVIEWER_APP_PRIVATE_KEY"})
        self.assertIn("GH_TOKEN_DIGEST: ${{ steps.issues.outputs.token }}", t)

    def test_no_issue_triggers(self):
        # Условие D-104 / D-121 §b: по issue и комментариям не запускается ничего,
        # иначе issues:write приложения ревьюера пересматривается.
        for name in sorted(os.listdir(WF)):
            if name.endswith(".yml"):
                on = read(name).split("\non:", 1)[1].split("\npermissions:", 1)[0]
                self.assertNotRegex(on, r"(?m)^\s+(issues|issue_comment|discussion|discussion_comment):", name)

    # --- §18′ п.18 (D-143): названная среда и положительная контрольная ---

    def step_block(self, text, name):
        i = text.index(f"- name: {name}\n")
        j = text.find("\n      - name: ", i + 1)
        return text[i:j if j != -1 else len(text)]

    def test_refusal_probes_job_runs_every_time(self):
        t = read("reviewer.yml")
        job = job_block(t, "refusal-probes")
        # Не зависит от resolve: ни needs, ни if на уровне job.
        self.assertNotRegex(job, r"(?m)^    (needs|if):")
        self.assertIn("    permissions: {}\n", job)
        fk = self.step_block(job, "Mint probe token (factory-knowledge, contents:read)")
        self.assertIn("repositories: factory-knowledge", fk)
        self.assertEqual(re.findall(r"permission-[a-z-]+: \w+", fk), ["permission-contents: read"])
        pr = self.step_block(job, "Mint probe token (probe, issues:write, pull-requests:read)")
        self.assertEqual(sorted(re.findall(r"permission-[a-z-]+: \w+", pr)),
                         ["permission-issues: write", "permission-pull-requests: read"])
        self.assertIn("run: python3 .github/reviewer/reviewer.py probes", job)
        self.assertEqual(rl.REFUSAL_MARKER, "REFUSAL_PROBE")

    def test_static_env_check_in_reviewer_ci(self):
        unit = job_block(read("reviewer-ci.yml"), "unit")
        self.assertIn("            .github/environment.lock.json\n", unit)
        self.assertLess(unit.index("run: python3 .github/reviewer/env_check.py static"),
                        unit.index("- name: Reviewer unit tests (offline)"))
        self.assertNotIn("continue-on-error", self.step_block(unit, "Environment lock (static)"))

    def test_runtime_env_check_in_three_workflows(self):
        for name, wf in (("reviewer.yml", "reviewer"), ("agent.yml", "agent"), ("digest.yml", "digest")):
            t = read(name)
            check = self.step_block(t, "Environment check (runtime)")
            self.assertIn(f"env_check.py runtime --workflow {wf}", check, name)
            self.assertIn('--out "$RUNNER_TEMP/env-check.json"', check, name)
            up = self.step_block(t, "Upload environment check")
            self.assertIn("actions/upload-artifact@", up, name)
            self.assertIn(f"name: env-check-{wf}-${{{{ github.run_id }}}}", up, name)
            self.assertIn("if: always()", up, name)
            self.assertIn("continue-on-error: true", up, name)
            self.assertLess(t.index("- name: Environment check (runtime)"), t.index("- name: Upload environment check"))

    def test_runtime_env_check_placement(self):
        rv_ = job_block(read("reviewer.yml"), "report")
        self.assertIn("            .github/environment.lock.json\n", rv_)
        self.assertLess(rv_.index("- name: REVIEW_RESULT"), rv_.index("- name: Environment check (runtime)"))
        self.assertIn("if: always()", self.step_block(rv_, "Environment check (runtime)"))
        dg = read("digest.yml")
        self.assertIn("            .github/environment.lock.json\n", dg)
        # сводка выходит и при сломанной сверке (D-121 §c)
        self.assertIn("continue-on-error: true", self.step_block(dg, "Environment check (runtime)"))
        self.assertLess(dg.index("- name: Environment check (runtime)"), dg.index("- name: Digest\n"))
        self.assertIn("ENV_CHECK_FILE: ${{ runner.temp }}/env-check.json", self.step_block(dg, "Digest"))
        role = job_block(read("agent.yml"), "role")
        check = self.step_block(role, "Environment check (runtime)")
        # версия CLI — наша: расхождение обязано остановить роль до её запуска
        self.assertIn('--cli "$CLAUDE_PATH"', check)
        self.assertIn("CLAUDE_PATH: ${{ steps.claude_cli.outputs.path }}", check)
        self.assertNotIn("continue-on-error", check)
        self.assertNotIn("if: always()", check)
        self.assertLess(role.index("- name: Install Claude Code (verified)"), role.index("- name: Environment check (runtime)"))
        self.assertLess(role.index("- name: Environment check (runtime)"), role.index("- name: Run role"))

    def test_subset_token_test(self):
        t = read("reviewer-app-token-test.yml")
        self.assertIn('{"repositories":["factory-knowledge"],"permissions":{"contents":"read"}}', t)
        self.assertIn("del(.token)", t)
        self.assertIn("trap cleanup EXIT", t)
        self.assertRegex(t, r"(?m)^  workflow_dispatch:$")


if __name__ == "__main__":
    unittest.main()
