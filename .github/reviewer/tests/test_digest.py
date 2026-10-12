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


SHA1, SHA2 = "1" * 40, "2" * 40
WORKER = "online-base1-factory-worker[bot]"


def merged_pr(n, sha, base="main"):
    return {"number": n, "merged_at": "2026-10-12T09:00:00Z", "base": {"ref": base}, "merge_commit_sha": sha}


BASE_SHA, TIP_SHA = "b" * 40, "c" * 40


def merges_src(commits=None, pulls=None, merged_by=None, base=BASE_SHA, tip=TIP_SHA, status="ahead", total=None):
    """Источник строки ВЛИВАНИЯ: вершина, начало диапазона, сравнение, заявки, merged_by.

    commits=None — main не сдвинулся (начало == вершине); Missing — репозиторий не виден.
    """
    merged_by = merged_by or {}

    def detail(n):
        v = merged_by.get(n, dl.OWNER_LOGIN)
        return v if isinstance(v, dl.Missing) else {"number": n, "merged_by": {"login": v} if v else None}
    if isinstance(commits, dl.Missing):
        return {"tip": commits, "base": base, "compare": None, "pulls": {}, "pull_detail": None}
    if commits is None:
        return {"tip": tip, "base": tip if base == BASE_SHA else base, "compare": None, "pulls": {}, "pull_detail": None}
    cmp = {"status": status, "commits": list(commits), "total_commits": len(commits) if total is None else total}
    return {"tip": tip, "base": base, "compare": cmp, "pulls": pulls or {}, "pull_detail": detail}


def obs(**over):
    o = {
        "now": NOW,
        "own_run_id": OWN_RUN,
        "runs": [run(CANARY_RUN, "canary-trigger.yml"),
                 run(REVIEWER_RUN, "reviewer.yml", event="workflow_run", created="2026-10-12T10:07:21Z"),
                 run(OWN_RUN, "digest.yml", status="in_progress", conclusion=None, created="2026-10-12T10:47:00Z")],
        "own_created": "2026-10-12T10:47:00Z",
        "previous_digest": None,
        "reviewer_logs": {REVIEWER_RUN: reviewer_log()},
        "oldest_reviewer_created": "2026-09-28T19:00:00Z",
        "bypass": {r: {"day": [], "all": [{"id": 1}], "allowed": True} for r in dl.BYPASS_REPOS},
        "open_prs": [],
        "branch_exists": {},
        "worklog_last": "2026-10-11T08:00:00Z",
        "standards_last": "2026-10-10T08:00:00Z",
        "checks": {r: {} for r in dl.CHECKS_REPOS},
        "merges": {r: merges_src() for r in dl.MERGES_REPOS},
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
        n = len(TITLES)
        self.assertEqual([h.split(":", 1)[0] for h in human[:n]], TITLES)
        self.assertEqual(human[n], "")
        self.assertEqual(human[n + 1], dline)
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
                                "bypass_30d=probe:1/allowed,factory-knowledge:1/allowed,online-base:1/allowed "
                                "prless_branch=0 worklog_age=1 models=PASS standards_age=2 "
                                "checks_changed=probe:0,factory-ci:0,factory-knowledge:0,online-base:0,cost-panel:0 "
                                "complete=yes "
                                "merges=probe:0/0/0,factory-ci:0/0/0,factory-knowledge:0/0/0,online-base:0/0/0,cost-panel:0/0/0")
        self.assertIn("(первая сводка: окно 24 ч)", body)
        self.assertIn("окно 2026-10-11T10:47Z … 2026-10-12T10:47Z", body)

    def test_no_nightly_run_at_all(self):
        # Ночной прогон не запустился вовсе: сводка обязана выйти, строки — «не наблюдалось».
        o = obs(runs=[run(OWN_RUN, "digest.yml", status="in_progress", conclusion=None)], reviewer_logs={})
        body, dline, incomplete = dl.build(o, 8)
        self.assertShape(body, dline)
        for title in ("РЕВЬЮЕР", "КАНАРЕЙКА", "СРОК ХРАНЕНИЯ", "МОДЕЛИ"):
            self.assertEqual(line(body, title),
                             f"{title}: не наблюдалось: прогона по расписанию не было")
        self.assertEqual(line(body, "НОЧЬ"), "НОЧЬ: прогонов 0, красных 0, UNKNOWN 0 (из 0 прогонов ревьюера)")
        self.assertEqual(incomplete, ["РЕВЬЮЕР", "КАНАРЕЙКА", "СРОК ХРАНЕНИЯ", "МОДЕЛИ"])
        self.assertTrue(body.endswith("СВОДКА НЕПОЛНАЯ: РЕВЬЮЕР, КАНАРЕЙКА, СРОК ХРАНЕНИЯ, МОДЕЛИ\n"))
        self.assertIn(" reviewer=not_observed findings=not_observed canary=not_observed retention=not_observed "
                      "expires_in=not_observed ", dline)
        self.assertIn(" complete=no:reviewer,canary,retention,models merges=", dline)

    def test_runs_unreadable(self):
        body, dline, incomplete = dl.build(obs(runs=dl.Missing("нет права actions:read (HTTP 403)")), 1)
        self.assertShape(body, dline)
        self.assertEqual(line(body, "НОЧЬ"), "НОЧЬ: не наблюдалось: нет права actions:read (HTTP 403)")
        self.assertIn("НОЧЬ", incomplete)

    def test_every_line_missing_still_all_lines(self):
        m = dl.Missing("нет")
        o = obs(runs=m, oldest_reviewer_created=m, open_prs=m, worklog_last=m, standards_last=m,
                bypass={r: {"day": m, "all": m, "allowed": m} for r in dl.BYPASS_REPOS})
        body, dline, incomplete = dl.build(o, 1)
        self.assertShape(body, dline)
        o["merges"] = {r: merges_src(commits=m) for r in dl.MERGES_REPOS}
        body, dline, incomplete = dl.build(o, 1)
        self.assertShape(body, dline)
        five = "probe, factory-ci, factory-knowledge, online-base, cost-panel"
        self.assertEqual(incomplete, [
            "НОЧЬ", "РЕВЬЮЕР", "КАНАРЕЙКА", "СРОК ХРАНЕНИЯ", "ОБХОДЫ (probe, factory-knowledge, online-base)",
            f"ВЛИВАНИЯ ({five})", "ЗАЯВКИ БЕЗ ВЕТКИ", "ЖУРНАЛ", "МОДЕЛИ", "ПРАВИЛА", f"ИЗМЕНЕНИЕ ПРОВЕРОК ({five})"])
        self.assertTrue(all("не наблюдалось" in h for h in lines_of(body)[:len(TITLES)]))
        self.assertIn("complete=no:night,reviewer,canary,retention,bypass(probe+factory-knowledge+online-base),", dline)

    def test_code_error_is_printed_not_skipped(self):
        o = obs(worklog_last="not-a-date")  # ошибка разбора не должна съесть строку
        body, dline, incomplete = dl.build(o, 1)
        self.assertShape(body, dline)
        self.assertEqual(line(body, "ЖУРНАЛ"), "ЖУРНАЛ: не наблюдалось: ошибка вычисления ValueError")
        self.assertIn("worklog_age=not_observed", dline)


class Nightly(unittest.TestCase):
    def test_several_schedule_runs_last_taken(self):
        # D-133 c: берётся последний по расписанию, множественность называется.
        o = obs(runs=[run(1, "canary-trigger.yml"), run(2, "canary-trigger.yml", created="2026-10-12T10:30:58Z")],
                reviewer_logs={3: reviewer_log(upstream=1, result="UNKNOWN(x)"), 4: reviewer_log(upstream=2)})
        body, _, incomplete = dl.build(o, 1)
        self.assertEqual(line(body, "РЕВЬЮЕР"), "РЕВЬЮЕР: DONE, находок 1 (ревьюер 4 по ночному прогону 2) "
                                                "(прогонов по расписанию: 2, взят последний 2)")
        self.assertIn("(прогонов по расписанию: 2, взят последний 2)", line(body, "КАНАРЕЙКА"))
        self.assertEqual(incomplete, [])

    def test_manual_run_is_not_the_night(self):
        # Ручной прогон позже ночного — в ночь не входит; в НОЧЬ он считается.
        o = obs(runs=[run(1, "canary-trigger.yml"),
                      run(2, "canary-trigger.yml", event="workflow_dispatch", created="2026-10-12T10:30:58Z")],
                reviewer_logs={3: reviewer_log(upstream=1), 4: reviewer_log(upstream=2, result="UNKNOWN(x)")})
        body, _, _ = dl.build(o, 1)
        self.assertEqual(line(body, "РЕВЬЮЕР"), "РЕВЬЮЕР: DONE, находок 1 (ревьюер 3 по ночному прогону 1)")
        self.assertIn("НОЧЬ: прогонов 2, красных 0, UNKNOWN 1 (из 2 прогонов ревьюера)", body)

    def test_only_manual_runs_not_observed(self):
        o = obs(runs=[run(2, "canary-trigger.yml", event="workflow_dispatch")], reviewer_logs={4: reviewer_log(upstream=2)})
        body, _, incomplete = dl.build(o, 1)
        self.assertEqual(line(body, "РЕВЬЮЕР"), "РЕВЬЮЕР: не наблюдалось: прогона по расписанию не было; "
                                                "ручных прогонов canary-trigger: 1 — в ночь не входят")
        self.assertIn("МОДЕЛИ", incomplete)

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


class Merges(unittest.TestCase):
    """D-137: вливания в main — владельцем, не владельцем, без заявки, не прочиталось."""

    def build(self, src, repo=dl.PROBE_REPO):
        m = {r: merges_src() for r in dl.MERGES_REPOS}
        m[repo] = src
        cmp = src.get("compare") if isinstance(src.get("compare"), dict) else {}
        files = {c["sha"]: ["lib/x.ts"] for c in cmp.get("commits") or []}  # .github не трогают
        return dl.build(obs(merges=m, checks={**{r: {} for r in dl.CHECKS_REPOS}, repo: files}), 1)

    def test_owner_login_pinned(self):
        # Смена владельца — изменение конфигурации: этот тест и строка в сводке.
        self.assertEqual(dl.OWNER_LOGIN, "MartynPin")
        body, _, _ = self.build(merges_src())
        self.assertIn("ВЛИВАНИЯ: всего/не владельцем/без заявки, владелец MartynPin — ", body)

    def test_merged_by_owner(self):
        body, dline, incomplete = self.build(merges_src([{"sha": SHA1}], {SHA1: [merged_pr(42, SHA1)]}))
        self.assertIn("merges=probe:1/0/0,", dline)
        self.assertNotIn("КРАСНЫЙ", line(body, "ВЛИВАНИЯ"))
        self.assertEqual(incomplete, [])

    def test_merged_by_not_owner_is_red(self):
        body, dline, incomplete = self.build(merges_src([{"sha": SHA1}], {SHA1: [merged_pr(42, SHA1)]}, {42: WORKER}))
        self.assertIn("merges=probe:1/1/0,", dline)
        self.assertIn(f"probe: 1/1/0 КРАСНЫЙ: 1111111 влил {WORKER}", line(body, "ВЛИВАНИЯ"))
        self.assertEqual(incomplete, [])  # наблюдено и красное — не пробел

    def test_commit_without_pr_is_red(self):
        body, dline, _ = self.build(merges_src([{"sha": SHA1}, {"sha": SHA2}],
                                               {SHA1: [], SHA2: [{"number": 7, "merged_at": None, "base": {"ref": "main"}}]}))
        self.assertIn("merges=probe:2/0/2,", dline)
        self.assertIn("probe: 2/0/2 КРАСНЫЙ: 1111111 без заявки, 2222222 без заявки", line(body, "ВЛИВАНИЯ"))

    def test_pr_merged_elsewhere_is_no_pr(self):
        # Заявка влита не в main — коммит в main попал не ею.
        _, dline, _ = self.build(merges_src([{"sha": SHA1}], {SHA1: [merged_pr(9, SHA1, base="canary-base")]}))
        self.assertIn("merges=probe:1/0/1,", dline)

    def test_merged_by_unreadable(self):
        body, dline, incomplete = self.build(merges_src(
            [{"sha": SHA1}], {SHA1: [merged_pr(42, SHA1)]},
            {42: dl.Missing("нет права pull_requests=read (HTTP 403)")}))
        self.assertIn("merges=probe:not_observed,", dline)
        self.assertIn("probe: не наблюдалось: заявка #42 коммита 1111111: нет права pull_requests=read (HTTP 403)",
                      line(body, "ВЛИВАНИЯ"))
        self.assertEqual(incomplete, ["ВЛИВАНИЯ (probe)"])
        self.assertIn(" complete=no:merges(probe) ", dline)

    def test_merged_by_empty(self):
        _, dline, incomplete = self.build(merges_src([{"sha": SHA1}], {SHA1: [merged_pr(42, SHA1)]}, {42: ""}))
        self.assertIn("merges=probe:not_observed,", dline)
        self.assertEqual(incomplete, ["ВЛИВАНИЯ (probe)"])

    def test_pulls_unreadable(self):
        body, dline, incomplete = self.build(merges_src(
            [{"sha": SHA1}], {SHA1: dl.Missing("нет права pull_requests=read (HTTP 403: Resource not accessible by integration)")}))
        self.assertIn("merges=probe:not_observed,", dline)
        self.assertIn("probe: не наблюдалось: заявки коммита 1111111: нет права pull_requests=read "
                      "(HTTP 403: Resource not accessible by integration)", line(body, "ВЛИВАНИЯ"))
        self.assertEqual(incomplete, ["ВЛИВАНИЯ (probe)"])

    # --- D-138 b: диапазон от запомненной вершины; D-139 b: ноль без запросов ---

    def test_no_new_commits_says_no_requests(self):
        body, dline, incomplete = self.build(merges_src())
        self.assertIn("probe: 0/0/0 (запросов не было);", line(body, "ВЛИВАНИЯ"))
        self.assertIn("merges=probe:0/0/0,", dline)
        self.assertEqual(incomplete, [])

    def test_first_with_remembered_tip(self):
        body, dline, incomplete = self.build(merges_src(base=None))
        self.assertIn("probe: 0/0/0 (запросов не было: начало диапазона — текущая вершина ccccccc, "
                      "первая сводка с запомненной вершиной)", line(body, "ВЛИВАНИЯ"))
        self.assertIn("merges=probe:0/0/0,", dline)
        self.assertEqual(incomplete, [])

    def test_previous_tip_unreadable(self):
        body, dline, incomplete = self.build(merges_src(base=dl.Missing("журнал сводки 7: HTTP 410")))
        self.assertIn("probe: не наблюдалось: предыдущая вершина не прочитана: журнал сводки 7: HTTP 410",
                      line(body, "ВЛИВАНИЯ"))
        # диапазон не определён — пробел обеих строк, что на нём стоят
        self.assertEqual(incomplete, ["ВЛИВАНИЯ (probe)", "ИЗМЕНЕНИЕ ПРОВЕРОК (probe)"])

    def test_rewritten_main_is_red_and_gap(self):
        body, dline, incomplete = self.build(merges_src([{"sha": SHA1}], {SHA1: [merged_pr(1, SHA1)]}, status="diverged"))
        self.assertIn("probe: не наблюдалось: КРАСНЫЙ: история main не продолжает запомненную вершину bbbbbbb "
                      "(compare bbbbbbb...ccccccc: diverged)", line(body, "ВЛИВАНИЯ"))
        # диапазон не определён — пробел обеих строк, что на нём стоят
        self.assertEqual(incomplete, ["ВЛИВАНИЯ (probe)", "ИЗМЕНЕНИЕ ПРОВЕРОК (probe)"])

    def test_range_truncated_not_observed(self):
        _, dline, incomplete = self.build(merges_src([{"sha": SHA1}], {SHA1: [merged_pr(1, SHA1)]}, total=300))
        self.assertIn("merges=probe:not_observed,", dline)
        # диапазон не определён — пробел обеих строк, что на нём стоят
        self.assertEqual(incomplete, ["ВЛИВАНИЯ (probe)", "ИЗМЕНЕНИЕ ПРОВЕРОК (probe)"])

    def test_heads_remembered_in_body(self):
        m = {r: merges_src() for r in dl.MERGES_REPOS}
        m[dl.ONLINE_BASE_REPO] = merges_src(dl.Missing("репозиторий не виден токену (HTTP 404)"))
        body, _, _ = dl.build(obs(merges=m), 1)
        heads = dl.heads_of(body)
        self.assertEqual(heads, {"probe": TIP_SHA, "factory-ci": TIP_SHA, "factory-knowledge": TIP_SHA,
                                 "cost-panel": TIP_SHA})
        self.assertIsNone(dl.heads_of("REVIEW_LEDGER kind=canary"))

    def test_repo_not_visible(self):
        body, dline, incomplete = self.build(merges_src(dl.Missing("репозиторий не виден токену (HTTP 404)")),
                                             repo=dl.ONLINE_BASE_REPO)
        self.assertIn("online-base: не наблюдалось: репозиторий не виден токену (HTTP 404)", line(body, "ВЛИВАНИЯ"))
        self.assertTrue(dline.endswith(",online-base:not_observed,cost-panel:0/0/0"))
        self.assertEqual(incomplete, ["ВЛИВАНИЯ (online-base)", "ИЗМЕНЕНИЕ ПРОВЕРОК (online-base)"])

    def test_merge_commit_sha_decides(self):
        # Коммит связан с двумя влитыми заявками; решает та, чей merge_commit_sha — он.
        src = merges_src([{"sha": SHA1}], {SHA1: [merged_pr(5, SHA2), merged_pr(6, SHA1)]}, {5: WORKER, 6: dl.OWNER_LOGIN})
        _, dline, _ = self.build(src)
        self.assertIn("merges=probe:1/0/0,", dline)


class CommitFiles(unittest.TestCase):
    """digest.commit_files: файлы коммитов диапазона; усечённый список — Missing."""

    class GH:
        def __init__(self, n):
            self.n = n

        def request(self, method, path, body=None, accept=None):
            return 200, {}, json.dumps({"files": [{"filename": f"f{i}"} for i in range(self.n)]}).encode()

    def merges(self):
        return {"compare": {"status": "ahead", "commits": [{"sha": SHA1}]}}

    def test_files_listed(self):
        self.assertEqual(dg.commit_files(self.GH(2), dl.PROBE_REPO, self.merges()), {SHA1: ["f0", "f1"]})

    def test_truncated_is_missing(self):
        out = dg.commit_files(self.GH(dg.COMMIT_FILES_LIMIT), dl.PROBE_REPO, self.merges())
        self.assertIsInstance(out[SHA1], dl.Missing)
        self.assertIn("список усечён", out[SHA1].reason)

    def test_no_range_no_requests(self):
        self.assertEqual(dg.commit_files(None, dl.PROBE_REPO, {"compare": None}), {})


class Window(unittest.TestCase):
    """D-133 d: окно — от предыдущей сводки до текущей; первая — 24 ч."""

    def test_from_previous_digest(self):
        prev = {"id": 38280526382, "created_at": "2026-10-11T16:53:28Z"}
        o = obs(previous_digest=prev,
                runs=[run(9, "ci.yml", conclusion="failure", created="2026-10-11T16:00:00Z"),  # до окна
                      run(CANARY_RUN, "canary-trigger.yml"),
                      run(REVIEWER_RUN, "reviewer.yml", event="workflow_run", created="2026-10-12T10:07:21Z")])
        body, dline, _ = dl.build(o, 2)
        self.assertIn("окно 2026-10-11T16:53Z … 2026-10-12T10:47Z (от предыдущей сводки 38280526382)", body)
        self.assertIn(" runs=2 red=0 ", dline)

    def test_long_gap_covers_all_days(self):
        # Сводка не выходила трое суток — окно тянется от последней вышедшей.
        prev = {"id": 1, "created_at": "2026-10-09T12:00:00Z"}
        o = obs(previous_digest=prev, runs=[run(9, "ci.yml", conclusion="failure", created="2026-10-10T01:00:00Z")])
        _, dline, _ = dl.build(o, 2)
        self.assertIn(" runs=1 red=1 ", dline)

    def test_end_is_own_run_created(self):
        # Прогон, созданный после своего (в т. ч. сам), — уже следующего окна.
        o = obs(now=NOW + datetime.timedelta(minutes=5),
                runs=[run(9, "ci.yml", created="2026-10-12T10:49:00Z"), run(CANARY_RUN, "canary-trigger.yml")],
                reviewer_logs={})
        _, dline, _ = dl.build(o, 2)
        self.assertIn(" runs=1 ", dline)

    def test_previous_unreadable(self):
        body, _, _ = dl.build(obs(previous_digest=dl.Missing("нет права actions:read (HTTP 403)")), 2)
        self.assertIn("(предыдущая сводка не прочитана (нет права actions:read (HTTP 403)): окно 24 ч)", body)


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
        self.assertIn("bypass_30d=probe:0/forbidden,factory-knowledge:2/allowed,online-base:not_observed ", dline)
        text = line(body, "ОБХОДЫ")
        self.assertIn("probe: за сутки 0, за 30 дней 0; обход невозможен по настройке — ноль здесь ничего не доказывает", text)
        self.assertIn("online-base: не наблюдалось: нет права administration=read (HTTP 403)", text)
        self.assertEqual(incomplete, ["ОБХОДЫ (online-base)"])
        self.assertTrue(body.endswith("СВОДКА НЕПОЛНАЯ: ОБХОДЫ (online-base)\n"))
        self.assertIn(" complete=no:bypass(online-base)", dline)

    def test_bypass_flag_unknown_is_gap(self):
        # D-133 b: число есть, признак не прочитан → N/unknown, репозиторий — в перечне.
        b = {r: {"day": [], "all": [], "allowed": True} for r in dl.BYPASS_REPOS}
        b[dl.PROBE_REPO] = {"day": [{"id": 1}], "all": [{"id": 1}], "allowed": dl.Missing("нет права")}
        _, dline, incomplete = dl.build(obs(bypass=b), 1)
        self.assertIn("bypass_24h=probe:1/unknown,factory-knowledge:0/allowed,", dline)
        self.assertEqual(incomplete, ["ОБХОДЫ (probe)"])

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

    # ИЗМЕНЕНИЕ ПРОВЕРОК — тот же диапазон от запомненной вершины, что у ВЛИВАНИЙ (D-138 b).

    def checks_build(self, merges_probe, files_probe, extra=None):
        m = {r: merges_src() for r in dl.MERGES_REPOS}
        m[dl.PROBE_REPO] = merges_probe
        m.update(extra or {})
        return dl.build(obs(merges=m, checks={**{r: {} for r in dl.CHECKS_REPOS}, dl.PROBE_REPO: files_probe}), 1)

    def test_checks_changed_in_range(self):
        a, b, c = "f1be53b" + "0" * 33, "d4ee0ef" + "0" * 33, "a" * 40
        src = merges_src([{"sha": a}, {"sha": b}, {"sha": c}], {x: [merged_pr(1, x)] for x in (a, b, c)})
        files = {a: [".github/workflows/ci.yml"], b: [".github/reviewer/x.py", "lib/y.ts"], c: ["lib/z.ts", "github.md", ".githubish/a"]}
        body, dline, incomplete = self.checks_build(src, files, {
            dl.ONLINE_BASE_REPO: merges_src(dl.Missing("репозиторий не виден токену (HTTP 404)"))})
        self.assertIn("checks_changed=probe:2,factory-ci:0,factory-knowledge:0,online-base:not_observed,cost-panel:0 ", dline)
        self.assertIn("ИЗМЕНЕНИЕ ПРОВЕРОК: коммитов в .github/ на main — probe: 2 (f1be53b, d4ee0ef); "
                      "factory-ci: 0 (запросов не было);", body)
        self.assertEqual(incomplete, ["ВЛИВАНИЯ (online-base)", "ИЗМЕНЕНИЕ ПРОВЕРОК (online-base)"])

    def test_checks_range_commits_without_github_is_observed_zero(self):
        src = merges_src([{"sha": SHA1}], {SHA1: [merged_pr(1, SHA1)]})
        body, dline, _ = self.checks_build(src, {SHA1: ["lib/a.ts"]})
        self.assertIn("ИЗМЕНЕНИЕ ПРОВЕРОК: коммитов в .github/ на main — probe: 0; factory-ci", body)

    def test_checks_first_with_remembered_tip(self):
        body, _, incomplete = self.checks_build(merges_src(base=None), {})
        self.assertIn("ИЗМЕНЕНИЕ ПРОВЕРОК: коммитов в .github/ на main — probe: 0 (запросов не было: начало диапазона — "
                      "текущая вершина ccccccc, первая сводка с запомненной вершиной)", body)
        self.assertEqual(incomplete, [])

    def test_checks_commit_files_unreadable(self):
        src = merges_src([{"sha": SHA1}], {SHA1: [merged_pr(1, SHA1)]})
        body, dline, incomplete = self.checks_build(src, {SHA1: dl.Missing("HTTP 502")})
        self.assertIn("probe: не наблюдалось: файлы коммита 1111111: HTTP 502", line(body, "ИЗМЕНЕНИЕ ПРОВЕРОК"))
        self.assertIn("checks_changed=probe:not_observed,", dline)
        self.assertEqual(incomplete, ["ИЗМЕНЕНИЕ ПРОВЕРОК (probe)"])

    def test_checks_rewritten_main(self):
        src = merges_src([{"sha": SHA1}], {SHA1: [merged_pr(1, SHA1)]}, status="diverged")
        body, _, incomplete = self.checks_build(src, {SHA1: [".github/x"]})
        self.assertIn("probe: не наблюдалось: КРАСНЫЙ: история main не продолжает", line(body, "ИЗМЕНЕНИЕ ПРОВЕРОК"))
        self.assertIn("ИЗМЕНЕНИЕ ПРОВЕРОК (probe)", incomplete)

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
        self.digests = []
        self.files_queries = []
        self.commit_files = {"f" * 40: [".github/workflows/digest.yml"]}
        self.main_commits = {F.REPO: [{"sha": "f" * 40}]}
        self.tips = {F.REPO: "f" * 40}
        self.compares = []
        self.digest_logs = {}
        self.commit_pulls = {"f" * 40: [merged_pr(42, "f" * 40)]}
        self.merged_by = "MartynPin"
        self.github_commits = {F.REPO: [{"sha": "f1be53b" + "0" * 33, "commit": {"committer": {"date": "2026-10-12T09:00:00Z"}}}]}
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
        if p == f"/repos/{F.REPO}/actions/runs/{OWN_RUN}":
            return ok({"id": OWN_RUN, "created_at": "2026-10-12T10:47:00Z"})
        if p == f"/repos/{F.REPO}/actions/workflows/digest.yml/runs":
            return ok({"workflow_runs": self.digests})
        if p == f"/repos/{F.REPO}/actions/runs":
            return ok({"workflow_runs": self.runs if "page=1" in path else []})
        m_ref = re.fullmatch(r"/repos/([^/]+/[^/]+)/git/ref/heads/main", p)
        if m_ref:
            repo = m_ref.group(1)
            if repo in ("Online-Base1/online-base", "Online-Base1/cost-panel") or (repo == F.KR and token != "Bearer k"):
                return 404, {}, b"{}"
            return ok({"object": {"sha": self.tips.get(repo, TIP_SHA)}})
        m_cmp = re.fullmatch(r"/repos/([^/]+/[^/]+)/compare/([0-9a-f]{40})\.\.\.([0-9a-f]{40})", p)
        if m_cmp:
            self.compares.append(m_cmp.groups())
            commits = self.main_commits.get(m_cmp.group(1), [])
            return ok({"status": "ahead", "total_commits": len(commits), "commits": commits})
        m_log = re.fullmatch(rf"/repos/{F.REPO}/actions/runs/(\d+)/logs", p)
        if m_log and int(m_log.group(1)) not in self.digest_logs:
            return 410, {}, b"{}"  # журнал истёк
        if m_log:
            return 302, {"Location": f"https://blob.example/logs/{m_log.group(1)}"}, b""
        if url.startswith("https://blob.example/logs/"):
            return 200, {}, F.log_zip(self.digest_logs[int(url.rsplit("/", 1)[1])])
        m_pulls = re.fullmatch(r"/repos/([^/]+/[^/]+)/commits/([0-9a-f]{40})/pulls", p)
        if m_pulls:
            return ok(self.commit_pulls.get(m_pulls.group(2), []))
        m_pull = re.fullmatch(rf"/repos/{F.REPO}/pulls/(\d+)", p)
        if m_pull:
            return ok({"number": int(m_pull.group(1)), "merged_by": {"login": self.merged_by}})
        m_commit = re.fullmatch(r"/repos/([^/]+/[^/]+)/commits/([0-9a-f]{40})", p)
        if m_commit:
            self.files_queries.append(m_commit.groups())
            return ok({"sha": m_commit.group(2), "files": [{"filename": f} for f in self.commit_files.get(m_commit.group(2), [])]})
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
        self.assertIn("РЕВЬЮЕР: не наблюдалось: прогона по расписанию не было", posted)
        self.assertIn("probe: не наблюдалось: нет права administration=read (HTTP 403: Resource not accessible by integration)", posted)
        self.assertIn("ЖУРНАЛ: не наблюдалось: нет права contents:read на online-base: ресурс не виден токену (HTTP 404)",
                      posted)
        self.assertIn("ПРАВИЛА: 1 дн.", posted)
        self.assertIn("DIGEST seq=3 date=2026-10-12 ", posted)
        # Никаких записей, кроме одного комментария; токен публикации ничего не читает.
        self.assertEqual([c for c in self.calls if c[0] != "GET"], [("POST", self.calls[-1][1], "Bearer d")])
        self.assertEqual([c for c in self.calls if c[2] == "Bearer d" and c[0] == "GET"], [])
        self.assertFalse([c for c in self.calls if c[0] == "GET" and c[2] == ""])
        self.assertNotIn("HTTP 599", posted)  # каждый запрос сводки знаком подделке
        self.assertIn("ИЗМЕНЕНИЕ ПРОВЕРОК: коммитов в .github/ на main — probe: 0 (запросов не было: начало диапазона — "
                      "текущая вершина fffffff, первая сводка с запомненной вершиной); factory-ci: 0 (запросов не было: "
                      "начало диапазона — текущая вершина ccccccc, первая сводка с запомненной вершиной); factory-knowledge: 0 "
                      "(запросов не было: начало диапазона — текущая вершина ccccccc, первая сводка с запомненной вершиной); "
                      "online-base: не наблюдалось: репозиторий не виден токену (HTTP 404)", posted)
        self.assertEqual(self.files_queries, [])
        self.assertIn("(первая сводка: окно 24 ч)", posted)
        first = "(запросов не было: начало диапазона — текущая вершина {}, первая сводка с запомненной вершиной)"
        self.assertIn(f"владелец MartynPin — probe: 0/0/0 {first.format('fffffff')}; "
                      f"factory-ci: 0/0/0 {first.format('ccccccc')}; factory-knowledge: 0/0/0 {first.format('ccccccc')}; "
                      "online-base: не наблюдалось: репозиторий не виден токену (HTTP 404); "
                      "cost-panel: не наблюдалось: репозиторий не виден токену (HTTP 404)", posted)
        self.assertEqual(self.compares, [])  # без запомненной вершины диапазона нет
        self.assertEqual(dl.heads_of(posted)["probe"], "f" * 40)

    def remember(self, heads):
        prev = 38291821501
        self.digests = [{"id": prev, "created_at": "2026-10-12T08:00:00Z"}]
        self.digest_logs[prev] = "x <!-- DIGEST_HEADS " + " ".join(f"{k}={v}" for k, v in heads.items()) + " -->\n"

    def test_range_from_remembered_tip(self):
        self.remember({"probe": "e" * 40, "factory-ci": TIP_SHA})
        body, code = dg.run(self.env, self.transport, now=NOW)
        self.assertEqual(self.compares, [(F.REPO, "e" * 40, "f" * 40)])  # factory-ci не сдвинулся — без запроса
        self.assertIn("probe: 1/0/0; factory-ci: 0/0/0 (запросов не было); factory-knowledge: 0/0/0 (запросов не было: "
                      "начало диапазона — текущая вершина ccccccc, первая сводка с запомненной вершиной)", body)
        self.assertEqual(self.files_queries, [(F.REPO, "f" * 40)])
        self.assertIn("ИЗМЕНЕНИЕ ПРОВЕРОК: коммитов в .github/ на main — probe: 1 (fffffff); factory-ci: 0 (запросов не было)", body)

    def test_merge_by_not_owner_flow(self):
        self.merged_by = WORKER
        self.remember({"probe": "e" * 40})
        body, code = dg.run(self.env, self.transport, now=NOW)
        self.assertEqual(code, 0)  # сводка отчитывается о наблюдении и выходит зелёной
        self.assertIn(f"probe: 1/1/0 КРАСНЫЙ: fffffff влил {WORKER}", body)

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
        self.assertFalse([c for c in self.calls if "since=" in c[1] or "path=.github" in c[1]])  # по дате — больше нет

    def test_window_from_previous_digest(self):
        self.digests = [{"id": OWN_RUN, "created_at": "2026-10-12T10:47:00Z"},
                        {"id": 38280526382, "created_at": "2026-10-11T16:53:28Z"}]
        body, _ = dg.run(self.env, self.transport, now=NOW)
        self.assertIn("окно 2026-10-11T16:53Z … 2026-10-12T10:47Z (от предыдущей сводки 38280526382)", body)
        self.assertIn("probe: не наблюдалось: предыдущая вершина не прочитана: журнал сводки 38280526382: HTTP 410", body)
        q = [c[1] for c in self.calls if "/actions/runs?" in c[1]][0]
        self.assertIn("created=%3E%3D2026-10-11T16%3A53%3A28Z", q)


if __name__ == "__main__":
    unittest.main()
