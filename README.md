# Шаблон next-app

Дата сборки: 2026-09-28

Веб-приложение с базой данных. Next.js (App Router) + Prisma + Vitest +
Playwright.

Разворачивается: `factory-knowledge/bin/new-project next-app <имя>`

Что даёт шаблон поверх `create-next-app`:

- `scripts/preflight.sh` и `scripts/gates.sh` — гейты с тремя состояниями;
- `prisma/schema.prisma` с datasource и без моделей;
- `lib/prisma.ts` — единственный клиент на процесс;
- `vitest.config.mts` (расширение `.mts` намеренно: `.ts` даёт
  ESM-в-CJS предупреждение);
- `playwright.config.ts`;
- `CLAUDE.md` с зонами ответственности;
- пины версий и allowlist install-скриптов;
- `security-baseline.json` — снимок `npm audit` на момент создания.

## Локальный запуск

Установка зависимостей:

```bash
npm install
```

Запуск приложения в режиме разработки:

```bash
npm run dev
```

Запуск unit-тестов:

```bash
npm run test:unit
```

Запуск e2e-тестов:

```bash
npm run test:e2e
```

Запуск линтера:

```bash
npm run lint
```
