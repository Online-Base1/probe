"""Механика ревьюера другого семейства: чистая логика без сети.

D-098 (свой шаг на API, запуск с main по workflow_run), D-099/D-101 (граница —
allowlist; сверка в каждом прогоне), D-091 §b (объяснения автора не читаются),
D-102 (снимок задания, исходы, доступ к промпту), D-103 (хеш в имени артефакта,
отказы в каждом прогоне, «находок нет» ≠ галочка, ночная канарейка), L-010
(нет учёта расхода — нет доказательства вызова).

Исходы прогона ревьюера:
  DONE                       — ревью состоялось (о качестве кода это не говорит);
  AGENT_RUN_INCOMPLETE(<c>)  — прогон агента не завершён, ревью не делается;
  UNKNOWN(<причина>)         — судить не по чему; красный.

Всё, что приходит из сети, передаётся сюда уже полученным: так каждая проверка
гоняется на подделках (tests/test_reviewer_lib.py, tests/test_reviewer_flow.py).
"""

import datetime
import hashlib
import io
import json
import re
import zipfile

# --- Константы. Меняются заявкой, не настройкой (D-100 §f, D-101 §a). ---

ARTIFACT_PREFIX = "agent-task-"
TASK_FILE = "task.txt"

KNOWLEDGE_REPO = "Online-Base1/factory-knowledge"
KNOWLEDGE_REF = "main"
# Пути названы в D-104 §h: промпт один на обоих ревьюеров, формат находок —
# отдельный стандарт; промпт на него ссылается. Схема ответа — единственный
# блок ```json в формате (договор с «Архитектурой», см. README).
PROMPT_PATH = "prompts/05-review.md"
FORMAT_PATH = "standards/findings-format.md"

WORKER_LOGIN = "online-base1-factory-worker[bot]"
REVIEWER_LOGIN = "online-base1-reviewer[bot]"

AGENT_WORKFLOW_PATH = ".github/workflows/agent.yml"
CANARY_WORKFLOW_PATH = ".github/workflows/canary-trigger.yml"

# Постоянная черновая заявка canary/known-defect → canary-base (probe#34) и
# служебная issue «reviewer-write-probe» в factory-knowledge (#3). Канарейка
# определяется ТОЛЬКО этим номером и прогоном canary-trigger.yml (D-105 §a.1):
# ни тело, ни ветка, ни метка заявки её не делают канарейкой.
CANARY_PR = 34
CANARY_BRANCH = "canary/known-defect"
CANARY_BASE = "canary-base"  # невливаемость базой, а не меткой (D-105 §b)
WRITE_PROBE_ISSUE = 3

# Известный дефект канареечной заявки (D-105 §d): lib/paginate.ts,
# pageCount = Math.floor(total / pageSize) вместо ceil. Успех — находка,
# называющая этот файл и строку с floor; «нет теста на остаток» без этой
# строки успехом не считается.
CANARY_EXPECTED = {"file": "lib/paginate.ts", "lines": (9, 9)}

# Незавершённые исходы прогона агента (D-102 §c). failure — отдельно: он
# «незавершённый», только если заявки нет (провал до PR).
INCOMPLETE_CONCLUSIONS = {"cancelled", "timed_out", "skipped", "startup_failure",
                          "action_required", "neutral", "stale"}

DONE, INCOMPLETE, UNKNOWN_KIND, REVIEW = "DONE", "AGENT_RUN_INCOMPLETE", "UNKNOWN", "REVIEW"

# Срок хранения журналов прогонов (D-107, D-108): не читается без
# администраторского права, поэтому наблюдается. Ожидаемое значение — только
# основа для N; в строку учёта оно не пишется, пока не наблюдено.
EXPECTED_RETENTION_DAYS = 90
RETENTION_MARGIN_DAYS = 7
RETENTION_PROBE_DAYS = EXPECTED_RETENTION_DAYS - RETENTION_MARGIN_DAYS
REVIEWER_WORKFLOW_FILE = "reviewer.yml"
# Строка учёта в журнале; прогоны до её появления несут REVIEW_RESULT= —
# этого достаточно, чтобы доказать, что журнал такого возраста читается.
LEDGER_MARKERS = ("REVIEW_LEDGER ", "REVIEW_RESULT=")
RETENTION_NOT_OBSERVED, RETENTION_FAILED = "not_observed", "failed"

# Учёта прогонов (D-087, BB-22) ещё нет: единственная долговечная запись об
# исходе канарейки — её комментарий. Ротация комментариев включается только
# вместе с учётом (D-106 §d); пока False, ревьюер ничего не удаляет.
LEDGER_AVAILABLE = False

_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_SHA1 = re.compile(r"^[0-9a-f]{40}$")


class Unknown(Exception):
    """Судить не по чему: исход UNKNOWN(reason)."""

    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


class Incomplete(Exception):
    """Прогон агента не завершён: исход AGENT_RUN_INCOMPLETE(conclusion)."""

    def __init__(self, conclusion):
        super().__init__(conclusion)
        self.conclusion = conclusion


def result_line(kind, reason=""):
    if kind == DONE:
        return "DONE"
    return f"{kind}({reason})"


# --- resolve: какой прогон, какое задание, какая заявка ---

def trigger_of(workflow_run):
    """agent | canary по пути файла прогона; иное — UNKNOWN."""
    path = workflow_run.get("path") or ""
    # path бывает с @ref на конце; сравнивается только файл.
    path = path.split("@", 1)[0]
    if path == AGENT_WORKFLOW_PATH:
        return "agent"
    if path == CANARY_WORKFLOW_PATH:
        return "canary"
    raise Unknown(f"unexpected_workflow:{path or 'none'}")


def check_run_conclusion(trigger, conclusion):
    """Незавершённый прогон агента — Incomplete; canary-trigger обязан быть success."""
    if trigger == "canary":
        if conclusion != "success":
            raise Unknown(f"canary_trigger_conclusion:{conclusion}")
        return
    if conclusion in INCOMPLETE_CONCLUSIONS:
        raise Incomplete(conclusion)
    if conclusion not in ("success", "failure"):
        raise Unknown(f"agent_run_conclusion:{conclusion}")


def select_task_artifact(artifacts):
    """Ровно один артефакт с префиксом agent-task-, суффикс — sha256 (D-103 §b)."""
    found = [a for a in artifacts if (a.get("name") or "").startswith(ARTIFACT_PREFIX)]
    if not found:
        raise Unknown("no_task_artifact")
    if len(found) > 1:
        raise Unknown(f"multiple_task_artifacts:{len(found)}")
    art = found[0]
    suffix = art["name"][len(ARTIFACT_PREFIX):]
    if not _SHA256.match(suffix):
        raise Unknown("bad_task_artifact_name")
    if art.get("expired"):
        raise Unknown("task_artifact_expired")
    return art


def task_bytes_from_zip(zip_bytes):
    """Ровно один файл task.txt; байты — как есть."""
    try:
        with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zf:
            names = [n for n in zf.namelist() if not n.endswith("/")]
            if names != [TASK_FILE]:
                raise Unknown(f"task_artifact_content:{','.join(names) or 'empty'}")
            return zf.read(TASK_FILE)
    except zipfile.BadZipFile:
        raise Unknown("task_artifact_not_zip")


def verify_task(artifact_name, data):
    """sha256 байтов задания == суффиксу имени артефакта."""
    want = artifact_name[len(ARTIFACT_PREFIX):]
    got = hashlib.sha256(data).hexdigest()
    if got != want:
        raise Unknown("task_hash_mismatch")
    return got


def select_agent_pr(prs, commit_date, repo, window_start, window_end):
    """Открытая заявка бота-исполнителя, head agent/*, коммит head в окне прогона.

    Ровно одна; окно не расширяется (D-102 §d). commit_date(sha) -> ISO-время.
    Возвращает (номер, head_sha) или None, если ни одной.
    """
    candidates = []
    for pr in prs:
        if pr.get("state") != "open":
            continue
        if (pr.get("user") or {}).get("login") != WORKER_LOGIN:
            continue
        head = pr.get("head") or {}
        if not (head.get("ref") or "").startswith("agent/"):
            continue
        if ((head.get("repo") or {}).get("full_name")) != repo:
            continue
        date = commit_date(head["sha"])
        if date and window_start <= date <= window_end:
            candidates.append((pr["number"], head["sha"]))
    if len(candidates) > 1:
        raise Unknown(f"multiple_agent_prs:{len(candidates)}")
    return candidates[0] if candidates else None


def pr_for_agent_run(conclusion, found):
    """0 заявок: failure → Incomplete(failure) (провал до PR), success → UNKNOWN."""
    if found:
        return found
    if conclusion == "failure":
        raise Incomplete("failure")
    raise Unknown("no_agent_pr")


def canary_pr(pr):
    """Канареечная заявка: номер — константа; ветка и черновик сверяются."""
    if CANARY_PR is None:
        raise Unknown("canary_pr_not_configured")
    if pr.get("number") != CANARY_PR or pr.get("state") != "open" or not pr.get("draft"):
        raise Unknown("canary_pr_state")
    if (pr.get("head") or {}).get("ref") != CANARY_BRANCH:
        raise Unknown("canary_pr_branch")
    if (pr.get("base") or {}).get("ref") != CANARY_BASE:
        raise Unknown("canary_pr_base")
    return pr["number"], pr["head"]["sha"]


# --- review ---

def done_marker(head_sha, canary_run_id=None):
    """Ключ «уже ревьюили»: PR + head SHA; для канарейки ещё run_id её прогона.

    Дифф канарейки один и тот же каждую ночь: без run_id со второй ночи ревью
    пропускалось бы, и пропуск выглядел бы её успехом (D-105 §a).
    """
    if canary_run_id is not None:
        return f"<!-- factory-reviewer: done head_sha={head_sha} canary_run_id={canary_run_id} -->"
    return f"<!-- factory-reviewer: done head_sha={head_sha} -->"


def already_reviewed(comments, head_sha, canary_run_id=None):
    """Комментарий DONE с этим ключом — только от самого ревьюера.

    Маркер от кого-то другого не засчитывается: иначе автор заявки мог бы
    выключить ревью, оставив строку в комментарии.
    """
    marker = done_marker(head_sha, canary_run_id)
    return any((c.get("user") or {}).get("login") == REVIEWER_LOGIN and marker in (c.get("body") or "")
               for c in comments)


def judge_write_probe(name, status):
    """Проба на запись обязана получить 403; 2xx — красный; иное — UNKNOWN."""
    if status == 403:
        return
    if 200 <= status < 300:
        raise Unknown(f"{name}:write_allowed:{status}")
    raise Unknown(f"{name}:unexpected_status:{status}")


def gates_summary(check_runs, statuses):
    """Статусы гейтов: только имя, состояние и итог — без текста вывода."""
    out = [{"name": c.get("name"), "status": c.get("status"), "conclusion": c.get("conclusion")}
           for c in check_runs]
    out += [{"name": s.get("context"), "status": "completed", "conclusion": s.get("state")}
            for s in statuses]
    return sorted(out, key=lambda g: (str(g["name"]), str(g["conclusion"])))


def build_input(task_bytes, diff_text, gates):
    """Запрос по белому списку полей: задание, дифф, гейты. Больше ничего.

    Функция не принимает заявку целиком — body, title и сообщения коммитов
    в неё попасть не могут. Задание — те же байты, что хешировались: без
    перекодировки, нормализации переводов строк и обрезки. Не UTF-8 — UNKNOWN.
    """
    try:
        task_text = task_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise Unknown("task_not_utf8")
    if task_text.encode("utf-8") != task_bytes:
        raise Unknown("task_roundtrip")
    return [{
        "role": "user",
        "content": [
            {"type": "input_text", "text": task_text},
            {"type": "input_text", "text": "PULL REQUEST DIFF (unified):\n" + diff_text},
            {"type": "input_text", "text": "GATE STATUSES (JSON):\n" + json.dumps(gates, ensure_ascii=False, sort_keys=True)},
        ],
    }]


# Проверка ответа по схеме — своим подмножеством JSON Schema, без зависимостей.
# Незнакомое ключевое слово — UNKNOWN(schema_unsupported), а не «не проверено».
_SCHEMA_KEYS = {"$schema", "$id", "title", "description", "type", "properties", "required",
                "additionalProperties", "items", "enum", "minimum", "maximum",
                "minLength", "maxLength", "minItems", "maxItems"}
_TYPES = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}


def check_schema_supported(schema, path="$"):
    if not isinstance(schema, dict):
        raise Unknown(f"schema_unsupported:{path}")
    extra = set(schema) - _SCHEMA_KEYS
    if extra:
        raise Unknown(f"schema_unsupported:{path}:{sorted(extra)[0]}")
    for k, sub in (schema.get("properties") or {}).items():
        check_schema_supported(sub, f"{path}.{k}")
    if "items" in schema:
        check_schema_supported(schema["items"], f"{path}[]")
    if isinstance(schema.get("additionalProperties"), dict):
        raise Unknown(f"schema_unsupported:{path}:additionalProperties(schema)")


_JSON_BLOCK = re.compile(r"^```json[ \t]*\n(.*?)^```[ \t]*$", re.S | re.M)


def schema_from_format(text):
    """Схема ответа — ровно один блок ```json в standards/findings-format.md."""
    blocks = _JSON_BLOCK.findall(text)
    if len(blocks) != 1:
        raise Unknown(f"format_schema_blocks:{len(blocks)}")
    try:
        return json.loads(blocks[0])
    except ValueError:
        raise Unknown("format_schema_not_json")


def check_schema_contract(schema):
    """Договор с «Архитектурой»: верхний объект с массивом findings; у находки file и line."""
    check_schema_supported(schema)
    try:
        items = schema["properties"]["findings"]
        assert schema.get("type") == "object" and items.get("type") == "array"
        props = items["items"]["properties"]
        assert "file" in props and "line" in props
        assert {"file", "line"} <= set(items["items"].get("required", []))
        assert "findings" in schema.get("required", [])
    except (KeyError, TypeError, AssertionError):
        raise Unknown("schema_contract")


def _type_ok(value, t):
    if t == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if t == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return isinstance(value, _TYPES[t])


def validate(value, schema, path="$"):
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        if not any(_type_ok(value, x) for x in types):
            raise Unknown(f"response_schema:{path}:type")
    if "enum" in schema and value not in schema["enum"]:
        raise Unknown(f"response_schema:{path}:enum")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise Unknown(f"response_schema:{path}:minimum")
        if "maximum" in schema and value > schema["maximum"]:
            raise Unknown(f"response_schema:{path}:maximum")
    if isinstance(value, str):
        if len(value) < schema.get("minLength", 0) or len(value) > schema.get("maxLength", len(value)):
            raise Unknown(f"response_schema:{path}:length")
    if isinstance(value, list):
        if len(value) < schema.get("minItems", 0) or len(value) > schema.get("maxItems", len(value)):
            raise Unknown(f"response_schema:{path}:items")
        for i, v in enumerate(value):
            if "items" in schema:
                validate(v, schema["items"], f"{path}[{i}]")
    if isinstance(value, dict):
        for k in schema.get("required", []):
            if k not in value:
                raise Unknown(f"response_schema:{path}.{k}:required")
        props = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            extra = set(value) - set(props)
            if extra:
                raise Unknown(f"response_schema:{path}.{sorted(extra)[0]}:additional")
        for k, v in value.items():
            if k in props:
                validate(v, props[k], f"{path}.{k}")


def parse_response(text, schema):
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        raise Unknown("response_not_json")
    validate(value, schema)
    return value


def check_response_meta(status, input_tokens, output_tokens):
    if status != "completed":
        raise Unknown(f"response_status:{status}")
    if not input_tokens or not output_tokens:
        # L-010: без учёта расхода вызов не доказан.
        raise Unknown("usage_missing_or_zero")


def canary_found(findings):
    """Находка на известный дефект: тот же файл и строка внутри окна."""
    lo, hi = CANARY_EXPECTED["lines"]
    for f in findings:
        line = f.get("line")
        if f.get("file") == CANARY_EXPECTED["file"] and isinstance(line, int) and lo <= line <= hi:
            return True
    return False


# --- вывод ---

_TOKEN_RE = re.compile(r"(ghs_|gh[opur]_|github_pat_|sk-ant-|sk-|eyJ)[A-Za-z0-9_.-]+")


def clean(text, limit=500):
    """Санитизация как в Surface permission denials (agent.yml)."""
    text = _TOKEN_RE.sub("<redacted>", str(text))
    text = re.sub(r"`{3,}", "′′′", text).replace("@", "＠")
    return text[:limit]


def format_comment(findings, prompt_sha, model, head_sha, run_id, trigger, format_sha=""):
    lines = [done_marker(head_sha, run_id if trigger == "canary" else None),
             f"### Ревью другим семейством (прогон агента {run_id})",
             "",
             "Неблокирующее. Модель не видит описания заявки, заголовка и сообщений коммитов (D-091 §b).",
             ""]
    if not findings:
        lines.append("**Находок нет.** Это не зелёная галочка: пустой список от сломанного ревьюера выглядит так же (D-103 §c).")
    else:
        lines.append(f"**Находок: {len(findings)}.**")
        lines.append("")
        for f in findings:
            where = clean(f"{f.get('file')}:{f.get('line')}", 200).replace("`", "′")
            lines.append(f"- `{where}`")
            text = f.get("message") or f.get("summary") or f.get("title") or ""
            if text:
                lines.append("  ```text")
                lines.extend("  " + ln for ln in clean(text, 1500).split("\n"))
                lines.append("  ```")
    lines += ["",
              f"_head_sha `{head_sha}` · MODEL `{model}` · PROMPT_SHA `{prompt_sha}` · FORMAT_SHA `{format_sha}` · trigger `{trigger}`_"]
    return "\n".join(lines) + "\n"


def retention_verdict(old_run, log_status, log_text, now):
    """Итог пробы срока по своему прогону возрастом >= N дней.

    old_run None — прогона такого возраста ещё нет: not_observed, не краснеет
    и не подменяется ожидаемым числом. Прогон есть, а журнал не отдаётся или
    строки в нём нет — failed, красный (D-108 §b–§c).
    """
    if old_run is None:
        return RETENTION_NOT_OBSERVED
    if log_status != 200 or not any(m in (log_text or "") for m in LEDGER_MARKERS):
        return RETENTION_FAILED
    created = datetime.datetime.strptime(old_run["created_at"], "%Y-%m-%dT%H:%M:%SZ")
    return f"observed={(now - created).days}d"


def ledger_expires(run_date, retention):
    """Дата истечения строки (D-107 §a): run_date + наблюдённая нижняя граница.

    Пока срок не наблюдён — not_observed, а не run_date + 90 (D-108 §c).
    """
    if not retention.startswith("observed="):
        return RETENTION_NOT_OBSERVED
    days = int(retention[len("observed="):-1])
    return (datetime.date.fromisoformat(run_date) + datetime.timedelta(days=days)).isoformat()


def rotate_canary_comments(delete):
    """Ротация канареечных комментариев — только при появившемся учёте (D-106 §d)."""
    if not LEDGER_AVAILABLE:
        return "disabled_until_ledger"
    raise NotImplementedError("rotation is built together with the ledger (D-087)")


def summary_lines(result, findings_count, prompt_sha, model, canary, kind="", pr="", head_sha="", format_sha="",
                  run_date="", retention=RETENTION_NOT_OBSERVED):
    if findings_count is None:
        findings = "FINDINGS=n/a"
    elif findings_count == 0:
        findings = "FINDINGS=0 — находок нет"
    else:
        findings = f"FINDINGS={findings_count}"
    return [f"REVIEW_RESULT={result}", findings, f"PROMPT_SHA={prompt_sha or 'n/a'}",
            f"FORMAT_SHA={format_sha or 'n/a'}", f"MODEL={model or 'n/a'}", f"CANARY={canary}",
            f"RETENTION={retention}",
            ledger_line(result, findings_count, prompt_sha, model, canary, kind, pr, head_sha, format_sha,
                        run_date, retention)]


def ledger_line(result, findings_count, prompt_sha, model, canary, kind, pr, head_sha, format_sha,
                run_date, retention):
    """Одна строка учёта фиксированного вида (D-106 §e, D-107 §a) — в сводку и в журнал.

    Порядок полей не меняется: из этих строк учёт наполняется задним числом.
    d086=excluded у канарейки: она проверка инструмента и в счёт D-086 не
    входит (D-104 §f, D-105 §c).
    """
    return " ".join([
        "REVIEW_LEDGER",
        f"kind={kind or 'n/a'}",
        f"pr={pr or 'n/a'}",
        f"head={head_sha or 'n/a'}",
        f"run_date={run_date or 'n/a'}",
        f"expires={ledger_expires(run_date, retention) if run_date else RETENTION_NOT_OBSERVED}",
        f"retention={retention}",
        f"result={result.replace(' ', '_')}",
        f"findings={'n/a' if findings_count is None else findings_count}",
        f"prompt_sha={prompt_sha or 'n/a'}",
        f"format_sha={format_sha or 'n/a'}",
        f"model={model or 'n/a'}",
        f"canary={canary}",
        f"d086={'excluded' if kind == 'canary' else 'counted'}",
    ])
