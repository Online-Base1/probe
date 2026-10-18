"""Автор тестов другого семейства: ввод-вывод вокруг test_author_lib (D-173, D-174).

  test_author.py author — снимок задания → Codex → проверенные файлы тестов.

В конвейер пока НЕ подключён (шаг E, job test-author в agent.yml). Механика —
ревьюера: GitHub/transport, обмен WIF и проверка границы OpenAI, промпт и
формат с одного коммита factory-knowledge, разбор с отказом на дубль ключа.
Своё: сервисный аккаунт автора тестов, его промпт/формат и проверки ответа.

Окружение:
  TASK_FILE, TASK_ARTIFACT — байты снимка и имя артефакта agent-task-<sha256>;
  GH_TOKEN_KNOWLEDGE       — чтение factory-knowledge (тот же, что у ревьюера);
  OPENAI_IDENTITY_PROVIDER_ID, OPENAI_WIF_AUDIENCE — общие с ревьюером;
  OPENAI_TEST_AUTHOR_SERVICE_ACCOUNT_ID — сервисный аккаунт этой роли;
  OUT                      — куда записать проверенный ответ (JSON);
  WRITE_ROOT (необяз.)     — корень рабочей копии: туда пишутся files.

Итог — строка TEST_AUTHOR_RESULT=DONE | UNKNOWN(<причина>). При UNKNOWN не
пишется ничего: ни OUT, ни файлы. Токены не печатаются.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import openai_checks as oc  # noqa: E402
import reviewer as rv  # noqa: E402
import reviewer_lib as rl  # noqa: E402
import test_author_lib as ta  # noqa: E402

SERVICE_ACCOUNT_VAR = "OPENAI_TEST_AUTHOR_SERVICE_ACCOUNT_ID"
BINDING = "Test-Author-Run"
MAX_OUTPUT_TOKENS = 32000


def author(ctx):
    """Возвращает dict: result, value (проверенный ответ или None), prompt_sha, format_sha, model."""
    st = {"result": None, "value": None, "prompt_sha": "", "format_sha": "", "model": oc.REVIEW_MODEL}
    try:
        rl.verify_task(ctx["task_artifact"], ctx["task_bytes"])
        task_text, request_input = ta.build_input(ctx["task_bytes"])
        ta.task_criteria(task_text)            # без строк «- …» модель не зовётся вовсе

        client = ctx["openai_factory"]()
        for name, verdict, detail in oc.boundary_checks(client, oc.load_expected(ctx["expected_models"])):
            print(f"{name}: {verdict} — {detail}")
            if verdict != oc.PASS:
                raise rl.Unknown(f"openai_boundary:{name.split(' ')[0]}={verdict}")

        prompt, schema, prompt_sha, format_sha = rv.fetch_knowledge(
            ctx["gh_knowledge"], ta.PROMPT_PATH, ta.FORMAT_PATH, ta.check_schema_contract)
        st["prompt_sha"], st["format_sha"] = prompt_sha, format_sha
        ctx.setdefault("sent", []).append(request_input)

        r = client.responses.create(
            model=oc.REVIEW_MODEL, instructions=prompt, input=request_input,
            max_output_tokens=MAX_OUTPUT_TOKENS, reasoning={"effort": "medium"},
            text={"format": {"type": "json_schema", "name": "test_author", "schema": schema, "strict": False}})
        tin, tout = oc.usage_tokens(r)
        print(f"response: status={getattr(r, 'status', None)} input_tokens={tin} output_tokens={tout}")
        rl.check_response_meta(getattr(r, "status", None), tin, tout)
        value = ta.parse_and_check(getattr(r, "output_text", None), schema, task_text)
        if ctx.get("write_root"):
            ta.write_files(value, ctx["write_root"])
        st.update(result=rl.DONE, value=value)
    except rl.Unknown as exc:
        st["result"] = rl.result_line(rl.UNKNOWN_KIND, exc.reason)
    return st


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    if cmd != "author":
        print("usage: test_author.py author", file=sys.stderr)
        return 2

    def factory():
        try:
            return rv._openai_factory(SERVICE_ACCOUNT_VAR, BINDING)
        except rl.Unknown:
            raise
        except Exception as exc:
            raise rl.Unknown("openai_client:" + oc.describe(exc)[:120])

    with open(os.environ["TASK_FILE"], "rb") as fh:
        task_bytes = fh.read()
    ctx = {"task_bytes": task_bytes, "task_artifact": os.environ.get("TASK_ARTIFACT", ""),
           "gh_knowledge": rv.GitHub(os.environ.get("GH_TOKEN_KNOWLEDGE", "")),
           "openai_factory": factory, "expected_models": rv.EXPECTED_MODELS,
           "write_root": os.environ.get("WRITE_ROOT", "")}
    st = author(ctx)
    print(f"TEST_AUTHOR_RESULT={st['result']}")
    print(f"PROMPT_SHA={st['prompt_sha'] or 'n/a'} FORMAT_SHA={st['format_sha'] or 'n/a'} MODEL={st['model']}")
    if st["value"] is None:
        print(f"::error::test author: {st['result']} — nothing written")
        return 1
    print("TEST_AUTHOR_SUMMARY " + ta.summary(st["value"]))
    with open(os.environ["OUT"], "x", encoding="utf-8") as fh:
        json.dump(st["value"], fh, ensure_ascii=False, indent=2)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
