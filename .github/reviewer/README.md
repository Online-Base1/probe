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

## Договор с «Архитектурой» (промпт и формат, D-104 §h)

- Промпт: `factory-knowledge@main:prompts/05-review.md` (UTF-8). Он общий для обоих ревьюеров.
- Формат находок: `factory-knowledge@main:standards/findings-format.md`. Модели уходят оба файла (`instructions` = промпт + формат); SHA обоих идут в комментарий и `REVIEW_RECORD`.
- **Предложение для формата:** схема ответа — **ровно один** блок ```` ```json ```` в `findings-format.md`. Ноль или несколько блоков дают `UNKNOWN(format_schema_blocks:N)`.
  - Верхний уровень схемы — `object` с обязательным массивом `findings`.
  - У находки обязательны `file` (путь в репозитории) и `line` (`integer`, строка в новой версии файла). Текст находки — `message`, `summary` или `title`.
  - Поддерживаемые ключевые слова: `type`, `properties`, `required`, `additionalProperties` (только `false`/`true`), `items`, `enum`, `minimum`, `maximum`, `minLength`, `maxLength`, `minItems`, `maxItems`, плюс `$schema`, `$id`, `title`, `description`. Любое другое слово даёт `UNKNOWN(schema_unsupported)`: не проверенное не считается проверенным.
- Модели передаются только три блока: задание (байты снимка), дифф заявки, статусы гейтов (имя и итог). Описания, заголовка и сообщений коммитов модель не видит.

## Канарейка (D-103 §c, D-105)

- Заявка `canary/known-defect` → `canary-base`, черновая. Номер — константа `CANARY_PR`; ветка и база сверяются.
- Дефект: `lib/paginate.ts`, `pageCount = Math.floor(total / pageSize)` вместо `ceil`; тесты только на кратные значения. Успех — находка с `file=lib/paginate.ts` и `line` = строке с `floor` (`CANARY_EXPECTED`). Находка «нет теста на остаток» без этой строки успехом не считается.
- Ключ «уже ревьюили» для канарейки — PR + head SHA + `run_id` прогона `canary-trigger`: иначе со второй ночи пропуск выглядел бы успехом.
- Канарейка доказывает, что путь жив и ревьюер видит очевидное. Она **не** доказывает, что он хорошо ищет дефекты (D-105 §e).

## Заглушки до ввода

- `vars.FACTORY_REVIEWER_APP_CLIENT_ID` и `secrets.FACTORY_REVIEWER_APP_PRIVATE_KEY` — приложение `online-base1-reviewer`.
- `vars.OPENAI_REVIEWER_SERVICE_ACCOUNT_ID` — привязка `Reviewer-Run`.
- `CANARY_PR` — постоянная черновая заявка `canary/known-defect`; `WRITE_PROBE_ISSUE` — служебная issue «reviewer-write-probe» в `factory-knowledge`. Обе — константы в `reviewer_lib.py`.

Пока заглушки не заменены, `reviewer.yml` и `reviewer-ci / prompt-present` красные. Так и должно быть.
