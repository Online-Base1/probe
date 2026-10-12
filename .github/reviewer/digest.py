"""Ночная сводка: ввод-вывод вокруг digest_lib (digest.yml, D-121).

Читает итоги ночи через API и пишет один комментарий в factory-knowledge#
DIGEST_ISSUE. Каждый источник получается отдельно; неполученный становится
Missing(причина) и даёт строку «не наблюдалось», а не падение сводки. Красный
прогон — только если комментарий не опубликован: тогда сводки нет вовсе.

Токены (окружение, не печатаются):
  GH_TOKEN_READ      — github.token прогона: actions/contents/pull-requests:read на probe;
  GH_TOKEN_KNOWLEDGE — приложение ревьюера, factory-knowledge, contents:read (строка ПРАВИЛА);
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


def _header(headers, name):
    for k, v in (headers or {}).items():
        if k.lower() == name.lower():
            return v
    return None


def why(status, headers, right):
    """Причина отказа словами. Право — из ответа площадки, если она его назвала."""
    accepted = _header(headers, "X-Accepted-GitHub-Permissions")
    if status == 403:
        return f"нет права {accepted or right} (HTTP 403)"
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
        return dl.Missing(why(status, headers, right))
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


def collect(gh_read, gh_knowledge, now, own_run_id):
    """Все источники сводки; каждый — данные либо Missing."""
    start, _ = dl.window(now)
    probe = dl.PROBE_REPO
    created = urllib.parse.quote(">=" + start.strftime("%Y-%m-%dT%H:%M:%SZ"))
    runs = get_pages(gh_read, f"/repos/{probe}/actions/runs?created={created}", "actions:read на probe",
                     key="workflow_runs")
    reviewer_logs = {}
    if not isinstance(runs, dl.Missing):
        for r in runs:
            if dl.workflow_file(r) != REVIEWER_PATH or str(r["id"]) == str(own_run_id):
                continue
            if r.get("status") != "completed":
                reviewer_logs[r["id"]] = dl.Missing(f"прогон ревьюера {r['id']} ещё не завершён")
                continue
            status, text = rv.run_log_text(gh_read, probe, r["id"])
            reviewer_logs[r["id"]] = text if status == 200 else dl.Missing(f"журнал прогона {r['id']}: HTTP {status}")

    tokens = {probe: gh_read, rl.KNOWLEDGE_REPO: gh_knowledge, dl.ONLINE_BASE_REPO: gh_read}
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

    return {
        "now": now,
        "own_run_id": own_run_id,
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
    obs = collect(gh_read, gh("GH_TOKEN_KNOWLEDGE"), now, env.get("GITHUB_RUN_ID", ""))
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
