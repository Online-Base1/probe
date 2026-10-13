"""Названная среда (§18′ п.18, D-143): lock-файл, динамическая и статическая сверки — без сети."""

import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
import env_check as ec  # noqa: E402
import env_lib as el  # noqa: E402

SHA_A, SHA_B = "a" * 40, "b" * 40
LOCK = {
    "schema": 1, "runner_label": "ubuntu-24.04", "image_os": "ubuntu24", "image_version": "20261004.327.1",
    "python3": "3.12.3", "claude_code_version": "2.1.283",
    "uses": {"actions/checkout": SHA_A, "Online-Base1/factory-ci/.github/workflows/gates.yml": SHA_B},
    "hashed_requirements": [".github/workflows/x.requirements.txt"],
}
ACTUAL = {"image_os": "ubuntu24", "image_version": "20261004.327.1", "python3": "3.12.3", "claude_code_version": "2.1.283"}


class Lock(unittest.TestCase):
    def test_parses(self):
        self.assertEqual(el.parse_lock(json.dumps(LOCK))["runner_label"], "ubuntu-24.04")

    def test_missing_file(self):
        with self.assertRaises(el.LockError) as c:
            el.parse_lock(None)
        self.assertIn("отсутствует", c.exception.reason)

    def test_missing_field(self):
        lock = dict(LOCK)
        del lock["image_version"]
        with self.assertRaises(el.LockError) as c:
            el.parse_lock(json.dumps(lock))
        self.assertEqual(c.exception.reason, "в lock-файле нет поля image_version")

    def test_empty_field(self):
        for field, empty in (("python3", ""), ("uses", {}), ("hashed_requirements", [])):
            with self.subTest(field=field), self.assertRaises(el.LockError) as c:
                el.parse_lock(json.dumps({**LOCK, field: empty}))
            self.assertEqual(c.exception.reason, f"поле {field} в lock-файле пустое")

    def test_not_json_and_bad_sha(self):
        with self.assertRaises(el.LockError):
            el.parse_lock("{not json")
        with self.assertRaises(el.LockError) as c:
            el.parse_lock(json.dumps({**LOCK, "uses": {"actions/checkout": "v4"}}))
        self.assertIn("не 40-символьный SHA", c.exception.reason)

    @unittest.skipUnless(os.environ.get("REVIEWER_WORKFLOW_TESTS") == "required"
                         or os.path.isfile(os.path.join(HERE, "..", "..", "environment.lock.json")),
                         "environment.lock.json not checked out")
    def test_repository_lock_is_valid(self):
        # Сам lock-файл репозитория разбирается — и в нём только поля, у которых есть наблюдение.
        path = os.path.join(HERE, "..", "..", "environment.lock.json")
        with open(path, encoding="utf-8") as fh:
            lock = el.parse_lock(fh.read())
        for field in el.REQUIRED:
            if field not in ("uses", "hashed_requirements"):
                self.assertIn(field, lock["observed_in"], field)
        for addr in lock["uses"]:
            self.assertIn(addr, lock["observed_in"], addr)


class Runtime(unittest.TestCase):
    def test_match(self):
        r = el.compare_runtime(LOCK, ACTUAL, el.PLATFORM_FIELDS)
        self.assertEqual((r["status"], r["unproven_items"]), ("match", []))
        self.assertEqual(el.runtime_line(r),
                         "ENV_CHECK match: image_os=ubuntu24 image_version=20261004.327.1 python3=3.12.3")

    def test_image_drift_does_not_red(self):
        r = el.compare_runtime(LOCK, {**ACTUAL, "image_version": "20261011.1.1"}, el.PLATFORM_FIELDS)
        self.assertEqual(r["status"], "drift")
        self.assertEqual(r["unproven_items"], [6, 7, 10, 13, 16])
        self.assertEqual(el.runtime_line(r), "ENV_CHECK drift: image_version 20261004.327.1 -> 20261011.1.1; "
                                             "доказанность пунктов 6, 7, 10, 13, 16 снята")

    def test_python_drift(self):
        r = el.compare_runtime(LOCK, {**ACTUAL, "python3": "3.12.4"}, el.PLATFORM_FIELDS)
        self.assertEqual([d["field"] for d in r["diffs"]], ["python3"])

    def test_tool_version_drift_is_red(self):
        fields = el.PLATFORM_FIELDS + el.OWN_FIELDS
        r = el.compare_runtime(LOCK, {**ACTUAL, "claude_code_version": "2.1.300"}, fields)
        self.assertEqual(r["status"], "red")
        self.assertIn("ENV_CHECK red: claude_code_version 2.1.283 -> 2.1.300 — значение меняем только мы", el.runtime_line(r))

    def test_unread_is_unknown_not_match(self):
        r = el.compare_runtime(LOCK, {**ACTUAL, "image_version": None}, el.PLATFORM_FIELDS)
        self.assertEqual(r["status"], "unknown")
        self.assertEqual(r["unproven_items"], [6, 7, 10, 13, 16])
        self.assertEqual(el.runtime_line(r), "ENV_CHECK unknown: не прочитано: image_version; "
                                             "доказанность пунктов 6, 7, 10, 13, 16 снята")

    def test_versions_parsed(self):
        self.assertEqual(el.python3_version("Python 3.12.3\n"), "3.12.3")
        self.assertIsNone(el.python3_version("Python 3.12.3rc1"))
        self.assertEqual(el.cli_version("2.1.283 (Claude Code)"), "2.1.283")
        self.assertIsNone(el.cli_version(""))


class RuntimeScript(unittest.TestCase):
    """env_check.runtime: строка в журнал, JSON для артефакта, код выхода."""

    def run_rt(self, env, lock_text=json.dumps(LOCK), cli=None, cli_out="2.1.283 (Claude Code)"):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "env-check.json")
            versions = {"python3": "Python 3.12.3"}

            def fake_version(cmd):
                return cli_out if cmd[0] == "claude" else versions.get(cmd[0])
            with mock.patch.object(ec, "read", lambda p: lock_text if p == el.LOCK_PATH else None), \
                    mock.patch.object(ec, "run_version", fake_version), \
                    mock.patch.dict(os.environ, env, clear=True), redirect_stdout(io.StringIO()) as so:
                code = ec.runtime("digest", out, cli, env={"GITHUB_RUN_ID": "77"})
            with open(out, encoding="utf-8") as fh:
                return code, json.load(fh), so.getvalue()

    def test_match_artifact(self):
        code, art, log = self.run_rt({"ImageOS": "ubuntu24", "ImageVersion": "20261004.327.1"})
        self.assertEqual((code, art["status"], art["run_id"], art["unproven_items"]), (0, "match", "77", []))
        self.assertTrue(log.startswith("ENV_CHECK match:"))

    def test_drift_not_red_artifact_lists_items(self):
        code, art, log = self.run_rt({"ImageOS": "ubuntu24", "ImageVersion": "20261011.1.1"})
        self.assertEqual((code, art["status"], art["unproven_items"]), (0, "drift", [6, 7, 10, 13, 16]))
        self.assertIn("::warning::ENV_CHECK drift: image_version 20261004.327.1 -> 20261011.1.1", log)

    def test_tool_red_exit_1(self):
        code, art, _ = self.run_rt({"ImageOS": "ubuntu24", "ImageVersion": "20261004.327.1"}, cli="claude",
                                   cli_out="2.1.300 (Claude Code)")
        self.assertEqual((code, art["status"]), (1, "red"))

    def test_lock_missing_not_red(self):
        code, art, log = self.run_rt({"ImageOS": "ubuntu24"}, lock_text=None)
        self.assertEqual((code, art["status"]), (0, "lock_error"))
        self.assertIn("отсутствует", log)

    def test_env_unset_is_unknown(self):
        code, art, _ = self.run_rt({})
        self.assertEqual((code, art["status"], art["unread"]), (0, "unknown", ["image_os", "image_version"]))


WF = {
    "a.yml": "jobs:\n  x:\n    runs-on: ubuntu-24.04\n    steps:\n      - uses: actions/checkout@" + SHA_A + " # v7\n",
    "ci.yml": "jobs:\n  g:\n    uses: Online-Base1/factory-ci/.github/workflows/gates.yml@" + SHA_B + "\n",
    "agent.yml": "    env:\n      CLAUDE_CODE_VERSION: \"2.1.283\" # pin\n"
                 "    run: pip install --require-hashes -r .github/workflows/x.requirements.txt\n",
    "app-token-test.yml": "jobs:\n  t:\n    runs-on: ubuntu-24.04\n    run: printf 'name: x\\njobs:\\n  x:\\n    runs-on: ubuntu-latest\\n'\n",
}
REQ = {".github/workflows/x.requirements.txt": "# c\nfoo==1.0 \\\n    --hash=sha256:" + "0" * 64 + "\n"}


class Static(unittest.TestCase):
    def v(self, workflows=None, files=None, lock=None):
        return el.static_violations(lock or LOCK, workflows if workflows is not None else WF,
                                    files if files is not None else REQ)

    def test_clean(self):
        self.assertEqual(self.v(), [])

    def test_runs_on_other_label(self):
        bad = self.v({**WF, "b.yml": "jobs:\n  y:\n    runs-on: ubuntu-22.04\n"})
        self.assertEqual(bad, ["b.yml:3: runs-on ubuntu-22.04 != ubuntu-24.04 (lock)"])

    def test_ubuntu_latest_only_in_fixture(self):
        bad = self.v({**WF, "deploy.yml": "jobs:\n  b:\n    runs-on: ubuntu-latest\n"})
        self.assertEqual(bad, ["deploy.yml:3: runs-on ubuntu-latest != ubuntu-24.04 (lock)",
                               "deploy.yml:3: ubuntu-latest вне фикстур app-token-test"])
        # в фикстуре app-token-test — допустимо; ключ runs-on там же — нет
        bad = self.v({**WF, "app-token-test.yml": WF["app-token-test.yml"] + "    runs-on: ubuntu-latest\n"})
        self.assertIn("app-token-test.yml:5: ubuntu-latest вне фикстур app-token-test", bad)

    def test_uses_sha_mismatch_unknown_unpinned_stale(self):
        bad = self.v({**WF, "a.yml": WF["a.yml"].replace(SHA_A, "c" * 40)})
        self.assertIn("a.yml:5: uses actions/checkout@ccccccc != aaaaaaa (lock)", bad)
        bad = self.v({**WF, "b.yml": "      - uses: actions/cache@" + "d" * 40 + "\n"})
        self.assertIn("b.yml:1: uses actions/cache нет в lock-файле", bad)
        bad = self.v({**WF, "b.yml": "      - uses: actions/cache@v4\n"})
        self.assertIn("b.yml:1: uses actions/cache@v4 не закреплён SHA", bad)
        bad = self.v({k: v for k, v in WF.items() if k != "ci.yml"})
        self.assertIn("lock: uses Online-Base1/factory-ci/.github/workflows/gates.yml не встречается ни в одном потоке", bad)

    def test_cli_version(self):
        bad = self.v({**WF, "agent.yml": WF["agent.yml"].replace("2.1.283", "2.1.300")})
        self.assertIn("agent.yml: CLAUDE_CODE_VERSION ['2.1.300'] != 2.1.283 (lock)", bad)
        bad = self.v({k: v for k, v in WF.items() if k != "agent.yml"})
        self.assertIn("agent.yml отсутствует: версию CLI исполнителя сверить не с чем", bad)

    def test_requirements(self):
        bad = self.v(files={".github/workflows/x.requirements.txt": "foo==1.0\n"})
        self.assertEqual(bad, [".github/workflows/x.requirements.txt: требование без хеша: foo==1.0"])
        bad = self.v(files={})
        self.assertEqual(bad, [".github/workflows/x.requirements.txt: файл требований из lock-файла отсутствует"])
        bad = self.v({**WF, "agent.yml": WF["agent.yml"].replace("--require-hashes ", "")})
        self.assertIn("agent.yml: -r .github/workflows/x.requirements.txt без --require-hashes", bad)
        bad = self.v({**WF, "o.yml": "run: pip install --require-hashes -r .github/workflows/y.requirements.txt\n"})
        self.assertIn("o.yml: -r .github/workflows/y.requirements.txt нет в lock-файле", bad)

    @unittest.skipUnless(os.environ.get("REVIEWER_WORKFLOW_TESTS") == "required"
                         or os.path.isfile(os.path.join(HERE, "..", "..", "workflows", "agent.yml")),
                         "workflow files not checked out")
    def test_repository_tree_matches_lock(self):
        # Рабочее дерево самого репозитория — как в шаге reviewer-ci «Environment lock (static)».
        with redirect_stdout(io.StringIO()) as so:
            code = ec.static()
        self.assertEqual(code, 0, so.getvalue())


if __name__ == "__main__":
    unittest.main()
