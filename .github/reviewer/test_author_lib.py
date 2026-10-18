"""Автор тестов другого семейства: чистая логика без сети (D-173, D-174 §d).

Модель возвращает ФАЙЛЫ тестов, а не находки. Схема ответа — единственный
блок ```json в factory-knowledge/standards/test-author-format.md; она держит
форму. Всё, что схема выразить не может, проверяется здесь — и любое
нарушение даёт UNKNOWN: ничего не пишется, причина печатается. Вывод модели
по умолчанию не доверенный.

  пути files      — только tests/unit/**.test.ts(x), без '..', без повторов, размер;
  импорты         — только vitest и interface.module (относительно файла);
  criteria        — ровно строки «- …» задания, у каждой ≥1 тест, имена тестов
                    дословно есть в it("…")/test("…") файлов;
  interface       — продуктовый модуль lib/app/components, экспорты-идентификаторы;
  assumptions     — присутствует, массив (может быть пустым).

Сеть и OpenAI — в test_author.py; здесь всё гоняется на подделках
(tests/test_test_author.py).
"""

import json
import os
import posixpath
import re

from reviewer_lib import Unknown, check_schema_supported, parse_response

PROMPT_PATH = "prompts/03-tests.md"
FORMAT_PATH = "standards/test-author-format.md"

MAX_FILES = 10
MAX_FILE_CHARS = 40000
MAX_TOTAL_BYTES = 200000

_PATH_RE = re.compile(r"^tests/unit/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*/)*[A-Za-z0-9_-][A-Za-z0-9._-]*\.test\.tsx?$")
_MODULE_RE = re.compile(r"^(?:lib|app|components)/(?:[A-Za-z0-9_-][A-Za-z0-9._-]*/)*[A-Za-z0-9_-][A-Za-z0-9._-]*\.tsx?$")
_IDENT_RE = re.compile(r"^[A-Za-z_$][A-Za-z0-9_$]*$")
# Название теста: первый аргумент it/test(.only/.skip/.each — не допускаются)
# — строка в одинарных, двойных или обратных кавычках без подстановок.
_TEST_TITLE_RE = re.compile(r"""\b(?:it|test)\s*\(\s*(["'`])((?:\\.|(?!\1)[^\\])*)\1""")
_IMPORT_RE = re.compile(r"""(?:\bimport\s[^'"`;]*?\bfrom\s*|\bimport\s*\(?\s*|\brequire\s*\(\s*)(["'])([^"']+)\1""")
_TASK_CRITERION_RE = re.compile(r"^\s*-\s+(.*\S)\s*$")


def check_schema_contract(schema):
    """Договор с «Архитектурой» (шаг A): files/criteria/interface/assumptions."""
    check_schema_supported(schema)
    try:
        props = schema["properties"]
        assert schema.get("type") == "object"
        assert {"files", "criteria", "interface"} <= set(schema.get("required", []))
        f = props["files"]["items"]["properties"]
        assert "path" in f and "content" in f
        c = props["criteria"]["items"]["properties"]
        assert "criterion" in c and "tests" in c
        i = props["interface"]["properties"]
        assert "module" in i and "exports" in i
        assert props["assumptions"]["type"] == "array"
    except (KeyError, TypeError, AssertionError):
        raise Unknown("schema_contract")


def _norm(text):
    return " ".join(text.split())


def task_criteria(task_text):
    """Критерии задания — строки «- …» (D-174 §a.3), без маркера, по порядку."""
    out = [_norm(m.group(1)) for line in task_text.splitlines() if (m := _TASK_CRITERION_RE.match(line))]
    if not out:
        raise Unknown("task_without_criteria")
    return out


def check_path(path):
    if not isinstance(path, str) or "\\" in path or ".." in path.split("/") or not _PATH_RE.match(path):
        raise Unknown(f"file_path_outside_tests_unit:{str(path)[:80]}")
    if posixpath.normpath(path) != path:
        raise Unknown(f"file_path_not_normal:{path[:80]}")


def test_titles(content):
    return {m.group(2) for m in _TEST_TITLE_RE.finditer(content)}


def check_imports(path, content, module):
    """Импорт — только vitest и interface.module; тесты-соседи в tests/ можно."""
    target = posixpath.splitext(module)[0]
    for m in _IMPORT_RE.finditer(content):
        spec = m.group(2)
        if spec == "vitest":
            continue
        if not spec.startswith("."):
            raise Unknown(f"import_not_allowed:{path}:{spec[:80]}")
        resolved = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
        if resolved.startswith("tests/"):
            continue
        if posixpath.splitext(resolved)[0] != target and resolved != target:
            raise Unknown(f"import_outside_interface:{path}:{spec[:80]}")


def check_response(value, task_text):
    """Проверки сверх схемы. Возвращает нормализованный ответ или Unknown."""
    if not isinstance(value, dict):
        raise Unknown("response_not_object")
    if "assumptions" not in value:
        raise Unknown("assumptions_missing")
    if not isinstance(value["assumptions"], list) or not all(isinstance(a, str) for a in value["assumptions"]):
        raise Unknown("assumptions_not_list")

    iface = value.get("interface")
    if not isinstance(iface, dict) or "module" not in iface or "exports" not in iface:
        raise Unknown("interface_missing")
    module, exports = iface["module"], iface["exports"]
    if not isinstance(module, str) or ".." in module.split("/") or not _MODULE_RE.match(module):
        raise Unknown(f"interface_module:{str(module)[:80]}")
    if not isinstance(exports, list) or not exports:
        raise Unknown("interface_exports_empty")
    if len(set(exports)) != len(exports) or not all(isinstance(e, str) and _IDENT_RE.match(e) for e in exports):
        raise Unknown("interface_exports_invalid")

    files = value.get("files")
    if not isinstance(files, list) or not files:
        raise Unknown("files_empty")
    if len(files) > MAX_FILES:
        raise Unknown(f"files_too_many:{len(files)}")
    seen, total, titles = set(), 0, set()
    for f in files:
        path, content = f.get("path"), f.get("content")
        check_path(path)
        if path in seen:
            raise Unknown(f"file_path_duplicate:{path}")
        seen.add(path)
        if not isinstance(content, str) or not content.strip():
            raise Unknown(f"file_empty:{path}")
        if len(content) > MAX_FILE_CHARS:
            raise Unknown(f"file_too_large:{path}")
        total += len(content.encode("utf-8"))
        check_imports(path, content, module)
        titles |= test_titles(content)
    if total > MAX_TOTAL_BYTES:
        raise Unknown(f"files_total_too_large:{total}")

    want = task_criteria(task_text)
    got = {}
    for c in value.get("criteria") or []:
        name = _norm(c.get("criterion") or "")
        if not name:
            raise Unknown("criterion_empty")
        if name in got:
            raise Unknown(f"criterion_duplicate:{name[:80]}")
        tests = c.get("tests")
        if not isinstance(tests, list) or not tests:
            raise Unknown(f"criterion_uncovered:{name[:80]}")
        for t in tests:
            if not isinstance(t, str) or not t.strip():
                raise Unknown(f"test_name_empty:{name[:80]}")
            if t not in titles:
                raise Unknown(f"test_not_found:{t[:80]}")
        got[name] = tests
    for name in got:
        if name not in want:
            raise Unknown(f"criterion_not_in_task:{name[:80]}")
    for name in want:
        if name not in got:
            raise Unknown(f"criterion_uncovered:{name[:80]}")
    return value


def parse_and_check(text, schema, task_text):
    """Разбор с отказом на дубль ключа (BB-45), схема, затем проверки сверх неё."""
    return check_response(parse_response(text, schema), task_text)


def build_input(task_bytes):
    """Модели — только байты снимка задания. Ни кода, ни диффа, ни заявки."""
    try:
        task_text = task_bytes.decode("utf-8", errors="strict")
    except UnicodeDecodeError:
        raise Unknown("task_not_utf8")
    return task_text, [{"role": "user", "content": [{"type": "input_text", "text": task_text}]}]


def stub_source(iface):
    """Заглушка модуля: каждый экспорт бросает Error("stub") (D-174 §c)."""
    return "".join(f'export function {name}(..._args: unknown[]): never {{\n  throw new Error("stub");\n}}\n'
                   for name in iface["exports"])


def write_files(value, root):
    """Пишет files под root. Пути уже проверены; повторно — что итог внутри tests/unit."""
    real_root = os.path.realpath(root)
    base = os.path.realpath(os.path.join(root, "tests", "unit"))
    if not base.startswith(real_root + os.sep):
        raise Unknown("tests_unit_escapes_root")
    written = []
    for f in value["files"]:
        check_path(f["path"])
        dest = os.path.join(root, *f["path"].split("/"))
        parent = os.path.realpath(os.path.dirname(dest))
        if parent != base and not parent.startswith(base + os.sep):
            raise Unknown(f"file_path_escapes:{f['path']}")
        if os.path.lexists(dest):
            raise Unknown(f"file_exists:{f['path']}")
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "x", encoding="utf-8") as fh:
            fh.write(f["content"])
        written.append(f["path"])
    return written


def summary(value):
    return json.dumps({"files": [f["path"] for f in value["files"]],
                       "criteria": len(value["criteria"]),
                       "interface": value["interface"],
                       "assumptions": len(value["assumptions"])}, ensure_ascii=False)
