"""Ревьюер другого семейства: ввод-вывод вокруг reviewer_lib (reviewer.yml).

  reviewer.py resolve  — job resolve: прогон, задание, заявка;
  reviewer.py review   — job review: пробы, сверка OpenAI, промпт, запрос, комментарий;
  reviewer.py report   — job report: итог REVIEW_RESULT в summary, красный при UNKNOWN.

Токены приходят через окружение и не печатаются. Сеть — только через
GitHub/transport и фабрику клиента OpenAI: в тестах они подменяются.
"""

import datetime
import io
import json
import os
import sys
import zipfile
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openai_checks as oc  # noqa: E402
import reviewer_lib as rl  # noqa: E402

API = "https://api.github.com"
EXPECTED_MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expected-models.json")
REVIEW_MAX_OUTPUT_TOKENS = 16000


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    # Редирект не выполняется автоматически: urllib перенёс бы заголовок
    # Authorization на чужой хост (хранилище артефактов).
    def redirect_request(self, *args, **kwargs):
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def http_transport(method, url, headers, body):
    req = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with _opener.open(req, timeout=60) as resp:
            return resp.status, dict(resp.headers), resp.read()
    except urllib.error.HTTPError as exc:
        return exc.code, dict(exc.headers or {}), exc.read() if exc.fp else b""


class GitHub:
    def __init__(self, token, transport=http_transport):
        self.token = token
        self.transport = transport

    def request(self, method, path, body=None, accept="application/vnd.github+json"):
        url = path if path.startswith("https://") else API + path
        headers = {"Accept": accept, "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "factory-reviewer"}
        if self.token:
            headers["Authorization"] = "Bearer " + self.token
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        return self.transport(method, url, headers, data)

    def json(self, path, what):
        status, _, data = self.request("GET", path)
        if status != 200:
            raise rl.Unknown(f"{what}:{status}")
        return json.loads(data)

    def raw(self, path, what, accept="application/vnd.github.raw+json"):
        status, _, data = self.request("GET", path, accept=accept)
        if status == 404:
            raise rl.Unknown(f"{what}_missing")
        if status != 200:
            raise rl.Unknown(f"{what}:{status}")
        return data

    def paginate(self, path, what, key=None, limit=10):
        out = []
        sep = "&" if "?" in path else "?"
        for page in range(1, limit + 1):
            chunk = self.json(f"{path}{sep}per_page=100&page={page}", what)
            items = chunk[key] if key else chunk
            out.extend(items)
            if len(items) < 100:
                return out
        raise rl.Unknown(f"{what}:too_many")

    def download(self, path, what):
        """Скачивание по редиректу: второй запрос — без Authorization."""
        status, headers, data = self.request("GET", path)
        if status in (301, 302, 303, 307, 308):
            location = headers.get("Location") or headers.get("location")
            if not location:
                raise rl.Unknown(f"{what}:redirect_without_location")
            status, _, data = self.transport("GET", location, {"User-Agent": "factory-reviewer"}, None)
        if status != 200:
            raise rl.Unknown(f"{what}:{status}")
        return data


def fetch_task(gh, repo, run_id):
    """Артефакт задания прогона run_id: ровно один, хеш байтов == суффиксу имени."""
    arts = gh.paginate(f"/repos/{repo}/actions/runs/{run_id}/artifacts", "task_artifacts", key="artifacts")
    art = rl.select_task_artifact(arts)
    data = rl.task_bytes_from_zip(gh.download(f"/repos/{repo}/actions/artifacts/{art['id']}/zip", "task_artifact_download"))
    rl.verify_task(art["name"], data)
    return art, data


def resolve(event, gh, repo):
    wr = event["workflow_run"]
    # run_id — только из события (D-101 §c), не из содержимого артефакта.
    out = {"run_id": str(wr["id"]), "trigger": "", "pr": "", "head_sha": "", "reason": "", "task_artifact": ""}
    try:
        trigger = rl.trigger_of(wr)
        out["trigger"] = trigger
        rl.check_run_conclusion(trigger, wr.get("conclusion"))
        art, _ = fetch_task(gh, repo, wr["id"])
        out["task_artifact"] = art["name"]
        if trigger == "agent":
            prs = gh.paginate(f"/repos/{repo}/pulls?state=open", "pulls")

            def commit_date(sha):
                return gh.json(f"/repos/{repo}/commits/{sha}", "commit")["commit"]["committer"]["date"]

            found = rl.select_agent_pr(prs, commit_date, repo, wr["run_started_at"], wr["updated_at"])
            pr, sha = rl.pr_for_agent_run(wr.get("conclusion"), found)
        else:
            if rl.CANARY_PR is None:
                raise rl.Unknown("canary_pr_not_configured")
            pr, sha = rl.canary_pr(gh.json(f"/repos/{repo}/pulls/{rl.CANARY_PR}", "canary_pr"))
        out.update(outcome=rl.REVIEW, pr=str(pr), head_sha=sha)
    except rl.Incomplete as exc:
        out.update(outcome=rl.INCOMPLETE, reason=exc.conclusion)
    except rl.Unknown as exc:
        out.update(outcome=rl.UNKNOWN_KIND, reason=exc.reason)
    return out


def write_probes(gh_knowledge, gh_probe):
    """(п1) комментарий в factory-knowledge и (п2) APPROVE канареечной заявки — обязаны 403."""
    if rl.WRITE_PROBE_ISSUE is None:
        raise rl.Unknown("write_probe_issue_not_configured")
    if rl.CANARY_PR is None:
        raise rl.Unknown("canary_pr_not_configured")
    status, _, data = gh_knowledge.request(
        "POST", f"/repos/{rl.KNOWLEDGE_REPO}/issues/{rl.WRITE_PROBE_ISSUE}/comments",
        {"body": "reviewer write probe — this request must be refused (D-103 §e)"})
    if 200 <= status < 300:
        # Запись прошла — убрать след и остаться красным.
        try:
            cid = json.loads(data).get("id")
            if cid:
                gh_knowledge.request("DELETE", f"/repos/{rl.KNOWLEDGE_REPO}/issues/comments/{cid}")
        except ValueError:
            pass
    rl.judge_write_probe("p1_knowledge_comment", status)
    status, _, _ = gh_probe.request(
        "POST", f"/repos/{os.environ.get('REPO', 'Online-Base1/probe')}/pulls/{rl.CANARY_PR}/reviews",
        {"event": "APPROVE", "body": "reviewer approve probe — this request must be refused (D-103 §e)"})
    rl.judge_write_probe("p2_canary_approve", status)


def fetch_knowledge(gh_knowledge):
    ref = gh_knowledge.json(f"/repos/{rl.KNOWLEDGE_REPO}/commits/{rl.KNOWLEDGE_REF}", "knowledge_ref")["sha"]
    q = urllib.parse.quote
    prompt = gh_knowledge.raw(f"/repos/{rl.KNOWLEDGE_REPO}/contents/{q(rl.PROMPT_PATH)}?ref={ref}", "prompt")
    fmt = gh_knowledge.raw(f"/repos/{rl.KNOWLEDGE_REPO}/contents/{q(rl.FORMAT_PATH)}?ref={ref}", "format")
    try:
        prompt_text, fmt_text = prompt.decode("utf-8"), fmt.decode("utf-8")
    except UnicodeDecodeError:
        raise rl.Unknown("knowledge_not_utf8")
    schema = rl.schema_from_format(fmt_text)
    rl.check_schema_contract(schema)

    def last_commit(path, what):
        commits = gh_knowledge.json(f"/repos/{rl.KNOWLEDGE_REPO}/commits?path={q(path)}&sha={ref}&per_page=1", what)
        if not commits:
            raise rl.Unknown(f"{what}_unknown")
        return commits[0]["sha"]

    # Промпт ссылается на формат, а не повторяет его (D-104 §h): модели
    # уходят оба файла; SHA обоих — в комментарий и итог.
    instructions = prompt_text + "\n\n---\n\n" + fmt_text
    return instructions, schema, last_commit(rl.PROMPT_PATH, "prompt_sha"), last_commit(rl.FORMAT_PATH, "format_sha")


def review(ctx):
    """Возвращает dict: result, findings, prompt_sha, model, canary, comment_posted."""
    st = {"result": None, "findings": None, "prompt_sha": "", "format_sha": "", "model": oc.REVIEW_MODEL,
          "canary": "n/a" if ctx["trigger"] != "canary" else "FAIL", "skipped": False}
    repo, pr, head_sha = ctx["repo"], ctx["pr"], ctx["head_sha"]
    gh_read, gh_probe, gh_knowledge = ctx["gh_read"], ctx["gh_probe"], ctx["gh_knowledge"]
    try:
        comments = gh_read.paginate(f"/repos/{repo}/issues/{pr}/comments", "pr_comments")
        canary_run = ctx["run_id"] if ctx["trigger"] == "canary" else None
        if rl.already_reviewed(comments, head_sha, canary_run):
            st.update(result=rl.DONE, skipped=True, canary="n/a" if ctx["trigger"] != "canary" else "PASS")
            return st

        # Отказы — в каждом прогоне, до всего остального (D-103 §a, §e).
        write_probes(gh_knowledge, gh_probe)

        client = ctx["openai_factory"]()
        for name, verdict, detail in oc.boundary_checks(client, oc.load_expected(ctx["expected_models"])):
            print(f"{name}: {verdict} — {detail}")
            if verdict != oc.PASS:
                raise rl.Unknown(f"openai_boundary:{name.split(' ')[0]}={verdict}")

        prompt, schema, prompt_sha, format_sha = fetch_knowledge(gh_knowledge)
        st["prompt_sha"], st["format_sha"] = prompt_sha, format_sha

        _, task = fetch_task(gh_read, repo, ctx["run_id"])
        pull = gh_read.json(f"/repos/{repo}/pulls/{pr}", "pull")
        if pull["head"]["sha"] != head_sha:
            raise rl.Unknown("head_moved")
        diff = gh_read.raw(f"/repos/{repo}/pulls/{pr}", "diff", accept="application/vnd.github.diff").decode("utf-8", errors="replace")
        runs = gh_read.paginate(f"/repos/{repo}/commits/{head_sha}/check-runs", "check_runs", key="check_runs")
        statuses = gh_read.json(f"/repos/{repo}/commits/{head_sha}/status", "statuses").get("statuses", [])
        # В запрос — только задание, дифф и гейты; pull (с body/title) не передаётся.
        request_input = rl.build_input(task, diff, rl.gates_summary(runs, statuses))
        ctx.setdefault("sent", []).append(request_input)

        r = client.responses.create(
            model=oc.REVIEW_MODEL, instructions=prompt, input=request_input,
            max_output_tokens=REVIEW_MAX_OUTPUT_TOKENS, reasoning={"effort": "medium"},
            text={"format": {"type": "json_schema", "name": "findings", "schema": schema, "strict": False}})
        tin, tout = oc.usage_tokens(r)
        print(f"response: status={getattr(r, 'status', None)} input_tokens={tin} output_tokens={tout}")
        rl.check_response_meta(getattr(r, "status", None), tin, tout)
        findings = rl.parse_response(getattr(r, "output_text", None), schema)["findings"]
        st["findings"] = len(findings)

        if ctx["trigger"] == "canary":
            if not rl.canary_found(findings):
                raise rl.Unknown("canary_missed")
            st["canary"] = "PASS"

        body = rl.format_comment(findings, prompt_sha, oc.REVIEW_MODEL, head_sha, ctx["run_id"], ctx["trigger"], format_sha)
        status, _, _ = gh_probe.request("POST", f"/repos/{repo}/issues/{pr}/comments", {"body": body})
        if status != 201:
            raise rl.Unknown(f"comment_post:{status}")
        st["result"] = rl.DONE
    except rl.Unknown as exc:
        st["result"] = rl.result_line(rl.UNKNOWN_KIND, exc.reason)
    return st


def run_log_text(gh, repo, run_id):
    """Журнал прогона (zip) текстом; (HTTP-статус, текст). Токен дальше редиректа не идёт."""
    status, headers, data = gh.request("GET", f"/repos/{repo}/actions/runs/{run_id}/logs")
    if status in (301, 302, 303, 307, 308):
        location = headers.get("Location") or headers.get("location")
        if not location:
            return 0, ""
        status, _, data = gh.transport("GET", location, {"User-Agent": "factory-reviewer"}, None)
    if status != 200:
        return status, ""
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as zf:
            return 200, "\n".join(zf.read(n).decode("utf-8", errors="replace") for n in zf.namelist() if not n.endswith("/"))
    except zipfile.BadZipFile:
        return 0, ""


def retention_probe(gh, repo, now, current_run_id):
    """Проба срока хранения в каждом прогоне (D-107 §c, D-108 §b–§c) → (итог, подробность).

    Положительная пара: журнал последнего завершённого своего прогона обязан
    читаться этим же токеном (actions:read). Иначе отрицательный исход
    «старый журнал не читается» ничего бы не доказывал — и это тоже failed.
    """
    base = f"/repos/{repo}/actions/workflows/{rl.REVIEWER_WORKFLOW_FILE}/runs?status=completed"
    try:
        recent = [r for r in gh.json(base + "&per_page=5", "runs")["workflow_runs"] if str(r["id"]) != str(current_run_id)]
        if recent:
            st, _ = run_log_text(gh, repo, recent[0]["id"])
            if st != 200:
                return rl.RETENTION_FAILED, f"positive control: log of recent run {recent[0]['id']} -> HTTP {st} (actions:read not enough?)"
        cutoff = (now - datetime.timedelta(days=rl.RETENTION_PROBE_DAYS)).strftime("%Y-%m-%dT%H:%M:%SZ")
        old = gh.json(base + f"&created=%3C%3D{cutoff}&per_page=1", "old_runs")["workflow_runs"]
    except rl.Unknown as exc:
        return rl.RETENTION_FAILED, "runs list: " + exc.reason
    if not old:
        return rl.retention_verdict(None, None, None, now), f"no own run older than {rl.RETENTION_PROBE_DAYS} days (cutoff {cutoff})"
    st, text = run_log_text(gh, repo, old[0]["id"])
    verdict = rl.retention_verdict(old[0], st, text, now)
    return verdict, f"run {old[0]['id']} created {old[0]['created_at']}: log HTTP {st}"


def report(env, gh=None, now=None):
    """Итог прогона ревьюера из выходов resolve и review. Возвращает (строки, код)."""
    outcome, reason = env.get("RESOLVE_OUTCOME", ""), env.get("RESOLVE_REASON", "")
    trigger = env.get("RESOLVE_TRIGGER", "")
    canary = "FAIL" if trigger == "canary" else "n/a"
    findings, prompt_sha, format_sha, model = None, "", "", ""
    if outcome == rl.INCOMPLETE:
        result = rl.result_line(rl.INCOMPLETE, reason)
    elif outcome == rl.UNKNOWN_KIND:
        result = rl.result_line(rl.UNKNOWN_KIND, reason)
    elif outcome == rl.REVIEW:
        result = env.get("REVIEW_RESULT", "")
        if not result:
            result = rl.result_line(rl.UNKNOWN_KIND, f"review_job_{env.get('REVIEW_JOB_RESULT') or 'none'}")
        f = env.get("REVIEW_FINDINGS", "")
        findings = int(f) if f.isdigit() else None
        prompt_sha, model = env.get("REVIEW_PROMPT_SHA", ""), env.get("REVIEW_MODEL", "")
        format_sha = env.get("REVIEW_FORMAT_SHA", "")
        canary = env.get("REVIEW_CANARY") or canary
    else:
        result = rl.result_line(rl.UNKNOWN_KIND, "resolve_job_" + (env.get("RESOLVE_JOB_RESULT") or "none"))
    now = now or datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
    if gh is not None:
        retention, detail = retention_probe(gh, env.get("REPO", ""), now, env.get("GITHUB_RUN_ID", ""))
    else:
        retention, detail = rl.RETENTION_NOT_OBSERVED, "retention probe not run"
    print(f"retention probe: {retention} — {detail}")
    lines = rl.summary_lines(result, findings, prompt_sha, model, canary, kind=trigger,
                             pr=env.get("RESOLVE_PR", ""), head_sha=env.get("RESOLVE_HEAD_SHA", ""),
                             format_sha=format_sha, run_date=now.date().isoformat(), retention=retention)
    red = result.startswith(rl.UNKNOWN_KIND) or canary == "FAIL" or retention == rl.RETENTION_FAILED
    return lines, 1 if red else 0


def _set_outputs(values):
    path = os.environ.get("GITHUB_OUTPUT")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            for k, v in values.items():
                fh.write(f"{k}={v}\n")


def _summary(lines):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as fh:
            fh.write("```text\n" + "\n".join(lines) + "\n```\n")


def _openai_factory():
    for n in ("OPENAI_IDENTITY_PROVIDER_ID", "OPENAI_REVIEWER_SERVICE_ACCOUNT_ID", "OPENAI_WIF_AUDIENCE"):
        if not os.environ.get(n):
            raise rl.Unknown(f"not_configured:{n}")
    import openai_smoke
    from openai import OpenAI

    wi = openai_smoke.workload_identity()
    wi["service_account_id"] = os.environ["OPENAI_REVIEWER_SERVICE_ACCOUNT_ID"]
    return OpenAI(workload_identity=wi)


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    repo = os.environ.get("REPO", "")
    if cmd == "resolve":
        with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
            event = json.load(fh)
        out = resolve(event, GitHub(os.environ.get("GH_TOKEN_READ", "")), repo)
        print(json.dumps(out, ensure_ascii=False))
        _set_outputs({"outcome": out["outcome"], "reason": out["reason"], "trigger": out["trigger"],
                      "pr": out["pr"], "head_sha": out["head_sha"], "run_id": out["run_id"]})
        return 0
    if cmd == "review":
        def factory():
            try:
                return _openai_factory()
            except rl.Unknown:
                raise
            except Exception as exc:
                raise rl.Unknown("openai_client:" + oc.describe(exc)[:120])

        ctx = {"repo": repo, "pr": os.environ["PR"], "head_sha": os.environ["HEAD_SHA"],
               "run_id": os.environ["RUN_ID"], "trigger": os.environ["TRIGGER"],
               "gh_read": GitHub(os.environ.get("GH_TOKEN_READ", "")),
               "gh_probe": GitHub(os.environ.get("GH_TOKEN_PROBE", "")),
               "gh_knowledge": GitHub(os.environ.get("GH_TOKEN_KNOWLEDGE", "")),
               "openai_factory": factory, "expected_models": EXPECTED_MODELS}
        st = review(ctx)
        print(json.dumps({k: v for k, v in st.items()}, ensure_ascii=False))
        _set_outputs({"result": st["result"], "findings": "" if st["findings"] is None else st["findings"],
                      "prompt_sha": st["prompt_sha"], "format_sha": st["format_sha"],
                      "model": st["model"], "canary": st["canary"]})
        return 0
    if cmd == "report":
        lines, code = report(os.environ, gh=GitHub(os.environ.get("GH_TOKEN_READ", "")))
        print("\n".join(lines))
        _summary(lines)
        return code
    print("usage: reviewer.py resolve|review|report", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv))
