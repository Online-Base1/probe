"""Ночная сводка (D-121): строки, DIGEST и публикация — без сети."""

import datetime
import json
import os
import re
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import digest as dg  # noqa: E402
import digest_lib as dl  # noqa: E402
import fakes as F  # noqa: E402

NOW = datetime.datetime(2026, 10, 12, 10, 47, 0)
CANARY_RUN, REVIEWER_RUN, OWN_RUN = 38130803000, 38130814643, 38200000000
TITLES = [t for _, t in dl.LINES]


def reviewer_log(upstream=CANARY_RUN, trigger="canary", result="DONE", findings="1", canary="PASS",
                 retention="not_observed", models=("PASS", "PASS", "PASS")):
    # Вид строк — как в журнале прогона 38130814643 (метка времени перед текстом).
    t = "2026-10-12T10:20:56.5993704Z "
    lines = [t + json.dumps({"run_id": str(upstream), "trigger": trigger, "pr": "34", "head_sha": "a" * 40},
                            ensure_ascii=False)]
    if models:
        lines += [t + f"(в) models.list == expected: {models[0]} — models=['gpt-5.3-codex']",
                  t + f"(г) responses.create allowed model: {models[1]} — model=gpt-5.3-codex",
                  t + f"(д) responses.create denied model: {models[2]} — code=model_not_found"]
    lines.append(t + f"REVIEW_LEDGER kind={trigger} pr=34 head={'a' * 40} run_date=2026-10-12 expires=not_observed "
                     f"retention={retention} result={result} findings={findings} prompt_sha=c format_sha=f "
                     f"model=gpt-5.3-codex canary={canary} d086=excluded")
    return "\n".join(lines) + "\n"


def run(id_, wf, conclusion="success", event="schedule", status="completed", created="2026-10-12T10:07:08Z"):
    return {"id": id_, "path": f".github/workflows/{wf}", "event": event, "status": status,
            "conclusion": conclusion, "created_at": created}


def obs(**over):
    o = {
        "now": NOW,
        "own_run_id": OWN_RUN,
        "runs": [run(CANARY_RUN, "canary-trigger.yml"),
                 run(REVIEWER_RUN, "reviewer.yml", event="workflow_run", created="2026-10-12T10:07:21Z"),
                 run(OWN_RUN, "digest.yml", status="in_progress", conclusion=None, created="2026-10-12T10:47:00Z")],
        "reviewer_logs": {REVIEWER_RUN: reviewer_log()},
        "oldest_reviewer_created": "2026-09-28T19:00:00Z",
        "bypass": {r: {"day": [], "all": [{"id": 1}], "allowed": True} for r in dl.BYPASS_REPOS},
        "open_prs": [],
        "branch_exists": {},
        "worklog_last": "2026-10-11T08:00:00Z",
        "standards_last": "2026-10-10T08:00:00Z",
    }
    o.update(over)
    return o


def lines_of(body):
    block = body.split("```text\n", 1)[1].split("```", 1)[0]
    return block.rstrip("\n").split("\n")


def line(body, title):
    found = [ln for ln in lines_of(body) if ln.startswith(title + ": ")]
    assert len(found) == 1, (title, found)
    return found[0]


def digest_fields(dline):
    return [kv.split("=", 1)[0] for kv in dline.split(" ")[1:]]


class Shape(unittest.TestCase):
    def assertShape(self, body, dline):
        human = lines_of(body)
        self.assertEqual([h.split(":", 1)[0] for h in human[:9]], TITLES)
        self.assertEqual(human[9], "")
        self.assertEqual(human[10], dline)
        self.assertEqual(digest_fields(dline), list(dl.DIGEST_FIELDS))
        self.assertNotRegex(dline, r"=(\s|$)")
        last = body.rstrip("\n").split("\n")[-1]
        self.assertRegex(last, r"^СВОДКА (ПОЛНАЯ|НЕПОЛНАЯ: .+)$")

    def test_complete_night(self):
        body, dline, incomplete = dl.build(obs(), 7)
        self.assertShape(body, dline)
        self.assertEqual(incomplete, [])
        self.assertTrue(body.endswith("СВОДКА ПОЛНАЯ\n"))
        self.assertEqual(dline, "DIGEST seq=7 date=2026-10-12 runs=2 red=0 unknown=0 reviewer=DONE findings=1 "
                                "canary=PASS retention=not_observed expires_in=not_observed "
                                "bypass_24h=probe:0/allowed,factory-knowledge:0/allowed,online-base:0/allowed "
                                "bypass_total=probe:1/allowed,factory-knowledge:1/allowed,online-base:1/allowed "
                                "prless_branch=0 worklog_age=1 models=PASS standards_age=2 complete=yes")

    def test_no_nightly_run_at_all(self):
        # Ночной прогон не запустился вовсе: сводка обязана выйти, строки — «не наблюдалось».
        o = obs(runs=[run(OWN_RUN, "digest.yml", status="in_progress", conclusion=None)], reviewer_logs={})
        body, dline, incomplete = dl.build(o, 8)
        self.assertShape(body, dline)
        for title in ("РЕВЬЮЕР", "КАНАРЕЙКА", "СРОК ХРАНЕНИЯ", "МОДЕЛИ"):
            self.assertEqual(line(body, title),
                             f"{title}: не наблюдалось: ночного прогона не было: canary-trigger за окно не запускался")
        self.assertEqual(line(body, "НОЧЬ"), "НОЧЬ: прогонов 0, красных 0, UNKNOWN 0 (из 0 прогонов ревьюера)")
        self.assertEqual(incomplete, ["РЕВЬЮЕР", "КАНАРЕЙКА", "СРОК ХРАНЕНИЯ", "МОДЕЛИ"])
        self.assertTrue(body.endswith("СВОДКА НЕПОЛНАЯ: РЕВЬЮЕР, КАНАРЕЙКА, СРОК ХРАНЕНИЯ, МОДЕЛИ\n"))
        self.assertIn(" reviewer=not_observed findings=not_observed canary=not_observed retention=not_observed "
                      "expires_in=not_observed ", dline)
        self.assertTrue(dline.endswith(" complete=no:reviewer,canary,retention,models"))

    def test_runs_unreadable(self):
        body, dline, incomplete = dl.build(obs(runs=dl.Missing("нет права actions:read (HTTP 403)")), 1)
        self.assertShape(body, dline)
        self.assertEqual(line(body, "НОЧЬ"), "НОЧЬ: не наблюдалось: нет права actions:read (HTTP 403)")
        self.assertIn("НОЧЬ", incomplete)

    def test_every_line_missing_still_nine_lines(self):
        m = dl.Missing("нет")
        o = obs(runs=m, oldest_reviewer_created=m, open_prs=m, worklog_last=m, standards_last=m,
                bypass={r: {"day": m, "all": m, "allowed": m} for r in dl.BYPASS_REPOS})
        body, dline, incomplete = dl.build(o, 1)
        self.assertShape(body, dline)
        self.assertEqual(incomplete, TITLES)
        self.assertTrue(all("не наблюдалось" in h for h in lines_of(body)[:9]))

    def test_code_error_is_printed_not_skipped(self):
        o = obs(worklog_last="not-a-date")  # ошибка разбора не должна съесть строку
        body, dline, incomplete = dl.build(o, 1)
        self.assertShape(body, dline)
        self.assertEqual(line(body, "ЖУРНАЛ"), "ЖУРНАЛ: не наблюдалось: ошибка вычисления ValueError")
        self.assertIn("worklog_age=not_observed", dline)


class Nightly(unittest.TestCase):
    def test_several_nightly_runs_not_chosen(self):
        o = obs(runs=[run(1, "canary-trigger.yml"), run(2, "canary-trigger.yml", event="workflow_dispatch",
                                                         created="2026-10-12T10:30:58Z")],
                reviewer_logs={3: reviewer_log(upstream=1), 4: reviewer_log(upstream=2)})
        body, _, incomplete = dl.build(o, 1)
        self.assertEqual(line(body, "РЕВЬЮЕР"),
                         "РЕВЬЮЕР: не наблюдалось: ночных прогонов 2: 1 (schedule), 2 (workflow_dispatch); "
                         "правило выбора не принято — вопрос к «Архитектуре»")
        self.assertIn("КАНАРЕЙКА", incomplete)

    def test_reviewer_of_other_run_not_taken(self):
        o = obs(reviewer_logs={REVIEWER_RUN: reviewer_log(upstream=111, trigger="agent")})
        body, _, _ = dl.build(o, 1)
        self.assertEqual(line(body, "РЕВЬЮЕР"),
                         f"РЕВЬЮЕР: не наблюдалось: ревьюер по ночному прогону {CANARY_RUN} за окно не отчитался")

    def test_reviewer_log_unreadable(self):
        o = obs(reviewer_logs={REVIEWER_RUN: dl.Missing("журнал прогона: HTTP 410")})
        body, dline, _ = dl.build(o, 1)
        self.assertIn("не прочитаны журналы", line(body, "РЕВЬЮЕР"))
        self.assertIn("UNKNOWN — не наблюдалось", line(body, "НОЧЬ"))
        self.assertIn(" runs=2 red=0 unknown=not_observed ", dline)

    def test_ledger_missing(self):
        log = reviewer_log().replace("REVIEW_LEDGER", "SOMETHING")
        body, _, _ = dl.build(obs(reviewer_logs={REVIEWER_RUN: log}), 1)
        self.assertEqual(line(body, "КАНАРЕЙКА"),
                         f"КАНАРЕЙКА: не наблюдалось: в журнале ревьюера {REVIEWER_RUN} нет строки REVIEW_LEDGER")

    def test_red_and_unknown_counted(self):
        o = obs(runs=[run(CANARY_RUN, "canary-trigger.yml", conclusion="failure"),
                      run(REVIEWER_RUN, "reviewer.yml", conclusion="failure", event="workflow_run")],
                reviewer_logs={REVIEWER_RUN: reviewer_log(result="UNKNOWN(canary_trigger_conclusion:failure)",
                                                          findings="n/a", canary="FAIL", models=None)})
        body, dline, incomplete = dl.build(o, 1)
        self.assertEqual(line(body, "НОЧЬ"), "НОЧЬ: прогонов 2, красных 2, UNKNOWN 1 (из 1 прогонов ревьюера)")
        self.assertIn("reviewer=UNKNOWN(canary_trigger_conclusion:failure) findings=n/a canary=FAIL", dline)
        self.assertIn("МОДЕЛИ: не наблюдалось: в журнале ревьюера", line(body, "МОДЕЛИ"))
        self.assertEqual(incomplete, ["МОДЕЛИ"])

    def test_models_fail(self):
        body, dline, _ = dl.build(obs(reviewer_logs={REVIEWER_RUN: reviewer_log(models=("PASS", "FAIL", "PASS"))}), 1)
        self.assertIn("models=в=PASS,г=FAIL,д=PASS", dline)
        self.assertIn("(г) FAIL", line(body, "МОДЕЛИ"))


class Lines(unittest.TestCase):
    def test_retention_observed_expires_in(self):
        log = reviewer_log(retention="observed=84d")
        body, dline, _ = dl.build(obs(reviewer_logs={REVIEWER_RUN: log},
                                      oldest_reviewer_created="2026-07-20T00:00:00Z"), 1)
        # 2026-07-20 + 84 дня = 2026-10-12 → 0 дней.
        self.assertIn("retention=observed=84d expires_in=0 ", dline)
        self.assertEqual(dl.expires_in("observed=84d", "2026-07-15T00:00:00Z", NOW.date()), -5)

    def test_retention_failed(self):
        body, dline, incomplete = dl.build(obs(reviewer_logs={REVIEWER_RUN: reviewer_log(retention="failed")}), 1)
        self.assertIn("красный", line(body, "СРОК ХРАНЕНИЯ"))
        self.assertIn("retention=failed expires_in=not_observed", dline)
        self.assertEqual(incomplete, [])

    def test_bypass_per_repo_distinguishes_forbidden(self):
        b = {dl.PROBE_REPO: {"day": [], "all": [], "allowed": False},
             dl.rl.KNOWLEDGE_REPO: {"day": [{"id": 1}], "all": [{"id": 1}, {"id": 2}], "allowed": True},
             dl.ONLINE_BASE_REPO: {"day": dl.Missing("нет права administration=read (HTTP 403)"),
                                   "all": dl.Missing("x"), "allowed": dl.Missing("x")}}
        body, dline, incomplete = dl.build(obs(bypass=b), 1)
        self.assertIn("bypass_24h=probe:0/forbidden,factory-knowledge:1/allowed,online-base:not_observed ", dline)
        self.assertIn("bypass_total=probe:0/forbidden,factory-knowledge:2/allowed,online-base:not_observed ", dline)
        text = line(body, "ОБХОДЫ")
        self.assertIn("probe: за сутки 0, за 30 дней 0; обход невозможен по настройке — ноль здесь ничего не доказывает", text)
        self.assertIn("online-base: не наблюдалось: нет права administration=read (HTTP 403)", text)
        self.assertEqual(incomplete, ["ОБХОДЫ"])

    def test_bypass_flag_unknown_is_gap(self):
        b = {r: {"day": [], "all": [], "allowed": dl.Missing("нет права")} for r in dl.BYPASS_REPOS}
        _, dline, incomplete = dl.build(obs(bypass=b), 1)
        self.assertIn("bypass_24h=probe:0/unknown,", dline)
        self.assertEqual(incomplete, ["ОБХОДЫ"])

    def test_prless_branch(self):
        prs = [{"number": 40, "head": {"ref": "agent/x", "repo": {"full_name": dl.PROBE_REPO}}},
               {"number": 41, "head": {"ref": "agent/y", "repo": {"full_name": dl.PROBE_REPO}}},
               {"number": 42, "head": {"ref": "z", "repo": None}}]
        body, dline, _ = dl.build(obs(open_prs=prs, branch_exists={"agent/x": True, "agent/y": False}), 1)
        self.assertIn("prless_branch=2 ", dline)
        self.assertIn("probe: 2 из 3 открытых (#41, #42)", line(body, "ЗАЯВКИ БЕЗ ВЕТКИ"))

    def test_ages(self):
        _, dline, _ = dl.build(obs(worklog_last="2026-10-02T23:59:59Z", standards_last=None), 1)
        self.assertIn("worklog_age=10 ", dline)
        self.assertIn("standards_age=not_observed ", dline)

    def test_values_have_no_spaces(self):
        log = reviewer_log(result="UNKNOWN(review_job_failure)")
        _, dline, _ = dl.build(obs(reviewer_logs={REVIEWER_RUN: log}), "n/a")
        self.assertEqual(len(dline.split(" ")), len(dl.DIGEST_FIELDS) + 1)


class Flow(unittest.TestCase):
    """digest.run с поддельным транспортом: что читается, куда публикуется."""

    def setUp(self):
        self.posted, self.calls = [], []
        self.post_status = 201
        self.runs = []
        self.env = {"GH_TOKEN_READ": "r", "GH_TOKEN_KNOWLEDGE": "k", "GH_TOKEN_DIGEST": "d",
                    "GITHUB_RUN_ID": str(OWN_RUN), "GITHUB_RUN_NUMBER": "3"}

    def transport(self, method, url, headers, body):
        token = headers.get("Authorization", "")
        self.calls.append((method, url, token))
        path = url.replace("https://api.github.com", "")
        p = path.split("?")[0]
        ok = lambda v: (200, {}, json.dumps(v).encode())  # noqa: E731
        if method == "POST" and p == f"/repos/{F.KR}/issues/{dl.DIGEST_ISSUE}/comments":
            self.posted.append((token, json.loads(body)["body"]))
            return self.post_status, {}, b"{}"
        if p == f"/repos/{F.REPO}/actions/runs":
            return ok({"workflow_runs": self.runs if "page=1" in path else []})
        if p == f"/repos/{F.REPO}/actions/workflows/reviewer.yml/runs":
            return ok({"total_count": 0, "workflow_runs": []})
        if p == f"/repos/{F.REPO}/pulls":
            return ok([])
        if "/rulesets/rule-suites" in p or p.endswith("/branches/main/protection"):
            return 403, {"X-Accepted-GitHub-Permissions": "administration=read"}, b'{"message":"Resource not accessible by integration"}'
        if p == f"/repos/{F.KR}/commits" and token == "Bearer k":
            return ok([{"commit": {"committer": {"date": "2026-10-11T00:00:00Z"}}}])
        if p == "/repos/Online-Base1/online-base/commits":
            return 404, {}, b"{}"
        return 599, {}, json.dumps({"unrouted": [method, path]}).encode()

    def test_no_nightly_run_published(self):
        body, code = dg.run(self.env, self.transport, now=NOW)
        self.assertEqual(code, 0)
        self.assertEqual(len(self.posted), 1)
        token, posted = self.posted[0]
        self.assertEqual(token, "Bearer d")  # публикует только токен issues:write
        self.assertEqual(posted, body)
        self.assertIn("РЕВЬЮЕР: не наблюдалось: ночного прогона не было", posted)
        self.assertIn("probe: не наблюдалось: нет права administration=read (HTTP 403)", posted)
        self.assertIn("ЖУРНАЛ: не наблюдалось: нет права contents:read на online-base: ресурс не виден токену (HTTP 404)",
                      posted)
        self.assertIn("ПРАВИЛА: 1 дн.", posted)
        self.assertIn("DIGEST seq=3 date=2026-10-12 ", posted)
        # Никаких записей, кроме одного комментария; токен публикации ничего не читает.
        self.assertEqual([c for c in self.calls if c[0] != "GET"], [("POST", self.calls[-1][1], "Bearer d")])
        self.assertEqual([c for c in self.calls if c[2] == "Bearer d" and c[0] == "GET"], [])
        self.assertFalse([c for c in self.calls if c[0] == "GET" and c[2] == "" ])

    def test_knowledge_token_missing_still_published(self):
        del self.env["GH_TOKEN_KNOWLEDGE"]
        body, code = dg.run(self.env, self.transport, now=NOW)
        self.assertEqual(code, 0)
        self.assertIn("ПРАВИЛА: не наблюдалось: токен для contents:read на factory-knowledge не выпущен", body)

    def test_publish_refused_is_red(self):
        self.post_status = 403
        _, code = dg.run(self.env, self.transport, now=NOW)
        self.assertEqual(code, 1)

    def test_no_digest_token_is_red(self):
        del self.env["GH_TOKEN_DIGEST"]
        _, code = dg.run(self.env, self.transport, now=NOW)
        self.assertEqual(code, 1)
        self.assertEqual(self.posted, [])

    def test_runs_window_and_own_run_excluded(self):
        self.runs = [run(OWN_RUN, "digest.yml", status="in_progress", conclusion=None)]
        body, _ = dg.run(self.env, self.transport, now=NOW)
        self.assertIn("НОЧЬ: прогонов 0, красных 0", body)
        q = [c[1] for c in self.calls if "/actions/runs?" in c[1]][0]
        self.assertIn("created=%3E%3D2026-10-11T10%3A47%3A00Z", q)


if __name__ == "__main__":
    unittest.main()
