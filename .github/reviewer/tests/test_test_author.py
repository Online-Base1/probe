"""Автор тестов без сети: адаптер test_author.py и проверки test_author_lib (D-173, D-174 §d).

Формат ответа — копия standards/test-author-format.md (шаг A) в tests/fixtures:
шаг C не зависит от вливания A.

python3 -m unittest discover -s .github/reviewer/tests
"""

import contextlib
import copy
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import fakes as F  # noqa: E402
import reviewer as rv  # noqa: E402
import reviewer_lib as rl  # noqa: E402
import test_author as tau  # noqa: E402
import test_author_lib as ta  # noqa: E402

EXPECTED = os.path.join(HERE, "..", "expected-models.json")
with open(os.path.join(HERE, "fixtures", "test-author-format.md"), "rb") as _fh:
    FORMAT = _fh.read()
SCHEMA = rl.schema_from_format(FORMAT.decode("utf-8"))
PROMPT = ("Ты — автор тестов. Ответ строго по standards/test-author-format.md.").encode()

TASK = ("В продуктовый код probe добавить чистую функцию slugify(text):\n"
        "- нижний регистр;\n"
        "- не-ASCII буквы считать разделителями;\n"
        "- пустой вход → '' (пустая строка);\n"
        "Больше ничего не менять.\n").encode()

CONTENT = ('import { describe, expect, it, test } from "vitest";\n'
           'import { slugify } from "../../lib/slug";\n\n'
           'describe("slugify", () => {\n'
           '  it("переводит в нижний регистр", () => {\n    expect(slugify("AbC")).toBe("abc");\n  });\n'
           "  it('не-ASCII буква — разделитель', () => {\n    expect(slugify(\"a\\u212Ab\")).toBe(\"a-b\");\n  });\n"
           '  test(`пустой вход`, () => {\n    expect(slugify("")).toBe("");\n  });\n'
           '});\n')

VALID = {
    "files": [{"path": "tests/unit/slug.test.ts", "content": CONTENT}],
    "criteria": [
        {"criterion": "нижний регистр;", "tests": ["переводит в нижний регистр"]},
        {"criterion": "не-ASCII буквы считать разделителями;", "tests": ["не-ASCII буква — разделитель"]},
        {"criterion": "пустой вход → '' (пустая строка);", "tests": ["пустой вход"]},
    ],
    "interface": {"module": "lib/slug.ts", "exports": ["slugify"]},
    "assumptions": ["Модуль не назван в задании; выбран lib/slug.ts."],
}


def artifact(task=TASK):
    return "agent-task-" + hashlib.sha256(task).hexdigest()


def variant(**changes):
    v = copy.deepcopy(VALID)
    for k, val in changes.items():
        if val is None:
            v.pop(k, None)
        else:
            v[k] = val
    return v


class Base(unittest.TestCase):
    def setUp(self):
        self.w = F.World()
        self.w.knowledge = {ta.PROMPT_PATH: PROMPT, ta.FORMAT_PATH: FORMAT}

    def run_author(self, response=VALID, task=TASK, name=None, client=None, write_root=""):
        text = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
        self.client = client or F.FakeOpenAI(review_text=text)
        self.ctx = {"task_bytes": task, "task_artifact": name or artifact(task),
                    "gh_knowledge": rv.GitHub("tok", transport=self.w.transport),
                    "openai_factory": lambda: self.client, "expected_models": EXPECTED,
                    "write_root": write_root}
        with contextlib.redirect_stdout(io.StringIO()) as out:
            st = tau.author(self.ctx)
        self.out = out.getvalue()
        return st


class Valid(Base):
    def test_valid_response_done(self):
        st = self.run_author()
        self.assertEqual(st["result"], "DONE")
        self.assertEqual(st["value"]["interface"], {"module": "lib/slug.ts", "exports": ["slugify"]})
        self.assertEqual((st["prompt_sha"], st["format_sha"]), (F.PROMPT_SHA, F.FORMAT_SHA))

    def test_model_gets_only_the_task(self):
        # Кода нет и не отправляется: один блок — байты снимка задания.
        self.run_author()
        (msg,), = self.ctx["sent"]
        self.assertEqual(msg["content"], [{"type": "input_text", "text": TASK.decode()}])
        req = next(r for r in self.client.requests if "instructions" in r)
        self.assertEqual(req["model"], "gpt-5.3-codex")
        self.assertEqual(req["text"]["format"]["schema"], SCHEMA)
        self.assertIn(PROMPT.decode(), req["instructions"])
        self.assertIn(FORMAT.decode(), req["instructions"])

    def test_writes_files_under_tests_unit(self):
        with tempfile.TemporaryDirectory() as root:
            st = self.run_author(write_root=root)
            self.assertEqual(st["result"], "DONE")
            with open(os.path.join(root, "tests", "unit", "slug.test.ts"), encoding="utf-8") as fh:
                self.assertEqual(fh.read(), CONTENT)

    def test_empty_assumptions_allowed(self):
        self.assertEqual(self.run_author(variant(assumptions=[]))["result"], "DONE")

    def test_fixture_schema_matches_contract(self):
        ta.check_schema_contract(SCHEMA)
        self.assertIn(ta.FORMAT_PATH, PROMPT.decode())

    def test_stub_throws_per_export(self):
        src = ta.stub_source({"module": "lib/x.ts", "exports": ["a", "b"]})
        self.assertEqual(src.count('throw new Error("stub")'), 2)
        self.assertIn("export function a(", src)
        self.assertIn("export function b(", src)


class Refused(Base):
    def refused(self, response, reason, **kw):
        with tempfile.TemporaryDirectory() as root:
            st = self.run_author(response, write_root=root, **kw)
            self.assertIsNone(st["value"])
            self.assertTrue(st["result"].startswith(f"UNKNOWN({reason}"), st["result"])
            self.assertFalse(os.path.exists(os.path.join(root, "tests")), "nothing written on UNKNOWN")
        return st

    def test_duplicate_key(self):
        # BB-45: второй "files" не должен молча заменить первый.
        text = json.dumps(VALID, ensure_ascii=False)[:-1] + ', "assumptions": []}'
        self.refused(text, "response_duplicate_key")

    def test_duplicate_nested_key(self):
        text = json.dumps(VALID, ensure_ascii=False).replace('"module": "lib/slug.ts"', '"module": "lib/slug.ts", "module": "lib/x.ts"')
        self.refused(text, "response_duplicate_key")

    def test_prose_around_json(self):
        self.refused("Вот тесты:\n" + json.dumps(VALID), "response_not_json")

    def test_path_outside_tests_unit(self):
        for p in ("lib/slug.test.ts", "tests/slug.test.ts", "tests/unit/../../lib/slug.test.ts",
                  "/tests/unit/slug.test.ts", "tests\\unit\\slug.test.ts", "tests/unit/slug.ts",
                  "tests/unit/.hidden/x.test.ts", "tests/unit//x.test.ts"):
            with self.subTest(p=p):
                self.refused(variant(files=[{"path": p, "content": CONTENT}]), "file_path_")

    def test_duplicate_path(self):
        f = {"path": "tests/unit/slug.test.ts", "content": CONTENT}
        self.refused(variant(files=[f, f]), "file_path_duplicate")

    def test_file_too_large(self):
        big = CONTENT + "//" + "x" * ta.MAX_FILE_CHARS
        self.refused(variant(files=[{"path": "tests/unit/slug.test.ts", "content": big}]), "response_schema")
        with self.assertRaises(rl.Unknown) as cm:
            ta.check_response(variant(files=[{"path": "tests/unit/slug.test.ts", "content": big}]), TASK.decode())
        self.assertEqual(cm.exception.reason, "file_too_large:tests/unit/slug.test.ts")

    def test_uncovered_criterion(self):
        self.refused(variant(criteria=VALID["criteria"][:2]), "criterion_uncovered")

    def test_criterion_without_tests(self):
        crit = copy.deepcopy(VALID["criteria"])
        crit[0]["tests"] = []
        self.refused(variant(criteria=crit), "response_schema")          # схема: minItems 1
        with self.assertRaises(rl.Unknown) as cm:
            ta.check_response(variant(criteria=crit), TASK.decode())     # и сама проверка, без схемы
        self.assertTrue(cm.exception.reason.startswith("criterion_uncovered"))

    def test_blank_test_name(self):
        crit = copy.deepcopy(VALID["criteria"])
        crit[0]["tests"] = ["   "]
        self.refused(variant(criteria=crit), "test_name_empty")

    def test_test_name_not_in_files(self):
        crit = copy.deepcopy(VALID["criteria"])
        crit[0]["tests"] = ["такого теста нет"]
        self.refused(variant(criteria=crit), "test_not_found")

    def test_criterion_not_in_task(self):
        crit = copy.deepcopy(VALID["criteria"]) + [{"criterion": "лишний критерий", "tests": ["пустой вход"]}]
        self.refused(variant(criteria=crit), "criterion_not_in_task")

    def test_duplicate_criterion(self):
        crit = copy.deepcopy(VALID["criteria"]) + [copy.deepcopy(VALID["criteria"][0])]
        self.refused(variant(criteria=crit), "criterion_duplicate")

    def test_interface_missing(self):
        self.refused(variant(interface=None), "response_schema")
        with self.assertRaises(rl.Unknown) as cm:
            ta.check_response(variant(interface=None), TASK.decode())
        self.assertEqual(cm.exception.reason, "interface_missing")

    def test_interface_module_not_product(self):
        for m in ("tests/unit/slug.ts", "lib/../slug.ts", "src/slug.ts", "lib/slug"):
            with self.subTest(m=m):
                self.refused(variant(interface={"module": m, "exports": ["slugify"]}), "interface_module")

    def test_interface_exports_invalid(self):
        for e in ([], ["slug-ify"], ["slugify", "slugify"]):
            with self.subTest(e=e):
                v = variant(interface={"module": "lib/slug.ts", "exports": e})
                with self.assertRaises(rl.Unknown) as cm:
                    ta.check_response(v, TASK.decode())
                self.assertTrue(cm.exception.reason.startswith("interface_exports"), cm.exception.reason)

    def test_assumptions_missing(self):
        # В схеме шага A поле необязательно — отказ держит адаптер.
        self.refused(variant(assumptions=None), "assumptions_missing")

    def test_assumptions_not_list(self):
        with self.assertRaises(rl.Unknown) as cm:
            ta.check_response(variant(assumptions="нет"), TASK.decode())
        self.assertEqual(cm.exception.reason, "assumptions_not_list")

    def test_import_not_allowed(self):
        bad = CONTENT.replace('import { slugify } from "../../lib/slug";', 'import { slugify } from "../../lib/slug";\nimport _ from "lodash";')
        self.refused(variant(files=[{"path": "tests/unit/slug.test.ts", "content": bad}]), "import_not_allowed")

    def test_import_outside_interface(self):
        bad = CONTENT.replace('"../../lib/slug"', '"../../lib/other"')
        self.refused(variant(files=[{"path": "tests/unit/slug.test.ts", "content": bad}]), "import_outside_interface")

    def test_task_without_criteria_model_not_called(self):
        task = b"Add slugify. No criteria lines here.\n"
        st = self.run_author(task=task)
        self.assertEqual(st["result"], "UNKNOWN(task_without_criteria)")
        self.assertEqual(self.client.requests, [])

    def test_task_hash_mismatch(self):
        st = self.run_author(name="agent-task-" + "0" * 64)
        self.assertEqual(st["result"], "UNKNOWN(task_hash_mismatch)")
        self.assertEqual(self.client.requests, [])

    def test_boundary_failure(self):
        st = self.run_author(client=F.FakeOpenAI(models=("gpt-5.3-codex", "gpt-4o"), review_text=json.dumps(VALID)))
        self.assertTrue(st["result"].startswith("UNKNOWN(openai_boundary:"), st["result"])

    def test_response_incomplete(self):
        st = self.run_author(client=F.FakeOpenAI(review_text=json.dumps(VALID), review_status="incomplete"))
        self.assertEqual(st["result"], "UNKNOWN(response_status:incomplete)")

    def test_prompt_must_refer_format(self):
        self.w.knowledge[ta.PROMPT_PATH] = b"no format reference"
        self.assertEqual(self.run_author()["result"], "UNKNOWN(prompt_without_format_ref)")

    def test_format_two_json_blocks(self):
        self.w.knowledge[ta.FORMAT_PATH] = FORMAT + b"\n```json\n{}\n```\n"
        self.assertEqual(self.run_author()["result"], "UNKNOWN(format_schema_blocks:2)")

    def test_reviewer_format_rejected_as_contract(self):
        # Схема находок ревьюера не годится автору тестов.
        self.w.knowledge[ta.FORMAT_PATH] = F.format_md(F.SCHEMA)
        self.assertEqual(self.run_author()["result"], "UNKNOWN(schema_contract)")


class WriteFiles(unittest.TestCase):
    def test_existing_file_not_overwritten(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "tests", "unit"))
            open(os.path.join(root, "tests", "unit", "slug.test.ts"), "w").close()
            with self.assertRaises(rl.Unknown) as cm:
                ta.write_files(VALID, root)
            self.assertEqual(cm.exception.reason, "file_exists:tests/unit/slug.test.ts")

    def test_symlinked_tests_unit_escape_refused(self):
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as outside:
            os.makedirs(os.path.join(root, "tests"))
            os.symlink(outside, os.path.join(root, "tests", "unit"))
            with self.assertRaises(rl.Unknown) as cm:
                ta.write_files(VALID, root)
            self.assertEqual(cm.exception.reason, "tests_unit_escapes_root")
            self.assertEqual(os.listdir(outside), [])


class Cli(Base):
    def run_main(self, response):
        text = json.dumps(response, ensure_ascii=False)
        client = F.FakeOpenAI(review_text=text)
        with tempfile.TemporaryDirectory() as d:
            task = os.path.join(d, "task.txt")
            with open(task, "wb") as fh:
                fh.write(TASK)
            out = os.path.join(d, "out.json")
            env = {"TASK_FILE": task, "TASK_ARTIFACT": artifact(), "OUT": out, "GH_TOKEN_KNOWLEDGE": "tok"}
            saved = (rv.GitHub, rv._openai_factory)
            rv.GitHub = lambda token, transport=None: saved[0](token, transport=self.w.transport)
            self.factory_args = []
            rv._openai_factory = lambda *a: self.factory_args.append(a) or client
            try:
                with unittest.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()) as o:
                    code = tau.main(["test_author.py", "author"])
            finally:
                rv.GitHub, rv._openai_factory = saved
            written = json.load(open(out)) if os.path.exists(out) else None
        return code, o.getvalue(), written

    def test_done_writes_out(self):
        code, out, written = self.run_main(VALID)
        self.assertEqual(code, 0)
        self.assertIn("TEST_AUTHOR_RESULT=DONE", out)
        self.assertEqual(written, VALID)
        # Клиент — по сервисному аккаунту автора тестов, не ревьюера.
        self.assertEqual(self.factory_args, [("OPENAI_TEST_AUTHOR_SERVICE_ACCOUNT_ID", "Test-Author-Run")])

    def test_unknown_writes_nothing(self):
        code, out, written = self.run_main(variant(assumptions=None))
        self.assertEqual(code, 1)
        self.assertIn("TEST_AUTHOR_RESULT=UNKNOWN(assumptions_missing)", out)
        self.assertIsNone(written)

    def test_factory_uses_test_author_account(self):
        env = {"OPENAI_IDENTITY_PROVIDER_ID": "idp", "OPENAI_WIF_AUDIENCE": "aud",
               "OPENAI_REVIEWER_SERVICE_ACCOUNT_ID": "reviewer-sa"}
        with unittest.mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(rl.Unknown) as cm:
                rv._openai_factory(tau.SERVICE_ACCOUNT_VAR, tau.BINDING)
        # Аккаунт ревьюера не подставляется вместо аккаунта автора тестов.
        self.assertEqual(cm.exception.reason, "not_configured:OPENAI_TEST_AUTHOR_SERVICE_ACCOUNT_ID")


import unittest.mock  # noqa: E402

if __name__ == "__main__":
    unittest.main()


# --- Шаг E: артефакт, заглушка, вердикт на заглушке ---------------------------

def tests_artifact(value=VALID):
    data = json.dumps(value, ensure_ascii=False, indent=2).encode()
    return "agent-tests-" + hashlib.sha256(data).hexdigest(), data


def vitest_report(statuses, path="tests/unit/slug.test.ts", titles=None, message=""):
    titles = titles or ["переводит в нижний регистр", "не-ASCII буква — разделитель", "пустой вход"]
    return {"testResults": [{
        "name": "/home/runner/work/probe/probe/" + path,
        "status": "failed" if "failed" in statuses or not statuses else "passed",
        "message": message,
        "assertionResults": [{"title": t, "fullName": "slugify " + t, "status": st,
                              "failureMessages": ["Error: stub"] if st == "failed" else []}
                             for t, st in zip(titles, statuses)]}]}


class StageArtifact(unittest.TestCase):
    def test_artifact_roundtrip(self):
        name, data = tests_artifact()
        self.assertEqual(ta.load_tests_artifact(name, data)["interface"]["module"], "lib/slug.ts")

    def test_artifact_hash_mismatch(self):
        name, data = tests_artifact()
        with self.assertRaises(rl.Unknown) as cm:
            ta.load_tests_artifact(name, data + b" ")
        self.assertEqual(cm.exception.reason, "tests_hash_mismatch")

    def test_artifact_wrong_prefix(self):
        _, data = tests_artifact()
        with self.assertRaises(rl.Unknown) as cm:
            ta.load_tests_artifact("agent-task-" + hashlib.sha256(data).hexdigest(), data)
        self.assertEqual(cm.exception.reason, "tests_artifact_name")

    def test_artifact_duplicate_key(self):
        data = json.dumps(VALID, ensure_ascii=False)[:-1].encode() + b', "assumptions": []}'
        with self.assertRaises(rl.Unknown) as cm:
            ta.load_tests_artifact("agent-tests-" + hashlib.sha256(data).hexdigest(), data)
        self.assertEqual(cm.exception.reason, "response_duplicate_key")

    def test_artifact_rechecked(self):
        # Артефакт проверяется заново: подложенный путь вне tests/unit — отказ и здесь.
        name, data = tests_artifact(variant(files=[{"path": "lib/slug.test.ts", "content": CONTENT}]))
        with self.assertRaises(rl.Unknown) as cm:
            ta.load_tests_artifact(name, data)
        self.assertTrue(cm.exception.reason.startswith("file_path_outside_tests_unit"))

    def test_branch_slug(self):
        self.assertEqual(ta.branch_slug({"module": "lib/group-by.ts"}), "group-by")
        self.assertEqual(ta.branch_slug({"module": "components/CostsView.tsx"}), "costsview")
        self.assertEqual(ta.branch_slug({"module": "lib/__.ts"}), "tests")

    def test_write_stub_replaces_module(self):
        with tempfile.TemporaryDirectory() as root:
            os.makedirs(os.path.join(root, "lib"))
            with open(os.path.join(root, "lib", "slug.ts"), "w") as fh:
                fh.write("export const real = 1;\n")
            self.assertEqual(ta.write_stub(VALID, root), "lib/slug.ts")
            with open(os.path.join(root, "lib", "slug.ts")) as fh:
                self.assertEqual(fh.read(), ta.stub_source(VALID["interface"]))

    def test_write_stub_refuses_bad_module(self):
        with tempfile.TemporaryDirectory() as root, self.assertRaises(rl.Unknown):
            ta.write_stub(variant(interface={"module": "../x.ts", "exports": ["f"]}), root)


class StubVerdict(unittest.TestCase):
    def test_all_failed_passes(self):
        self.assertEqual(ta.stub_verdict(vitest_report(["failed"] * 3), VALID), [])

    def test_green_on_stub_named(self):
        p = ta.stub_verdict(vitest_report(["failed", "passed", "failed"]), VALID)
        self.assertEqual(p, ["green_on_stub:tests/unit/slug.test.ts: slugify не-ASCII буква — разделитель"])

    def test_skipped_and_todo_not_proof(self):
        for st in ("skipped", "todo", "pending"):
            with self.subTest(st=st):
                p = ta.stub_verdict(vitest_report(["failed", st, "failed"]), VALID)
                self.assertTrue(p and p[0].startswith("not_run_on_stub:"), p)

    def test_failed_to_load_is_not_proof(self):
        # Падение на импорте (нет модуля, синтаксис) — файл без тестов: не доказательство.
        r = vitest_report([], message="Error: Failed to load url ../../lib/slug\n at ...")
        p = ta.stub_verdict(r, VALID)
        self.assertTrue(p[0].startswith("failed_to_load:tests/unit/slug.test.ts: Error: Failed to load"), p)

    def test_file_not_run(self):
        p = ta.stub_verdict(vitest_report(["failed"] * 3, path="tests/unit/other.test.ts"), VALID)
        self.assertEqual(p[0], "not_run:tests/unit/slug.test.ts")

    def test_criterion_test_must_run(self):
        r = vitest_report(["failed", "failed"], titles=["переводит в нижний регистр", "пустой вход"])
        self.assertEqual(ta.stub_verdict(r, VALID), ["criterion_test_not_run:не-ASCII буква — разделитель"])

    def test_unreadable_report(self):
        self.assertEqual(ta.stub_verdict(None, VALID), ["stub_report_unreadable"])
        self.assertEqual(ta.stub_verdict({"x": 1}, VALID), ["stub_report_unreadable"])


class StageCli(unittest.TestCase):
    def run_stage(self, cmd, value=VALID, report=None, extra=None, tamper=False):
        with tempfile.TemporaryDirectory() as d:
            name, data = tests_artifact(value)
            resp = os.path.join(d, "response.json")
            with open(resp, "wb") as fh:
                fh.write(data + (b" " if tamper else b""))
            env = {"TESTS_ARTIFACT": name, "RESPONSE": resp, "WRITE_ROOT": os.path.join(d, "root")}
            os.makedirs(env["WRITE_ROOT"])
            if report is not None:
                env["REPORT"] = os.path.join(d, "report.json")
                with open(env["REPORT"], "w") as fh:
                    json.dump(report, fh)
            env.update(extra or {})
            with unittest.mock.patch.dict(os.environ, env), contextlib.redirect_stdout(io.StringIO()) as o:
                code = tau.main(["test_author.py", cmd])
            tree = sorted(os.path.relpath(os.path.join(dp, f), env["WRITE_ROOT"])
                          for dp, _, fs in os.walk(env["WRITE_ROOT"]) for f in fs)
        return code, o.getvalue(), tree

    def test_materialize_tests_only(self):
        code, out, tree = self.run_stage("materialize")
        self.assertEqual((code, tree), (0, ["tests/unit/slug.test.ts"]))
        self.assertIn("files=tests/unit/slug.test.ts", out)

    def test_materialize_with_stub(self):
        code, out, tree = self.run_stage("materialize", extra={"STUB": "1"})
        self.assertEqual((code, tree), (0, ["lib/slug.ts", "tests/unit/slug.test.ts"]))

    def test_materialize_tampered_artifact_writes_nothing(self):
        code, out, tree = self.run_stage("materialize", tamper=True)
        self.assertEqual((code, tree), (1, []))
        self.assertIn("UNKNOWN(tests_hash_mismatch)", out)

    def test_slug(self):
        code, out, _ = self.run_stage("slug")
        self.assertEqual((code, out.strip()), (0, "slug"))

    def test_stub_verdict_pass_and_fail(self):
        code, out, _ = self.run_stage("stub-verdict", report=vitest_report(["failed"] * 3))
        self.assertEqual(code, 0)
        self.assertIn("STUB_CHECK=PASS", out)
        code, out, _ = self.run_stage("stub-verdict", report=vitest_report(["failed", "passed", "failed"]))
        self.assertEqual(code, 1)
        self.assertIn("green_on_stub", out)

    def test_stub_verdict_missing_report_fails(self):
        code, out, _ = self.run_stage("stub-verdict", extra={"REPORT": "/nonexistent/report.json"})
        self.assertEqual(code, 1)
        self.assertIn("stub_report_unreadable", out)
