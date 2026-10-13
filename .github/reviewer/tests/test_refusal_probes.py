"""Job refusal-probes (§18′ п.18, D-143 §f): пробы отказа в каждом прогоне и строки REFUSAL_PROBE — без сети."""

import io
import os
import sys
import unittest
from contextlib import redirect_stdout
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
import digest_lib as dl  # noqa: E402
import fakes as F  # noqa: E402
import reviewer as rv  # noqa: E402
import reviewer_lib as rl  # noqa: E402


class Probes(unittest.TestCase):
    def setUp(self):
        self._saved = (rl.CANARY_PR, rl.WRITE_PROBE_ISSUE)
        rl.CANARY_PR, rl.WRITE_PROBE_ISSUE = 50, 42
        self.w = F.World()

    def tearDown(self):
        rl.CANARY_PR, rl.WRITE_PROBE_ISSUE = self._saved

    def run_cmd(self):
        real = rv.GitHub

        def gh(token, transport=None):
            return real(token, self.w.transport)
        env = {"GH_TOKEN_KNOWLEDGE": "k", "GH_TOKEN_PROBE": "p", "REPO": F.REPO}
        with mock.patch.object(rv, "GitHub", gh), mock.patch.dict(os.environ, env), \
                redirect_stdout(io.StringIO()) as so:
            code = rv.main(["reviewer.py", "probes"])
        return code, so.getvalue()

    def test_both_refused_green_and_extracted(self):
        code, out = self.run_cmd()
        self.assertEqual(code, 0)
        self.assertEqual(dl.refusals_of(out), [("p1_knowledge_comment", "403", "refused"),
                                               ("p2_canary_approve", "403", "refused")])

    def test_allowed_write_red_and_still_visible(self):
        # Запись прошла: прогон красный, а строка напечатана ДО вердикта — сводка её видит.
        self.w.p1_status = 201
        code, out = self.run_cmd()
        self.assertEqual(code, 1)
        self.assertEqual(dl.refusals_of(out), [("p1_knowledge_comment", "201", "allowed")])
        self.assertIn("::error::refusal probes: UNKNOWN(p1_knowledge_comment:write_allowed:201)", out)
        self.assertEqual(self.w.deleted, [555])  # след записи убран

    def test_unexpected_status(self):
        self.w.p2_status = 500
        code, out = self.run_cmd()
        self.assertEqual(code, 1)
        self.assertEqual(dl.refusals_of(out)[-1], ("p2_canary_approve", "500", "unexpected"))


if __name__ == "__main__":
    unittest.main()
