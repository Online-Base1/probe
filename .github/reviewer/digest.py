"""Ночная сводка: ввод-вывод вокруг digest_lib (digest.yml, D-121).

Читает итоги ночи через API и пишет один комментарий в factory-knowledge#
DIGEST_ISSUE. Каждый источник получается отдельно; неполученный становится
Missing(причина) и даёт строку «не наблюдалось», а не падение сводки. Красный
прогон — только если комментарий не опубликован: тогда сводки нет вовсе.

Токены (окружение, не печатаются):
  GH_TOKEN_READ      — github.token прогона: actions/contents/pull-requests:read на probe;
  GH_TOKEN_KNOWLEDGE — приложение ревьюера, factory-knowledge, contents:read + pull-requests:read (ПРАВИЛА, ВЛИВАНИЯ);
  GH_TOKEN_DIGEST    — приложение ревьюера, factory-knowledge, issues:write (только публикация).
Права ни одного из них не расширяются: чего не хватает, то печатается как
«не наблюдалось: нет права <какое>» — право называет сама площадка
(заголовок X-Accepted-GitHub-Permissions), а не мы.
"""

import datetime
import json
import os
import sys
import urllib.parse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import digest_lib as dl  # noqa: E402
import reviewer as rv  # noqa: E402
import reviewer_lib as rl  # noqa: E402

REVIEWER_PATH = ".github/workflows/" + rl.REVIEWER_WORKFLOW_FILE
DIGEST_WORKFLOW_FILE = "digest.yml"


def _header(headers, name):
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def why(status, headers, right, message=""):
    """Причина отказа словами. Право и текст — из ответа площадки, как есть."""
    accepted = _header(headers, "X-Accepted-GitHub-Permissions")
    if status == 403:
        return f"нет права {accepted or right} (HTTP 403" + (f": {message})" if message else ")")
    if status == 404:
        return f"нет права {right}: ресурс не виден токену (HTTP 404)"
    return f"HTTP {status} ({right})"


def get(gh, path, right):
    """JSON по пути или Missing с причиной."""
    if gh is None:
        return dl.Missing(f"токен для {right} не выпущен")
    try:
        status, headers, data = gh.request("GET", path)
    except Exception as exc:  # сеть: причина без подробностей запроса
        return dl.Missing(f"ошибка запроса {type(exc).__name__} ({right})")
    if status != 200:
        try:
            message = str(json.loads(data).get("message") or "")[:200]
        except (ValueError, AttributeError):
            message = ""
        return dl.Missing(why(status, headers, right, message))
    return json.loads(data)


def get_pages(gh, path, right, key=None, limit=10):
    out, sep = [], "&" if "?" in path else "?"
    for page in range(1, limit + 1):
        chunk = get(gh, f"{path}{sep}per_page=100&page={page}", right)
        if isinstance(chunk, dl.Missing):
            return chunk
        items = chunk[key] if key else chunk
        out.extend(items)
        if len(items) < 100:
            return out
    return dl.Missing(f"слишком много страниц ({right})")


def own_created(gh, repo, run_id):
    run = get(gh, f"/repos/{repo}/actions/runs/{run_id}", "actions:read на probe") if run_id else \
        dl.Missing("GITHUB_RUN_ID не задан")
    return run if isinstance(run, dl.Missing) else run["created_at"]


def previous_digest(gh, repo, run_id, created):
    """Последняя успешная (= опубликованная) сводка до своего прогона: {id, created_at} или None."""
    runs = get(gh, f"/repos/{repo}/actions/workflows/{DIGEST_WORKFLOW_FILE}/runs?status=success&per_page=20",
               "actions:read на probe")
    if isinstance(runs, dl.Missing):
        return runs
    for r in runs.get("workflow_runs") or []:
        if str(r["id"]) != str(run_id) and (not isinstance(created, str) or r["created_at"] < created):
            return {"id": r["id"], "created_at": r["created_at"]}
    return None


# Файлов в ответе на коммит не больше 300; больше — список усечён.
COMMIT_FILES_LIMIT = 300


def commit_files(gh, repo, merges):
    """Файлы каждого коммита диапазона ВЛИВАНИЙ (D-138 b): {sha: [пути] | Missing}."""
    cmp = merges.get("compare")
    if not isinstance(cmp, dict) or cmp.get("status") != "ahead":
        return {}
    out = {}
    for c in cmp.get("commits") or []:
        data = get(gh, f"/repos/{repo}/commits/{c['sha']}", f"contents:read на {dl.short(repo)}")
        if isinstance(data, dl.Missing):
            out[c["sha"]] = data
        elif len(data.get("files") or []) >= COMMIT_FILES_LIMIT:
            out[c["sha"]] = dl.Missing(f"файлов не меньше {COMMIT_FILES_LIMIT}, список усечён")
        else:
            out[c["sha"]] = [f["filename"] for f in data.get("files") or []]
    return out


def previous_heads(gh, repo, previous):
    """Вершины main, запомненные прошлой сводкой (строка DIGEST_HEADS в её журнале).

    None — прошлой сводки нет или она вершин не запоминала (первая после
    введения, D-138 b); Missing — журнал не прочитан.
    """
    if previous is None or isinstance(previous, dl.Missing):
        return previous
    status, text = rv.run_log_text(gh, repo, previous["id"])
    if status != 200:
        return dl.Missing(f"журнал сводки {previous['id']}: HTTP {status}")
    return dl.heads_of(text)


def merges_of(gh, repo, heads):
    """Вливания в main с прошлой сводки (D-137 §b, D-138 b): вершина, начало
    диапазона, сравнение, заявки коммитов и merged_by."""
    right = f"contents:read на {dl.short(repo)}"
    ref = get(gh, f"/repos/{repo}/git/ref/heads/main", right)
    if isinstance(ref, dl.Missing):
        tip = dl.Missing("репозиторий не виден токену (HTTP 404)") if "HTTP 404" in ref.reason else ref
    else:
        tip = ref["object"]["sha"]
    base = heads if isinstance(heads, dl.Missing) or heads is None else heads.get(dl.short(repo))
    out = {"tip": tip, "base": base, "compare": None, "pulls": {}, "pull_detail": None}
    if not isinstance(tip, str) or not isinstance(base, str) or base == tip:
        return out
    cmp = get(gh, f"/repos/{repo}/compare/{base}...{tip}", right)
    out["compare"] = cmp
    if isinstance(cmp, dl.Missing) or cmp.get("status") != "ahead":
        return out
    right_pr = f"pull-requests:read на {dl.short(repo)}"
    out["pulls"] = {c["sha"]: get(gh, f"/repos/{repo}/commits/{c['sha']}/pulls", right_pr) for c in cmp.get("commits") or []}
    out["pull_detail"] = lambda number: get(gh, f"/repos/{repo}/pulls/{number}", right_pr)
    return out


def last_commit_date(gh, repo, path, right):
    q = urllib.parse.quote
    commits = get(gh, f"/repos/{repo}/commits?path={q(path)}&sha=main&per_page=1", right)
    if isinstance(commits, dl.Missing):
        return commits
    return commits[0]["commit"]["committer"]["date"] if commits else None


def oldest_completed_run(gh, repo, workflow_file):
    base = f"/repos/{repo}/actions/workflows/{workflow_file}/runs?status=completed&per_page=1"
    first = get(gh, base, "actions:read на probe")
    if isinstance(first, dl.Missing):
        return first
    total = first.get("total_count", 0)
    if not total:
        return None
    last = get(gh, f"{base}&page={total}", "actions:read на probe")
    if isinstance(last, dl.Missing):
        return last
    runs = last.get("workflow_runs") or []
    return runs[0]["created_at"] if runs else None


def bypass_of(gh, repo):
    """Обходы по rule suites и признак «обход разрешён» по защите main (D-129 §c)."""
    base = f"/repos/{repo}/rulesets/rule-suites?rule_suite_result=bypass"
    right = f"administration:read на {dl.short(repo)}"
    day = get_pages(gh, base + "&time_period=day", right)
    total = get_pages(gh, base + "&time_period=month", right)
    prot = get(gh, f"/repos/{repo}/branches/main/protection", right)
    if isinstance(prot, dl.Missing):
        allowed = prot
    else:
        allowed = not ((prot.get("enforce_admins") or {}).get("enabled", False))
    return {"day": day, "all": total, "allowed": allowed}


def job_names(gh, repo, run_id):
    """Имена заданий прогона ревьюера: есть ли в нём job контрольной (refusal-probes)."""
    jobs = get_pages(gh, f"/repos/{repo}/actions/runs/{run_id}/jobs", "actions:read на probe", key="jobs")
    return jobs if isinstance(jobs, dl.Missing) else [j.get("name") for j in jobs]


def env_check(path):
    """Результат шага Environment check этого прогона (env_check.py runtime) или Missing."""
    if not path:
        return dl.Missing("ENV_CHECK_FILE не задан: шаг сверки среды не подключён")
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except FileNotFoundError:
        return dl.Missing("сверка среды не создала результата: шаг Environment check не выполнился")
    except ValueError:
        return dl.Missing("результат сверки среды не JSON")


def collect(gh_read, gh_knowledge, now, own_run_id, env_file=""):
    """Все источники сводки; каждый — данные либо Missing."""
    probe = dl.PROBE_REPO
    created = own_created(gh_read, probe, own_run_id)
    previous = previous_digest(gh_read, probe, own_run_id, created)
    start, end, _ = dl.digest_window(now, created, previous)
    heads = previous_heads(gh_read, probe, previous)
    since = urllib.parse.quote(">=" + start.strftime("%Y-%m-%dT%H:%M:%SZ"))
    runs = get_pages(gh_read, f"/repos/{probe}/actions/runs?created={since}", "actions:read на probe",
                     key="workflow_runs")
    reviewer_logs = {}
    if not isinstance(runs, dl.Missing):
        for r in dl.in_window(runs, start, end):
            if dl.workflow_file(r) != REVIEWER_PATH or str(r["id"]) == str(own_run_id):
                continue
            if r.get("status") != "completed":
                reviewer_logs[r["id"]] = dl.Missing(f"прогон ревьюера {r['id']} ещё не завершён")
                continue
            status, text = rv.run_log_text(gh_read, probe, r["id"])
            reviewer_logs[r["id"]] = text if status == 200 else dl.Missing(f"журнал прогона {r['id']}: HTTP {status}")

    # Токен на репозиторий: probe и публичные — github.token; factory-knowledge —
    # contents:read приложения ревьюера; online-base и cost-panel токенам сводки
    # не видны — «не наблюдалось», права не добавляются.
    tokens = {probe: gh_read, dl.FACTORY_CI_REPO: gh_read, rl.KNOWLEDGE_REPO: gh_knowledge,
              dl.ONLINE_BASE_REPO: gh_read, dl.COST_PANEL_REPO: gh_read}
    open_prs = get_pages(gh_read, f"/repos/{probe}/pulls?state=open", "pull-requests:read на probe")
    branch_exists = {}
    if not isinstance(open_prs, dl.Missing):
        for pr in open_prs:
            ref = (pr.get("head") or {}).get("ref")
            if not ref or ref in branch_exists:
                continue
            status, headers, _ = gh_read.request("GET", f"/repos/{probe}/branches/{urllib.parse.quote(ref, safe='')}")
            branch_exists[ref] = True if status == 200 else False if status == 404 else \
                dl.Missing(why(status, headers, "contents:read на probe"))

    merges = {repo: merges_of(tokens[repo], repo, heads) for repo in dl.MERGES_REPOS}
    return {
        "now": now,
        "own_run_id": own_run_id,
        "own_created": created,
        "previous_digest": previous,
        "runs": runs,
        "reviewer_logs": reviewer_logs,
        "oldest_reviewer_created": oldest_completed_run(gh_read, probe, rl.REVIEWER_WORKFLOW_FILE),
        "bypass": {repo: bypass_of(tokens[repo], repo) for repo in dl.BYPASS_REPOS},
        "open_prs": open_prs,
        "branch_exists": branch_exists,
        "worklog_last": last_commit_date(gh_read, dl.ONLINE_BASE_REPO, dl.WORKLOG_PATH,
                                         "contents:read на online-base"),
        "standards_last": last_commit_date(gh_knowledge, rl.KNOWLEDGE_REPO, dl.STANDARDS_PATH,
                                           "contents:read на factory-knowledge"),
        "merges": merges,
        "reviewer_jobs": {rid: job_names(gh_read, probe, rid) for rid in reviewer_logs},
        "env_check": env_check(env_file),
        "checks": {repo: commit_files(tokens[repo], repo, merges[repo]) for repo in dl.CHECKS_REPOS},
    }


def publish(gh_digest, body):
    status, _, _ = gh_digest.request("POST", f"/repos/{rl.KNOWLEDGE_REPO}/issues/{dl.DIGEST_ISSUE}/comments",
                                     {"body": body})
    return status


def run(env, transport=rv.http_transport, now=None):
    """(тело, код). Код 1 — только если комментарий не опубликован."""
    def gh(name):
        token = env.get(name, "")
        return rv.GitHub(token, transport) if token else None

    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    gh_read = gh("GH_TOKEN_READ") or rv.GitHub("", transport)
    obs = collect(gh_read, gh("GH_TOKEN_KNOWLEDGE"), now, env.get("GITHUB_RUN_ID", ""), env.get("ENV_CHECK_FILE", ""))
    body, dline, incomplete = dl.build(obs, env.get("GITHUB_RUN_NUMBER", "") or "n/a")
    print(body)
    gh_digest = gh("GH_TOKEN_DIGEST")
    if gh_digest is None:
        print("::error::digest not published: GH_TOKEN_DIGEST is empty")
        return body, 1
    status = publish(gh_digest, body)
    if status != 201:
        print(f"::error::digest not published: POST {rl.KNOWLEDGE_REPO}#{dl.DIGEST_ISSUE} comment -> HTTP {status}")
        return body, 1
    print(f"digest published: {rl.KNOWLEDGE_REPO}#{dl.DIGEST_ISSUE} -> HTTP {status}; incomplete: {incomplete or 'none'}")
    if " control=blind:" in dline:
        # Сводка опубликована, но её механика извлечения отказов слепа (D-143 §f).
        print("::error::positive control: no refusal probe found in any reviewer run in the window — extraction is blind")
        return body, 1
    return body, 0


def main():
    body, code = run(os.environ)
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(body)
    return code


if __name__ == "__main__":
    sys.exit(main())
