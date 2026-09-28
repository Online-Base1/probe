# Ревьюер другого семейства — механика

D-098, D-099, D-101, D-102, D-103. Промпт и формат пишет «Архитектура»; здесь
только механика.

| Файл | Что |
|---|---|
| `openai_checks.py` | (в) список моделей == `expected-models.json`, (г) `gpt-5.3-codex` отвечает, (д) `gpt-4.1-nano` → `model_not_found` |
| `openai_smoke.py` | дымовой тест федерации (`openai-wif-test.yml`) |
| `reviewer_lib.py` | чистая логика: снимок задания, выбор заявки, пробы, белый список запроса, схема, канарейка, итог |
| `reviewer.py` | ввод-вывод: `resolve`, `review`, `report` (`reviewer.yml`) |
| `tests/` | всё без сети: `python3 -m unittest discover -s .github/reviewer/tests` |

## Договор с «Архитектурой» (промпт и схема)

- Промпт: `factory-knowledge@main:prompts/reviewer/prompt.md` (UTF-8) — уходит в `instructions`.
- Схема: `factory-knowledge@main:prompts/reviewer/findings.schema.json`.
  - Верхний уровень — `object` с обязательным массивом `findings`.
  - У находки обязательны `file` (путь в репозитории) и `line` (`integer`, строка в новой версии файла). Текст находки — `message`, `summary` или `title`.
  - Поддерживаемые ключевые слова: `type`, `properties`, `required`, `additionalProperties` (только `false`/`true`), `items`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength`, `minItems`, `maxItems`, плюс `$schema`, `$id`, `title`, `description`. Любое другое слово даёт `UNKNOWN(schema_unsupported)`: не проверенное не считается проверенным.
- Модели передаются только три блока: задание (байты снимка), дифф заявки, статусы гейтов (имя и итог). Описания, заголовка и сообщений коммитов модель не видит.

## Заглушки до ввода

- `vars.FACTORY_REVIEWER_APP_CLIENT_ID` и `secrets.FACTORY_REVIEWER_APP_PRIVATE_KEY` — приложение `online-base1-reviewer`.
- `vars.OPENAI_REVIEWER_SERVICE_ACCOUNT_ID` — привязка `Reviewer-Run`.
- `CANARY_PR` — постоянная черновая заявка `canary/known-defect`; `WRITE_PROBE_ISSUE` — служебная issue «reviewer-write-probe» в `factory-knowledge`. Обе — константы в `reviewer_lib.py`.

Пока заглушки не заменены, `reviewer.yml` и `reviewer-ci / prompt-present` красные. Так и должно быть.
