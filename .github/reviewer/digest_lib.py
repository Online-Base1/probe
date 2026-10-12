"""Ночная сводка (D-121, BB-38): чистая логика без сети.

Сводка отчитывается о НАБЛЮДЕНИИ, а не о наблюдаемом (D-121 §c, §g): сломанный
ревьюер или не запустившийся ночной прогон дают строку «не наблюдалось», а не
пропуск строки и не красную сводку. Девять строк фиксированного порядка
(D-121 §d), рядом — машиночитаемая DIGEST с неизменным порядком полей,
последняя строка — СВОДКА ПОЛНАЯ / СВОДКА НЕПОЛНАЯ.

Поправки к составу: строка ЖУРНАЛ считается по main (D-124 §c.4); строка
ОБХОДЫ — по репозиториям, с признаком, разрешён ли обход (D-129 §c).

Всё, что приходит из сети, передаётся сюда уже полученным (digest.py); то,
что получить не удалось, приходит как Missing(причина). Так каждая строка
гоняется на подделках (tests/test_digest.py).
"""

import datetime
import re

import reviewer_lib as rl

# factory-knowledge#12 «Ночная сводка Online-Base», закреплена (D-121 §b, §f).
# Ни один процесс по этой issue не запускается (условие D-104; тест
# test_no_issue_triggers держит его для probe).
DIGEST_ISSUE = 12

PROBE_REPO = "Online-Base1/probe"
ONLINE_BASE_REPO = "Online-Base1/online-base"
WORKLOG_PATH = "docs/06-worklog"   # D-115 §c; по main (D-124 §c.4)
STANDARDS_PATH = "standards"       # BB-39; по main factory-knowledge
# Обходы — по репозиториям (D-129 §c): ноль значит разное там, где обход
# разрешён, и там, где он невозможен по настройке.
BYPASS_REPOS = (PROBE_REPO, rl.KNOWLEDGE_REPO, ONLINE_BASE_REPO)

WINDOW_HOURS = 24
NOT_OBSERVED = "not_observed"

# Порядок строк и полей DIGEST не меняется: из DIGEST потом наполняется учёт
# (приём REVIEW_LEDGER, D-106 §e).
LINES = (
    ("night", "НОЧЬ"),
    ("reviewer", "РЕВЬЮЕР"),
    ("canary", "КАНАРЕЙКА"),
    ("retention", "СРОК ХРАНЕНИЯ"),
    ("bypass", "ОБХОДЫ"),
    ("prless", "ЗАЯВКИ БЕЗ ВЕТКИ"),
    ("worklog", "ЖУРНАЛ"),
    ("models", "МОДЕЛИ"),
    ("standards", "ПРАВИЛА"),
)
FIELDS_OF = {
    "night": ("runs", "red", "unknown"),
    "reviewer": ("reviewer", "findings"),
    "canary": ("canary",),
    "retention": ("retention", "expires_in"),
    "bypass": ("bypass_24h", "bypass_total"),
    "prless": ("prless_branch",),
    "worklog": ("worklog_age",),
    "models": ("models",),
    "standards": ("standards_age",),
}
DIGEST_FIELDS = ("seq", "date", "runs", "red", "unknown", "reviewer", "findings", "canary", "retention",
                 "expires_in", "bypass_24h", "bypass_total", "prless_branch", "worklog_age", "models",
                 "standards_age", "complete")

RED_CONCLUSIONS = {"failure", "timed_out", "startup_failure", "action_required", "cancelled", "stale"}
MODEL_CHECKS = ("в", "г", "д")

_UPSTREAM = re.compile(r'"run_id": "(\d+)", "trigger": "(\w*)"')
_LEDGER = re.compile(r"REVIEW_LEDGER (\S.*)$", re.M)
_FIELD = re.compile(r"(\w+)=(\S*)")
_MODEL = re.compile(r"\((в|г|д)\) [^:\n]+: (PASS|FAIL|UNKNOWN)\b")


class Missing:
    """Источник не получен; reason — словами, без токенов."""

    def __init__(self, reason):
        self.reason = reason

    def __repr__(self):
        return f"Missing({self.reason!r})"


class NotObserved(Exception):
    def __init__(self, reason):
        super().__init__(reason)
        self.reason = reason


def need(value):
    if isinstance(value, Missing):
        raise NotObserved(value.reason)
    return value


def parse_time(s):
    return datetime.datetime.strptime(s, "%Y-%m-%dT%H:%M:%SZ")


def window(now):
    return now - datetime.timedelta(hours=WINDOW_HOURS), now


def workflow_file(run):
    return (run.get("path") or "").split("@", 1)[0]


# --- разбор журналов ревьюера ---

def upstream_of(log):
    """(run_id, trigger) прогона, по которому работал ревьюер — из вывода resolve."""
    m = _UPSTREAM.search(log or "")
    return (m.group(1), m.group(2)) if m else None


def ledger_of(log):
    """Последняя строка REVIEW_LEDGER журнала как dict; нет строки — None."""
    found = _LEDGER.findall(log or "")
    return dict(_FIELD.findall(found[-1])) if found else None


def model_checks_of(log):
    """Итоги проверок (в)(г)(д) из журнала ревьюера: {'в': 'PASS', ...}."""
    return dict(_MODEL.findall(log or ""))


# --- ночной прогон ---

def nightly(obs):
    """Ночной прогон canary-trigger за окно и журнал ревьюера по нему.

    Ночных прогонов несколько — НЕ выбирается ни один: правило выбора не
    принято, это вопрос к «Архитектуре», и строки, зависящие от ночного
    прогона, честно не наблюдаются.
    """
    runs = need(obs["runs"])
    night = sorted((r for r in runs if workflow_file(r) == rl.CANARY_WORKFLOW_PATH), key=lambda r: r["created_at"])
    if not night:
        raise NotObserved("ночного прогона не было: canary-trigger за окно не запускался")
    if len(night) > 1:
        ids = ", ".join(f"{r['id']} ({r.get('event')})" for r in night)
        raise NotObserved(f"ночных прогонов {len(night)}: {ids}; правило выбора не принято — вопрос к «Архитектуре»")
    cr = night[0]
    unread = []
    for rid, log in sorted(obs["reviewer_logs"].items()):
        if isinstance(log, Missing):
            unread.append(f"{rid}: {log.reason}")
        elif upstream_of(log) == (str(cr["id"]), "canary"):
            return cr, rid, log
    if unread:
        raise NotObserved(f"ревьюер по ночному прогону {cr['id']} не найден; не прочитаны журналы {'; '.join(unread)}")
    raise NotObserved(f"ревьюер по ночному прогону {cr['id']} за окно не отчитался")


def nightly_ledger(obs):
    cr, rid, log = nightly(obs)
    ledger = ledger_of(log)
    if ledger is None:
        raise NotObserved(f"в журнале ревьюера {rid} нет строки REVIEW_LEDGER")
    return cr, rid, log, ledger


# --- девять строк: (текст, поля DIGEST, пробелы) ---

def line_night(obs):
    runs = [r for r in need(obs["runs"]) if str(r["id"]) != str(obs["own_run_id"])]
    red = sum(1 for r in runs if r.get("conclusion") in RED_CONCLUSIONS)
    unfinished = sum(1 for r in runs if r.get("status") != "completed")
    logs = obs["reviewer_logs"]
    unread = [rid for rid, log in logs.items() if isinstance(log, Missing)]
    text = f"прогонов {len(runs)}, красных {red}"
    if unfinished:
        text += f", не завершено {unfinished}"
    if unread:
        reason = f"не прочитаны журналы ревьюера {', '.join(map(str, sorted(unread)))}"
        return text + f", UNKNOWN — не наблюдалось: {reason}", \
            {"runs": len(runs), "red": red, "unknown": NOT_OBSERVED}, [reason]
    unknown = 0
    for log in logs.values():
        ledger = ledger_of(log)
        if ledger and ledger.get("result", "").startswith(rl.UNKNOWN_KIND):
            unknown += 1
    return text + f", UNKNOWN {unknown} (из {len(logs)} прогонов ревьюера)", \
        {"runs": len(runs), "red": red, "unknown": unknown}, []


def line_reviewer(obs):
    cr, rid, _, ledger = nightly_ledger(obs)
    result, findings = ledger.get("result", NOT_OBSERVED), ledger.get("findings", NOT_OBSERVED)
    return f"{result}, находок {findings} (ревьюер {rid} по ночному прогону {cr['id']})", \
        {"reviewer": result, "findings": findings}, []


def line_canary(obs):
    _, rid, _, ledger = nightly_ledger(obs)
    canary = ledger.get("canary", NOT_OBSERVED)
    meaning = {"PASS": "заложенный дефект найден", "FAIL": "заложенный дефект НЕ найден"}.get(canary, "")
    return f"{canary}" + (f" — {meaning}" if meaning else "") + f" (ревьюер {rid})", {"canary": canary}, []


def expires_in(retention, oldest_created, today):
    """Дней до самой ранней даты истечения (D-107): самый старый прогон
    ревьюера + наблюдённая нижняя граница срока. Отрицательное — самая старая
    запись уже за гарантированным сроком и может исчезнуть в любой день."""
    days = int(retention[len("observed="):-1])
    return (parse_time(oldest_created).date() + datetime.timedelta(days=days) - today).days


def line_retention(obs):
    _, rid, _, ledger = nightly_ledger(obs)
    retention = ledger.get("retention")
    if not retention:
        raise NotObserved(f"в REVIEW_LEDGER ревьюера {rid} нет поля retention")
    if not retention.startswith("observed="):
        why = {rl.RETENTION_NOT_OBSERVED: "своего прогона старше N дней ещё нет (D-108)",
               rl.RETENTION_FAILED: "журнал старого прогона не читается — красный (D-108 §c)"}.get(retention, "")
        return f"{retention}" + (f" — {why}" if why else "") + "; дата истечения не считается, пока срок не наблюдён", \
            {"retention": retention, "expires_in": NOT_OBSERVED}, []
    oldest = obs["oldest_reviewer_created"]
    if isinstance(oldest, Missing) or oldest is None:
        reason = oldest.reason if isinstance(oldest, Missing) else "самый старый прогон ревьюера не найден"
        return f"{retention}; до самой ранней даты истечения — не наблюдалось: {reason}", \
            {"retention": retention, "expires_in": NOT_OBSERVED}, [reason]
    n = expires_in(retention, oldest, obs["now"].date())
    return f"{retention}; до самой ранней даты истечения {n} дн. (самый старый прогон ревьюера от {oldest[:10]})", \
        {"retention": retention, "expires_in": n}, []


def short(repo):
    return repo.split("/", 1)[1]


def line_bypass(obs):
    parts, day_f, all_f, gaps = [], [], [], []
    for repo in BYPASS_REPOS:
        b, name = obs["bypass"][repo], short(repo)
        day, total, allowed = b["day"], b["all"], b["allowed"]
        if isinstance(day, Missing) or isinstance(total, Missing):
            reason = (day if isinstance(day, Missing) else total).reason
            parts.append(f"{name}: не наблюдалось: {reason}")
            day_f.append(f"{name}:{NOT_OBSERVED}")
            all_f.append(f"{name}:{NOT_OBSERVED}")
            gaps.append(f"{name}: {reason}")
            continue
        if isinstance(allowed, Missing):
            flag, note = "unknown", f"разрешён ли обход — не наблюдалось: {allowed.reason}"
            gaps.append(f"{name}: {allowed.reason}")
        elif allowed:
            flag, note = "allowed", "обход разрешён настройкой"
        else:
            flag, note = "forbidden", "обход невозможен по настройке — ноль здесь ничего не доказывает"
        parts.append(f"{name}: за сутки {len(day)}, за 30 дней {len(total)}; {note}")
        day_f.append(f"{name}:{len(day)}/{flag}")
        all_f.append(f"{name}:{len(total)}/{flag}")
    return "; ".join(parts), {"bypass_24h": ",".join(day_f), "bypass_total": ",".join(all_f)}, gaps


def line_prless(obs):
    prs = need(obs["open_prs"])
    without, unread = [], []
    for pr in prs:
        head = pr.get("head") or {}
        if (head.get("repo") or {}).get("full_name") != PROBE_REPO:
            without.append(pr["number"])
            continue
        exists = obs["branch_exists"].get(head.get("ref"), Missing("ветка не проверялась"))
        if isinstance(exists, Missing):
            unread.append(f"#{pr['number']}: {exists.reason}")
        elif not exists:
            without.append(pr["number"])
    if unread:
        raise NotObserved("не проверены ветки " + "; ".join(unread))
    listed = f" ({', '.join('#' + str(n) for n in sorted(without))})" if without else ""
    return f"probe: {len(without)} из {len(prs)} открытых{listed}; другие репозитории не наблюдаются", \
        {"prless_branch": len(without)}, []


def age_days(last, today, what):
    last = need(last)
    if last is None:
        raise NotObserved(f"на main нет коммитов в {what}")
    return (today - parse_time(last).date()).days


def line_worklog(obs):
    age = age_days(obs["worklog_last"], obs["now"].date(), WORKLOG_PATH + "/")
    return f"{age} дн. с последней записи в {WORKLOG_PATH}/ (online-base, по main — D-124 §c.4)", \
        {"worklog_age": age}, []


def line_models(obs):
    _, rid, log = nightly(obs)
    checks = model_checks_of(log)
    if set(checks) != set(MODEL_CHECKS):
        raise NotObserved(f"в журнале ревьюера {rid} нет проверок (в)(г)(д): ревью до них не дошло")
    text = ", ".join(f"({k}) {checks[k]}" for k in MODEL_CHECKS)
    value = "PASS" if all(checks[k] == "PASS" for k in MODEL_CHECKS) else ",".join(f"{k}={checks[k]}" for k in MODEL_CHECKS)
    return f"{text} (ревьюер {rid})", {"models": value}, []


def line_standards(obs):
    age = age_days(obs["standards_last"], obs["now"].date(), STANDARDS_PATH + "/")
    return (f"{age} дн. с последнего коммита в {STANDARDS_PATH}/ factory-knowledge@main — косвенно: "
            f"расхождение рабочего дерева владельца отсюда не видно (D-121 §e)"), {"standards_age": age}, []


LINE_FUNCS = {"night": line_night, "reviewer": line_reviewer, "canary": line_canary, "retention": line_retention,
              "bypass": line_bypass, "prless": line_prless, "worklog": line_worklog, "models": line_models,
              "standards": line_standards}


def compute_line(key, obs):
    """Строка всегда есть: невычисленная — «не наблюдалось: <причина>» (BB-28)."""
    try:
        text, fields, gaps = LINE_FUNCS[key](obs)
    except NotObserved as exc:
        text, fields, gaps = f"не наблюдалось: {exc.reason}", {}, [exc.reason]
    except Exception as exc:  # пропуск строки — дефект: ошибка кода тоже печатается
        reason = f"ошибка вычисления {type(exc).__name__}"
        text, fields, gaps = f"не наблюдалось: {reason}", {}, [reason]
    fields = {f: fields.get(f, NOT_OBSERVED) for f in FIELDS_OF[key]}
    return text, fields, gaps


def _value(v):
    return re.sub(r"\s+", "_", str(v)).replace("`", "′") or NOT_OBSERVED


def digest_line(values):
    return " ".join(["DIGEST"] + [f"{k}={_value(values[k])}" for k in DIGEST_FIELDS])


def build(obs, seq):
    """Комментарий сводки → (тело, строка DIGEST, список невычисленных строк)."""
    start, end = window(obs["now"])
    date = end.date().isoformat()
    values = {"seq": seq, "date": date}
    human, incomplete = [], []
    for key, title in LINES:
        text, fields, gaps = compute_line(key, obs)
        values.update(fields)
        human.append(rl.clean(f"{title}: {text}", 900))
        if gaps:
            incomplete.append((key, title))
    values["complete"] = "yes" if not incomplete else "no:" + ",".join(k for k, _ in incomplete)
    dline = digest_line(values)
    last = "СВОДКА ПОЛНАЯ" if not incomplete else "СВОДКА НЕПОЛНАЯ: " + ", ".join(t for _, t in incomplete)
    body = "\n".join([
        f"<!-- factory-digest seq={seq} date={date} -->",
        f"**Ночная сводка {date}** · окно {start:%Y-%m-%dT%H:%MZ} … {end:%Y-%m-%dT%H:%MZ} · прогон сводки {obs['own_run_id']}",
        "",
        "```text",
        *human,
        "",
        dline,
        "```",
        "",
        last,
    ]) + "\n"
    return body, dline, [t for _, t in incomplete]
