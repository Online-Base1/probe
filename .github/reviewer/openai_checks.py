"""Проверки границы ревьюера OpenAI (D-098, D-099, D-101).

Граница — allowlist моделей проекта, а не права service account: WIF-токены
не ограничиваются Restricted-правами (openai-wif rerun, 2026-09-28). Поэтому
проверяется ровно то, что граница обещает:

  (в) models.list — точно равен .github/reviewer/expected-models.json;
  (г) разрешённая модель отвечает (status=completed, usage > 0);
  (д) неразрешённая модель отклоняется ТОЛЬКО с code=model_not_found.

Итог каждой проверки — PASS, FAIL или UNKNOWN. FAIL — ответ получен и он
противоречит ожиданию; UNKNOWN — ответа, по которому можно судить, нет.
Для конвейера красные оба. Модуль без сетевых зависимостей: клиент
передаётся снаружи, поэтому проверки гоняются на подделках
(tests/test_openai_checks.py).
"""

import json
import re

PASS, FAIL, UNKNOWN = "PASS", "FAIL", "UNKNOWN"

# Разрешённая модель ревьюера — константа, не параметр прогона.
REVIEW_MODEL = "gpt-5.3-codex"
# Заведомо вне allowlist; раньше была разрешена, поэтому её отказ — это
# именно allowlist, а не опечатка в имени.
DENIED_MODEL = "gpt-4.1-nano"
# Минимум, в который помещаются рассуждения codex-модели при effort=low и
# ответ из одного слова; при 16 токенах ответ обрывается (incomplete).
PROBE_MAX_OUTPUT_TOKENS = 128


def scrub(text):
    """Токены, JWT и заголовки не печатаются, даже если сервер их вернул."""
    text = re.sub(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*", "<jwt>", str(text))
    text = re.sub(r"sk-[A-Za-z0-9_-]{8,}", "<key>", text)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer <redacted>", text)
    return " ".join(text.split())[:500]


def describe(exc):
    status = getattr(exc, "status_code", None)
    body = getattr(exc, "body", None)
    if body is not None:
        return f"{type(exc).__name__} status={status} code={error_code(exc)} body={scrub(json.dumps(body, ensure_ascii=False))}"
    # Без тела (ошибка обмена, сеть) — текст исключения, тоже через scrub.
    return f"{type(exc).__name__} status={status} message={scrub(exc)}"


def error_code(exc):
    """code ошибки API: атрибут SDK, иначе поле code в теле."""
    code = getattr(exc, "code", None)
    if code is None:
        body = getattr(exc, "body", None)
        if isinstance(body, dict):
            err = body.get("error")
            # OAuth (RFC 6749): {"error": "invalid_grant"}; API: {"code": ...}
            # или {"error": {"code": ...}}.
            code = body.get("code") or (err if isinstance(err, str) else (err or {}).get("code"))
    return code


def load_expected(path):
    with open(path, encoding="utf-8") as fh:
        value = json.load(fh)
    if not isinstance(value, list) or not value or not all(isinstance(m, str) and m for m in value):
        raise ValueError(f"{path}: expected a non-empty JSON list of model ids")
    return value


def check_models(client, expected):
    """(в) Точное равенство списка моделей ожидаемому (порядок не важен)."""
    try:
        ids = [m.id for m in client.models.list()]
    except Exception as exc:
        return UNKNOWN, "no answer: " + describe(exc)
    if sorted(ids) == sorted(expected):
        return PASS, f"models={sorted(ids)}"
    extra = sorted(set(ids) - set(expected))
    missing = sorted(set(expected) - set(ids))
    return FAIL, f"models={sorted(ids)} expected={sorted(expected)} extra={extra} missing={missing}"


def usage_tokens(response):
    usage = getattr(response, "usage", None)
    return getattr(usage, "input_tokens", None), getattr(usage, "output_tokens", None)


def check_positive(client, model=REVIEW_MODEL):
    """(г) Разрешённая модель отвечает: completed и ненулевой usage (L-010)."""
    try:
        r = client.responses.create(
            model=model,
            input="Reply with the single word: ok",
            max_output_tokens=PROBE_MAX_OUTPUT_TOKENS,
            reasoning={"effort": "low"},
        )
    except Exception as exc:
        return UNKNOWN, f"model={model} no answer: " + describe(exc)
    tin, tout = usage_tokens(r)
    detail = f"model={model} status={getattr(r, 'status', None)} input_tokens={tin} output_tokens={tout}"
    if getattr(r, "status", None) != "completed" or not getattr(r, "id", None):
        reason = getattr(getattr(r, "incomplete_details", None), "reason", None)
        return FAIL, detail + (f" incomplete_reason={reason}" if reason else "")
    if not tin or not tout:
        # Ответ без учёта расхода — не доказательство, что вызов был (L-010).
        return UNKNOWN, detail + " usage missing or zero"
    return PASS, detail


def check_negative(client, model=DENIED_MODEL):
    """(д) Неразрешённая модель: только model_not_found — PASS."""
    try:
        client.responses.create(model=model, input="x", max_output_tokens=16)
    except Exception as exc:
        if error_code(exc) == "model_not_found":
            return PASS, f"model={model} refused: " + describe(exc)
        return UNKNOWN, f"model={model} other error: " + describe(exc)
    return FAIL, f"model={model} request SUCCEEDED — model is not blocked by the allowlist"


# Документированный эндпоинт Admin API; путей для перечисления WIF-провайдеров
# и привязок в документации нет, поэтому их не подбираем.
ADMIN_PROBE_URL = "https://api.openai.com/v1/organization/projects?limit=1"


def check_admin_api_refused(http_get):
    """(ж) Токен не администраторский — проба ОБЛАСТИ токена (D-109 §d).

    http_get(url) -> HTTP-статус; токен остаётся внутри http_get.
    401/403 — PASS, 2xx — FAIL: федеративный токен достаёт до Admin API.

    Это не перечисление привязок. Допущение остаётся в точности таким:
    «состав WIF-привязок не наблюдаем» — (ж) его не закрывает.
    """
    try:
        status = http_get(ADMIN_PROBE_URL)
    except Exception as exc:
        return UNKNOWN, "no answer: " + describe(exc)
    if status in (401, 403):
        return PASS, f"GET /v1/organization/projects -> {status}: the token is not admin-scoped (the set of WIF bindings is still not observed)"
    if 200 <= status < 300:
        return FAIL, f"GET /v1/organization/projects -> {status}: the WIF token reaches the Admin API"
    return UNKNOWN, f"GET /v1/organization/projects -> {status}"


def check_foreign_binding_refused(exchange, own_exchange_ok):
    """(е) Обмен по привязке Reviewer-Run из чужого файла (D-102 §a, D-103 §a).

    Привязка probe-reviewer совпадает только с reviewer.yml@main по
    workflow_run; из openai-wif-test.yml обмен обязан получить invalid_grant.
    Засчитывается ТОЛЬКО если свой обмен (б) в этом же прогоне успешен: иначе
    отказ мог бы быть поломкой запроса, а не привязки. exchange() -> токен.
    """
    if not own_exchange_ok:
        return UNKNOWN, "not judged: own exchange (б) did not succeed in this run"
    try:
        exchange()
    except Exception as exc:
        if error_code(exc) == "invalid_grant":
            return PASS, "exchange for Reviewer-Run refused: " + describe(exc)
        return UNKNOWN, "exchange for Reviewer-Run failed, but not with invalid_grant: " + describe(exc)
    return FAIL, "exchange for Reviewer-Run SUCCEEDED from openai-wif-test.yml: the binding is not limited to reviewer.yml"


def boundary_checks(client, expected):
    """(в), (г), (д) по порядку; результат — список (имя, итог, подробность)."""
    return [
        ("(в) models.list == expected", *check_models(client, expected)),
        ("(г) responses.create allowed model", *check_positive(client)),
        ("(д) responses.create denied model", *check_negative(client)),
    ]
