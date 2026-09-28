"""Симуляция всех исходов openai_checks без сети: python3 -m unittest discover -s .github/reviewer/tests"""

import json
import os
import sys
import tempfile
import unittest
from types import SimpleNamespace as NS

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import openai_checks as oc  # noqa: E402

EXPECTED = ["gpt-5.3-codex"]


class ApiError(Exception):
    """Подделка openai.APIStatusError: status_code, code, body."""

    def __init__(self, status, code, message="x"):
        super().__init__(message)
        self.status_code = status
        self.code = code
        self.body = {"message": message, "type": "invalid_request_error", "param": None, "code": code}


def ok_response(tin=14, tout=9, status="completed"):
    return NS(id="resp_1", status=status, usage=NS(input_tokens=tin, output_tokens=tout), incomplete_details=None)


class FakeClient:
    """models: list | Exception; per_model: model -> response | Exception."""

    def __init__(self, models=EXPECTED, per_model=None):
        per_model = per_model if per_model is not None else {}
        self.calls = []

        def list_models():
            if isinstance(models, Exception):
                raise models
            return [NS(id=m) for m in models]

        def create(**kw):
            self.calls.append(kw)
            r = per_model.get(kw["model"], ApiError(403, "model_not_found"))
            if isinstance(r, Exception):
                raise r
            return r

        self.models = NS(list=list_models)
        self.responses = NS(create=create)


def default_client(**over):
    per_model = {oc.REVIEW_MODEL: ok_response(), oc.DENIED_MODEL: ApiError(403, "model_not_found", "Project does not have access to model `gpt-4.1-nano`")}
    per_model.update(over.pop("per_model", {}))
    return FakeClient(per_model=per_model, **over)


class ModelsList(unittest.TestCase):
    def test_equal(self):
        self.assertEqual(oc.check_models(default_client(), EXPECTED)[0], oc.PASS)

    def test_extra_model(self):
        v, d = oc.check_models(default_client(models=["gpt-5.3-codex", "gpt-4.1-nano"]), EXPECTED)
        self.assertEqual(v, oc.FAIL)
        self.assertIn("extra=['gpt-4.1-nano']", d)

    def test_missing_model(self):
        v, d = oc.check_models(default_client(models=[]), EXPECTED)
        self.assertEqual(v, oc.FAIL)
        self.assertIn("missing=['gpt-5.3-codex']", d)

    def test_other_model(self):
        self.assertEqual(oc.check_models(default_client(models=["gpt-5.3"]), EXPECTED)[0], oc.FAIL)

    def test_no_answer(self):
        self.assertEqual(oc.check_models(default_client(models=ApiError(500, None)), EXPECTED)[0], oc.UNKNOWN)


class Positive(unittest.TestCase):
    def test_completed(self):
        c = default_client()
        self.assertEqual(oc.check_positive(c)[0], oc.PASS)
        self.assertEqual(c.calls[0]["model"], "gpt-5.3-codex")
        self.assertEqual(c.calls[0]["max_output_tokens"], oc.PROBE_MAX_OUTPUT_TOKENS)

    def test_incomplete(self):
        r = ok_response(status="incomplete")
        r.incomplete_details = NS(reason="max_output_tokens")
        v, d = oc.check_positive(default_client(per_model={oc.REVIEW_MODEL: r}))
        self.assertEqual(v, oc.FAIL)
        self.assertIn("incomplete_reason=max_output_tokens", d)

    def test_refused(self):
        self.assertEqual(oc.check_positive(default_client(per_model={oc.REVIEW_MODEL: ApiError(403, "model_not_found")}))[0], oc.UNKNOWN)

    def test_usage_zero(self):
        self.assertEqual(oc.check_positive(default_client(per_model={oc.REVIEW_MODEL: ok_response(tout=0)}))[0], oc.UNKNOWN)

    def test_usage_missing(self):
        r = ok_response()
        r.usage = None
        self.assertEqual(oc.check_positive(default_client(per_model={oc.REVIEW_MODEL: r}))[0], oc.UNKNOWN)


class Negative(unittest.TestCase):
    def test_model_not_found(self):
        self.assertEqual(oc.check_negative(default_client())[0], oc.PASS)

    def test_model_not_found_in_body_only(self):
        e = ApiError(404, "model_not_found")
        e.code = None
        self.assertEqual(oc.check_negative(default_client(per_model={oc.DENIED_MODEL: e}))[0], oc.PASS)

    def test_success_is_fail(self):
        self.assertEqual(oc.check_negative(default_client(per_model={oc.DENIED_MODEL: ok_response()}))[0], oc.FAIL)

    def test_other_error_is_unknown(self):
        for e in (ApiError(401, "invalid_api_key"), ApiError(429, "rate_limit_exceeded"), ApiError(403, None), TimeoutError("t")):
            with self.subTest(e=e):
                self.assertEqual(oc.check_negative(default_client(per_model={oc.DENIED_MODEL: e}))[0], oc.UNKNOWN)


class AdminApi(unittest.TestCase):
    def test_refused(self):
        for st in (401, 403):
            self.assertEqual(oc.check_admin_api_refused(lambda url, st=st: st)[0], oc.PASS)

    def test_reachable_is_fail(self):
        self.assertEqual(oc.check_admin_api_refused(lambda url: 200)[0], oc.FAIL)

    def test_other_is_unknown(self):
        self.assertEqual(oc.check_admin_api_refused(lambda url: 404)[0], oc.UNKNOWN)
        self.assertEqual(oc.check_admin_api_refused(lambda url: 500)[0], oc.UNKNOWN)

    def test_no_answer_is_unknown(self):
        def boom(url):
            raise TimeoutError("t")
        self.assertEqual(oc.check_admin_api_refused(boom)[0], oc.UNKNOWN)

    def test_documented_endpoint(self):
        self.assertEqual(oc.ADMIN_PROBE_URL, "https://api.openai.com/v1/organization/projects?limit=1")


class Boundary(unittest.TestCase):
    def test_all_pass(self):
        self.assertEqual([v for _, v, _ in oc.boundary_checks(default_client(), EXPECTED)], [oc.PASS] * 3)

    def test_expected_file(self):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "expected-models.json")
        self.assertEqual(oc.load_expected(path), ["gpt-5.3-codex"])

    def test_expected_file_rejects_bad(self):
        for bad in ([], "gpt", [""], [1]):
            with self.subTest(bad=bad), tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as fh:
                json.dump(bad, fh)
            with self.assertRaises(ValueError):
                oc.load_expected(fh.name)
            os.unlink(fh.name)

    def test_describe_without_body_is_scrubbed(self):
        d = oc.describe(RuntimeError("invalid_grant: eyJhbGc.eyJzdWI.sig Bearer abc"))
        self.assertIn("invalid_grant", d)
        self.assertNotIn("eyJhbGc", d)
        self.assertNotIn("abc", d)

    def test_scrub(self):
        s = oc.scrub("Bearer abc.def eyJa.eyJb.c sk-1234567890abcdef")
        self.assertNotIn("abc.def", s)
        self.assertNotIn("eyJa", s)
        self.assertNotIn("sk-1234567890", s)


if __name__ == "__main__":
    unittest.main()
