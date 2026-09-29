"""Дымовой тест федерации и allowlist OpenAI (openai-wif-test.yml).

  (а) ключей OPENAI_API_KEY / ANTHROPIC_API_KEY / OPENAI_ADMIN_KEY в окружении нет;
  (б) обмен OIDC-токена GitHub на токен OpenAI успешен;
  (в)–(д) — openai_checks.boundary_checks;
  (е) обмен по привязке Reviewer-Run отсюда → только invalid_grant, и только
      при успешном (б) в этом же прогоне;
  (ж) токен не администраторский — проба области (D-109 §d). Состав WIF-привязок
      этим не наблюдается: допущение «состав WIF-привязок не наблюдаем» остаётся.

Любой итог, кроме PASS, — выход 1. Токены не печатаются.
"""

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openai_checks as oc  # noqa: E402

EXPECTED_MODELS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "expected-models.json")


def github_oidc_token():
    # OIDC-токен GitHub с audience из переменной; значение не печатается.
    url = os.environ["ACTIONS_ID_TOKEN_REQUEST_URL"] + "&audience=" + urllib.parse.quote(os.environ["OPENAI_WIF_AUDIENCE"], safe="")
    req = urllib.request.Request(url, headers={"Authorization": "bearer " + os.environ["ACTIONS_ID_TOKEN_REQUEST_TOKEN"]})
    with urllib.request.urlopen(req, timeout=10) as resp:
        value = json.load(resp).get("value", "")
    if not value:
        raise RuntimeError("GitHub did not issue an OIDC token")
    return value


def oidc_claims():
    """Claims OIDC-токена GitHub для диагностики отказа обмена — без самого токена."""
    import base64
    payload = github_oidc_token().split(".")[1]
    data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    keys = ("iss", "aud", "sub", "repository", "repository_id", "repository_owner_id", "ref",
            "workflow_ref", "job_workflow_ref", "event_name", "run_id")
    return {k: data.get(k) for k in keys}


def workload_identity():
    return {
        "identity_provider_id": os.environ["OPENAI_IDENTITY_PROVIDER_ID"],
        "service_account_id": os.environ["OPENAI_SERVICE_ACCOUNT_ID"],
        "provider": {"token_type": "jwt", "get_token": github_oidc_token},
    }


def admin_get_status(wi):
    """GET к Admin API WIF-токеном; возвращается только HTTP-статус."""
    from openai.auth import WorkloadIdentityAuth

    token = WorkloadIdentityAuth(workload_identity=wi).get_token()

    def http_get(url):
        req = urllib.request.Request(url, headers={"Authorization": "Bearer " + token})
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                return resp.status
        except urllib.error.HTTPError as exc:
            return exc.code

    try:
        return oc.check_admin_api_refused(http_get)
    finally:
        del token


def main():
    results = []

    def record(name, verdict, detail):
        results.append((name, verdict))
        print(f"{name}: {verdict} — {detail}")

    print(f"ref={os.environ.get('REF')}")
    present = [n for n in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_ADMIN_KEY") if n in os.environ]
    record("(а) no static keys in env", oc.FAIL if present else oc.PASS, "present: " + (", ".join(present) or "none"))

    for n in ("OPENAI_IDENTITY_PROVIDER_ID", "OPENAI_SERVICE_ACCOUNT_ID", "OPENAI_WIF_AUDIENCE"):
        if not os.environ.get(n):
            print(f"::error::repository variable {n} is empty")
            return 1

    expected = oc.load_expected(EXPECTED_MODELS)
    print(f"expected models ({os.path.relpath(EXPECTED_MODELS)}): {expected}")

    from openai import OpenAI
    from openai.auth import WorkloadIdentityAuth

    wi = workload_identity()
    # (б) обмен — отдельно от вызовов API, чтобы отказ обмена не путался
    # с отказом allowlist.
    try:
        token = WorkloadIdentityAuth(workload_identity=wi).get_token()
        record("(б) token exchange", oc.PASS if token else oc.FAIL, "access token received (not printed)")
        del token
        exchanged = True
    except Exception as exc:
        record("(б) token exchange", oc.FAIL, oc.describe(exc))
        exchanged = False

    # (е) — сразу после (б): отказ засчитывается только в паре с успешным (б).
    reviewer_sa = os.environ.get("OPENAI_REVIEWER_SERVICE_ACCOUNT_ID", "")
    if reviewer_sa:
        wi_rev = dict(wi, service_account_id=reviewer_sa)
        record("(е) Reviewer-Run binding refused here",
               *oc.check_foreign_binding_refused(lambda: WorkloadIdentityAuth(workload_identity=wi_rev).get_token(), exchanged))
    else:
        record("(е) Reviewer-Run binding refused here", oc.UNKNOWN, "OPENAI_REVIEWER_SERVICE_ACCOUNT_ID is not set")

    if exchanged:
        for name, verdict, detail in oc.boundary_checks(OpenAI(workload_identity=wi), expected):
            record(name, verdict, detail)
        record("(ж) token is not admin-scoped", *admin_get_status(wi))
    else:
        for name in ("(в) models.list == expected", "(г) responses.create allowed model", "(д) responses.create denied model", "(ж) token is not admin-scoped"):
            record(name, oc.UNKNOWN, "not run: token exchange failed")

    bad = [f"{n}={v}" for n, v in results if v != oc.PASS]
    if bad:
        print("::error::not PASS: " + ", ".join(bad))
        return 1
    print("openai federation and allowlist: all checks PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
