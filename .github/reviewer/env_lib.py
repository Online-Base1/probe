"""Среда исполнения (§18′ п.18, D-143): чистая логика без сети.

Среда названа одним файлом — .github/environment.lock.json. Две сверки:

  статическая (reviewer-ci, рабочее дерево) — runs-on, uses@SHA, версия CLI
    исполнителя, файлы требований с хешами. Эти значения меняются только нашей
    заявкой; расхождение — подмена, красный (D-143 §d);
  динамическая (каждый прогон reviewer, agent, digest) — фактические ImageOS,
    ImageVersion, python3 (и версия CLI в agent) против lock-файла. То, что
    меняет площадка (образ, python3), прогон НЕ красит: расхождение печатается
    одной строкой и снимает доказанность пунктов 6, 7, 10, 13, 16; то, что
    меняем только мы (версия CLI), — красный.

Всё, что читается из окружения и файлов, передаётся сюда уже прочитанным
(env_check.py); так каждая ветка гоняется в тестах (tests/test_env.py).
"""

import json
import re

LOCK_PATH = ".github/environment.lock.json"

# Пункты §18′, доказанность которых держится на названной среде (п.18).
UNPROVEN_ON_CHANGE = (6, 7, 10, 13, 16)

REQUIRED = ("runner_label", "image_os", "image_version", "python3", "claude_code_version", "uses",
            "hashed_requirements")
# Меняет площадка: расхождение снимает доказанность, прогон не красит.
PLATFORM_FIELDS = ("image_os", "image_version", "python3")
# Меняем только мы: расхождение — красный.
OWN_FIELDS = ("claude_code_version",)

# Строки ubuntu-latest допустимы только внутри фикстур app-token-test.yml:
# там это текст создаваемого и тут же удаляемого файла, а не ярлык нашего job.
FIXTURE_FILES = ("app-token-test.yml",)

_SHA = re.compile(r"^[0-9a-f]{40}$")
_RUNS_ON = re.compile(r"^\s*runs-on:\s*(\S+)")
_USES = re.compile(r"^\s*(?:-\s*)?uses:\s*([^\s@#]+)@(\S+)")
_CLI = re.compile(r"^\s*CLAUDE_CODE_VERSION:\s*\"?([^\"\s#]+)\"?")
_REQ_REF = re.compile(r"-r\s+(\.github/workflows/[\w.-]+\.requirements\.txt)")


class LockError(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def parse_lock(text):
    """lock-файл → dict; отсутствует, не JSON, нет поля, пустое поле — LockError."""
    if text is None:
        raise LockError(f"lock-файл {LOCK_PATH} отсутствует")
    try:
        lock = json.loads(text)
    except ValueError as exc:
        raise LockError(f"lock-файл не JSON ({exc.__class__.__name__})")
    if not isinstance(lock, dict):
        raise LockError("lock-файл не объект")
    for field in REQUIRED:
        if field not in lock:
            raise LockError(f"в lock-файле нет поля {field}")
        if lock[field] in ("", None, [], {}):
            raise LockError(f"поле {field} в lock-файле пустое")
    for addr, sha in lock["uses"].items():
        if not _SHA.match(str(sha)):
            raise LockError(f"uses[{addr}] в lock-файле — не 40-символьный SHA")
    return lock


# --- динамическая сверка ---

def compare_runtime(lock, actual, fields):
    """actual — {поле: фактическое значение | None (не прочитано)}; fields — что сверять.

    → {status: match|drift|red|unknown, checked, diffs, red, unread, unproven_items}.
    unproven_items — пункты 6, 7, 10, 13, 16 при любом статусе, кроме match:
    доказательство в среде, которая не подтверждена как названная, не засчитывается.
    """
    checked, diffs, red, unread = {}, [], [], []
    for field in fields:
        expected, got = lock[field], actual.get(field)
        checked[field] = {"expected": expected, "actual": got}
        if got in (None, ""):
            unread.append(field)
        elif got != expected:
            (red if field in OWN_FIELDS else diffs).append({"field": field, "expected": expected, "actual": got})
    status = "red" if red else "drift" if diffs else "unknown" if unread else "match"
    return {"status": status, "checked": checked, "diffs": diffs, "red": red, "unread": unread,
            "unproven_items": [] if status == "match" else list(UNPROVEN_ON_CHANGE)}


def runtime_line(result):
    """Одна строка в журнал: что было и что стало (D-143 §d)."""
    items = ", ".join(map(str, result.get("unproven_items") or UNPROVEN_ON_CHANGE))
    if result["status"] == "lock_error":
        return f"ENV_CHECK unknown: {result['reason']}; доказанность пунктов {items} снята"
    changes = "; ".join(f"{d['field']} {d['expected']} -> {d['actual']}" for d in result["red"] + result["diffs"])
    unread = ", ".join(result["unread"])
    if result["status"] == "match":
        return "ENV_CHECK match: " + " ".join(f"{f}={v['actual']}" for f, v in result["checked"].items())
    if result["status"] == "red":
        return (f"ENV_CHECK red: {changes} — значение меняем только мы, расхождение — подмена; "
                f"доказанность пунктов {items} снята")
    if result["status"] == "drift":
        tail = f"; не прочитано: {unread}" if unread else ""
        return f"ENV_CHECK drift: {changes}{tail}; доказанность пунктов {items} снята"
    return f"ENV_CHECK unknown: не прочитано: {unread}; доказанность пунктов {items} снята"


def lock_error_result(reason):
    return {"status": "lock_error", "reason": reason, "checked": {}, "diffs": [], "red": [], "unread": [],
            "unproven_items": list(UNPROVEN_ON_CHANGE)}


def python3_version(text):
    """«Python 3.12.3» → «3.12.3»; иное — None."""
    m = re.match(r"^Python (\d+\.\d+\.\d+)\s*$", (text or "").strip())
    return m.group(1) if m else None


def cli_version(text):
    """«2.1.283 (Claude Code)» → «2.1.283»; пусто — None."""
    text = (text or "").strip()
    return text.split(" ", 1)[0] if text else None


# --- статическая сверка рабочего дерева ---

def logical_lines(text):
    """Строки файла требований со склеенными продолжениями «\\»."""
    out, cur = [], ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if line.endswith("\\"):
            cur += line[:-1] + " "
            continue
        out.append(cur + line)
        cur = ""
    if cur:
        out.append(cur)
    return [ln.strip() for ln in out if ln.strip() and not ln.strip().startswith("#")]


def static_violations(lock, workflows, repo_files):
    """workflows — {имя файла в .github/workflows: текст}; repo_files — {путь: текст | None}.

    → список нарушений словами; пустой — рабочее дерево совпадает с lock-файлом.
    """
    out, used = [], set()
    label = lock["runner_label"]
    for name in sorted(workflows):
        if not name.endswith((".yml", ".yaml")):
            continue
        for i, line in enumerate(workflows[name].splitlines(), 1):
            where = f"{name}:{i}"
            m = _RUNS_ON.match(line)
            if m and m.group(1) != label:
                out.append(f"{where}: runs-on {m.group(1)} != {label} (lock)")
            if "ubuntu-latest" in line and not (name in FIXTURE_FILES and not m):
                out.append(f"{where}: ubuntu-latest вне фикстур app-token-test")
            u = _USES.match(line)
            if u:
                addr, ref = u.group(1), u.group(2)
                if addr.startswith("./"):
                    continue
                if not _SHA.match(ref):
                    out.append(f"{where}: uses {addr}@{ref} не закреплён SHA")
                elif addr not in lock["uses"]:
                    out.append(f"{where}: uses {addr} нет в lock-файле")
                elif lock["uses"][addr] != ref:
                    out.append(f"{where}: uses {addr}@{ref[:7]} != {lock['uses'][addr][:7]} (lock)")
                used.add(addr)
    for addr in sorted(set(lock["uses"]) - used):
        out.append(f"lock: uses {addr} не встречается ни в одном потоке")

    agent = workflows.get("agent.yml")
    cli = [m.group(1) for m in map(_CLI.match, (agent or "").splitlines()) if m]
    if agent is None:
        out.append("agent.yml отсутствует: версию CLI исполнителя сверить не с чем")
    elif cli != [lock["claude_code_version"]]:
        out.append(f"agent.yml: CLAUDE_CODE_VERSION {cli or 'не найден'} != {lock['claude_code_version']} (lock)")

    for path in lock["hashed_requirements"]:
        text = repo_files.get(path)
        if text is None:
            out.append(f"{path}: файл требований из lock-файла отсутствует")
            continue
        for req in logical_lines(text):
            if "--hash=sha256:" not in req:
                out.append(f"{path}: требование без хеша: {req.split()[0]}")
    for name in sorted(workflows):
        for ref in _REQ_REF.findall(workflows[name]):
            if ref not in lock["hashed_requirements"]:
                out.append(f"{name}: -r {ref} нет в lock-файле")
            if "--require-hashes" not in workflows[name]:
                out.append(f"{name}: -r {ref} без --require-hashes")
    return out
