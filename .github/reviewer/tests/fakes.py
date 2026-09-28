"""Подделки GitHub API и OpenAI для тестов ревьюера — без сети."""

import hashlib
import io
import json
import re
import zipfile
from types import SimpleNamespace as NS

REPO = "Online-Base1/probe"
KR = "Online-Base1/factory-knowledge"
RUN_ID = 900001
HEAD = "a" * 40
KNOW_SHA = "b" * 40
PROMPT_SHA = "c" * 40
FORMAT_SHA = "9" * 40
CANARY = "CANARY-7f3e-do-not-leak"

SCHEMA = {
    "type": "object",
    "required": ["findings"],
    "additionalProperties": False,
    "properties": {
        "findings": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["file", "line", "message"],
                "additionalProperties": False,
                "properties": {
                    "file": {"type": "string", "minLength": 1},
                    "line": {"type": "integer", "minimum": 1},
                    "message": {"type": "string"},
                },
            },
        },
    },
}


def format_md(schema, blocks=1):
    """standards/findings-format.md: проза и ровно один блок ```json со схемой."""
    block = "```json\n" + json.dumps(schema, indent=2) + "\n```\n"
    return ("# Формат находок\n\nОтвет — JSON по схеме ниже.\n\n" + block * blocks + "\nПример: `{\"findings\": []}`\n").encode()


def log_zip(text):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("report/1_REVIEW_RESULT.txt", text)
    return buf.getvalue()


def task_zip(data, name="task.txt"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr(name, data)
    return buf.getvalue()


def artifact_name(data):
    return "agent-task-" + hashlib.sha256(data).hexdigest()


class World:
    """Состояние поддельного GitHub; каждое поле можно испортить в тесте."""

    def __init__(self, task=b"Add clamp()\n"):
        self.task = task
        self.artifacts = [{"id": 11, "name": artifact_name(task), "expired": False}]
        self.artifact_zip = {11: task_zip(task)}
        self.prs = [self.agent_pr(7)]
        self.commit_dates = {HEAD: "2026-09-28T10:05:00Z"}
        self.comments = {7: []}
        self.diff = "diff --git a/lib/x.ts b/lib/x.ts\n+export const x = 1;\n"
        self.check_runs = [{"name": "gates / unit", "status": "completed", "conclusion": "success",
                            "output": {"summary": "agent text " + CANARY}}]
        self.statuses = []
        self.prompt = "You are the reviewer.".encode()
        self.format = format_md(SCHEMA)
        self.p1_status = 403
        self.p2_status = 403
        self.comment_status = 201
        self.posted = []
        self.deleted = []
        self.calls = []
        self.redirect_auth = []
        self.recent_runs = [{"id": 400, "created_at": "2026-09-29T10:00:00Z"}]
        self.old_runs = []
        self.run_logs = {400: log_zip("REVIEW_RESULT=DONE\n")}

    @staticmethod
    def agent_pr(n, sha=HEAD, login="online-base1-factory-worker[bot]", ref="agent/2026-09-28-x", draft=True, base="main"):
        return {"number": n, "state": "open", "draft": draft, "user": {"login": login},
                "title": "title " + CANARY, "body": "body " + CANARY,
                "base": {"ref": base},
                "head": {"ref": ref, "sha": sha, "repo": {"full_name": REPO}}}

    def transport(self, method, url, headers, body):
        self.calls.append((method, url))
        path = url.replace("https://api.github.com", "")
        path_only = path.split("?")[0]
        if url.startswith("https://blob.example/logs/"):
            self.redirect_auth.append("Authorization" in headers)
            return 200, {}, self.run_logs[int(url.rsplit("/", 1)[1])]
        if url.startswith("https://blob.example/"):
            self.redirect_auth.append("Authorization" in headers)
            return 200, {}, self.artifact_zip[int(url.rsplit("/", 1)[1])]
        if method == "GET" and path_only == f"/repos/{REPO}/actions/workflows/reviewer.yml/runs":
            runs = self.old_runs if "created=" in path else self.recent_runs
            return 200, {}, json.dumps({"workflow_runs": runs}).encode()
        m = re.fullmatch(rf"/repos/{REPO}/actions/runs/(\d+)/logs", path_only)
        if method == "GET" and m:
            log = self.run_logs.get(int(m.group(1)), 404)
            if isinstance(log, int):
                return log, {}, b"{}"
            return 302, {"Location": f"https://blob.example/logs/{m.group(1)}"}, b""
        if method == "GET" and path_only == f"/repos/{REPO}/actions/runs/{RUN_ID}/artifacts":
            return self._page(path, {"artifacts": self.artifacts}, "artifacts")
        m = re.fullmatch(rf"/repos/{REPO}/actions/artifacts/(\d+)/zip", path_only)
        if method == "GET" and m:
            return 302, {"Location": f"https://blob.example/{m.group(1)}"}, b""
        if method == "GET" and path_only == f"/repos/{REPO}/pulls":
            return self._page(path, self.prs, None)
        m = re.fullmatch(rf"/repos/{REPO}/pulls/(\d+)", path_only)
        if method == "GET" and m:
            pr = next((p for p in self.prs if p["number"] == int(m.group(1))), None)
            if pr is None:
                return 404, {}, b"{}"
            if headers.get("Accept") == "application/vnd.github.diff":
                return 200, {}, self.diff.encode()
            return 200, {}, json.dumps(pr).encode()
        m = re.fullmatch(rf"/repos/{REPO}/commits/([0-9a-f]+)", path_only)
        if method == "GET" and m:
            d = self.commit_dates.get(m.group(1))
            if d is None:
                return 404, {}, b"{}"
            return 200, {}, json.dumps({"commit": {"committer": {"date": d}, "message": "msg " + CANARY}}).encode()
        if method == "GET" and re.fullmatch(rf"/repos/{REPO}/commits/[0-9a-f]+/check-runs", path_only):
            return self._page(path, {"check_runs": self.check_runs}, "check_runs")
        if method == "GET" and re.fullmatch(rf"/repos/{REPO}/commits/[0-9a-f]+/status", path_only):
            return 200, {}, json.dumps({"statuses": self.statuses}).encode()
        m = re.fullmatch(rf"/repos/{REPO}/issues/(\d+)/comments", path_only)
        if m and method == "GET":
            return self._page(path, self.comments.get(int(m.group(1)), []), None)
        if m and method == "POST":
            if self.comment_status != 201:
                return self.comment_status, {}, b"{}"
            self.posted.append((int(m.group(1)), json.loads(body)["body"]))
            return 201, {}, b'{"id": 1}'
        if method == "POST" and re.fullmatch(rf"/repos/{KR}/issues/\d+/comments", path_only):
            return self.p1_status, {}, b'{"id": 555}' if self.p1_status == 201 else b"{}"
        if method == "DELETE" and path_only == f"/repos/{KR}/issues/comments/555":
            self.deleted.append(555)
            return 204, {}, b""
        if method == "POST" and re.fullmatch(rf"/repos/{REPO}/pulls/\d+/reviews", path_only):
            return self.p2_status, {}, b"{}"
        if method == "GET" and path_only == f"/repos/{KR}/commits/main":
            return 200, {}, json.dumps({"sha": KNOW_SHA}).encode()
        if method == "GET" and path_only == f"/repos/{KR}/contents/prompts/05-review.md":
            return (200, {}, self.prompt) if self.prompt is not None else (404, {}, b"{}")
        if method == "GET" and path_only == f"/repos/{KR}/contents/standards/findings-format.md":
            return (200, {}, self.format) if self.format is not None else (404, {}, b"{}")
        if method == "GET" and path_only == f"/repos/{KR}/commits":
            sha = FORMAT_SHA if "findings-format" in path else PROMPT_SHA
            return 200, {}, json.dumps([{"sha": sha}]).encode()
        return 599, {}, json.dumps({"unrouted": [method, path]}).encode()

    # Сеть в тестах запрещена: любой вызов мимо подделки — ошибка.

    @staticmethod
    def _page(path, payload, key):
        page = int((re.search(r"[?&]page=(\d+)", path) or [None, "1"])[1])
        if page > 1:
            payload = {key: []} if key else []
        return 200, {}, json.dumps(payload).encode()


class ApiError(Exception):
    def __init__(self, status, code):
        super().__init__(code)
        self.status_code, self.code = status, code
        self.body = {"code": code}


class FakeOpenAI:
    def __init__(self, models=("gpt-5.3-codex",), nano_ok=False, review_text=None,
                 review_status="completed", usage=(1200, 300)):
        self.models_ids = list(models)
        self.nano_ok = nano_ok
        self.review_text = review_text if review_text is not None else json.dumps({"findings": []})
        self.review_status = review_status
        self.usage = usage
        self.requests = []
        self.models = NS(list=lambda: [NS(id=m) for m in self.models_ids])
        self.responses = NS(create=self._create)

    def _create(self, **kw):
        self.requests.append(kw)
        if kw["model"] == "gpt-4.1-nano":
            if self.nano_ok:
                return NS(id="r", status="completed", usage=NS(input_tokens=3, output_tokens=1), incomplete_details=None)
            raise ApiError(403, "model_not_found")
        if "instructions" not in kw:
            return NS(id="probe", status="completed", usage=NS(input_tokens=13, output_tokens=5), incomplete_details=None)
        tin, tout = self.usage
        return NS(id="rev", status=self.review_status, output_text=self.review_text,
                  usage=NS(input_tokens=tin, output_tokens=tout), incomplete_details=None)


def workflow_run(conclusion="success", path=".github/workflows/agent.yml"):
    return {"workflow_run": {"id": RUN_ID, "path": path, "conclusion": conclusion,
                             "run_started_at": "2026-09-28T10:00:00Z", "updated_at": "2026-09-28T10:20:00Z"}}
