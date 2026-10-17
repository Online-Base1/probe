"""Ночная сводка (D-121, BB-38): чистая логика без сети.

Сводка отчитывается о НАБЛЮДЕНИИ, а не о наблюдаемом (D-121 §c, §g): сломанный
ревьюер или не запустившийся ночной прогон дают строку «не наблюдалось», а не
пропуск строки и не красную сводку. Девять строк фиксированного порядка
(D-121 §d), рядом — машиночитаемая DIGEST с неизменным порядком полей,
последняя строка — СВОДКА ПОЛНАЯ / СВОДКА НЕПОЛНАЯ.

Поправки к составу: строка ЖУРНАЛ считается по main (D-124 §c.4); строка
ОБХОДЫ — по репозиториям, с признаком, разрешён ли обход (D-129 §c); признак
не прочитан — N/unknown, и репозиторий называется в СВОДКА НЕПОЛНАЯ (D-133 b).
Ночь — последний canary-trigger по расписанию; ручные прогоны в ночь не входят
(D-133 c). Окно — от предыдущей сводки до текущей, первая берёт 24 ч (D-133 d).
Строка ИЗМЕНЕНИЕ ПРОВЕРОК — коммиты в .github/** по репозиториям (D-134) в
том же диапазоне от запомненной вершины main, что у ВЛИВАНИЙ (D-138 b).
Строка ВЛИВАНИЯ — вливания в main не владельцем и без заявки (D-137): замена
пробы BB-37 без администраторского права; ОБХОДЫ — другая величина и остаётся.
Диапазон вливаний — от вершины main, запомненной прошлой сводкой (D-138 b), а
не по дате коммиттера; ноль без единого запроса — «(запросов не было)» (D-139).
СРЕДА — сверка среды прогона сводки с environment.lock.json (§18′ п.18, D-143);
КОНТРОЛЬНАЯ — заведомые пробы-отказы в каждом прогоне ревьюера за окно: не
найдены ни в одном — механика извлечения слепа, прогон сводки красный (D-143 §f).
ИСХОДЫ — исход каждого прогона окна (§18′ п.17, D-145): не завершён за срок из
digest-config.json и завершён без вердикта — UNKNOWN, идущий в срок — «идёт»;
источника запросов нет — так и сказано, без нуля (D-139).

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
# Задача-журнал находок ревьюера — probe#50 (D-147 §d); константа живёт в reviewer_lib.
FINDINGS_ISSUE = rl.FINDINGS_ISSUE

PROBE_REPO = "Online-Base1/probe"
ONLINE_BASE_REPO = "Online-Base1/online-base"
FACTORY_CI_REPO = "Online-Base1/factory-ci"
COST_PANEL_REPO = "Online-Base1/cost-panel"
WORKLOG_PATH = "docs/06-worklog"   # D-115 §c; по main (D-124 §c.4)
STANDARDS_PATH = "standards"       # BB-39; по main factory-knowledge
# Обходы — по репозиториям (D-129 §c): ноль значит разное там, где обход
# разрешён, и там, где он невозможен по настройке.
BYPASS_REPOS = (PROBE_REPO, rl.KNOWLEDGE_REPO, ONLINE_BASE_REPO)
# Изменения проверок (.github/**) за окно — по репозиториям (D-134): чьи гейты
# и откуда они берутся (factory-ci). Недоступный токену — «не наблюдалось».
CHECKS_PATH = ".github"
CHECKS_REPOS = (PROBE_REPO, FACTORY_CI_REPO, rl.KNOWLEDGE_REPO, ONLINE_BASE_REPO, COST_PANEL_REPO)
# Вливания в main за окно (D-137): кто влил — по merged_by заявки, а не по
# rule-suites. Владелец — названная константа, а не «кто чаще встречается»;
# её смена — изменение конфигурации: тест test_owner_login_pinned и сама
# строка ВЛИВАНИЯ, которая печатает владельца каждую ночь.
OWNER_LOGIN = "MartynPin"
MERGES_REPOS = CHECKS_REPOS
# Сравнение отдаёт до 250 коммитов; больше — диапазон не наблюдён целиком.
COMPARE_LIMIT = 250
PER_REPO_LINES = {"bypass", "merges", "checks"}

FIRST_WINDOW_HOURS = 24
NOT_OBSERVED = "not_observed"

# Порядок строк и полей DIGEST не меняется: из DIGEST потом наполняется учёт
# (приём REVIEW_LEDGER, D-106 §e).
LINES = (
    ("night", "НОЧЬ"),
    ("reviewer", "РЕВЬЮЕР"),
    ("canary", "КАНАРЕЙКА"),
    ("retention", "СРОК ХРАНЕНИЯ"),
    ("bypass", "ОБХОДЫ"),
    ("merges", "ВЛИВАНИЯ"),
    ("prless", "ЗАЯВКИ БЕЗ ВЕТКИ"),
    ("worklog", "ЖУРНАЛ"),
    ("models", "МОДЕЛИ"),
    ("standards", "ПРАВИЛА"),
    ("checks", "ИЗМЕНЕНИЕ ПРОВЕРОК"),
    ("env", "СРЕДА"),
    ("control", "КОНТРОЛЬНАЯ"),
    ("outcomes", "ИСХОДЫ"),
)
FIELDS_OF = {
    "night": ("runs", "red", "unknown"),
    "reviewer": ("reviewer", "findings"),
    "canary": ("canary",),
    "retention": ("retention", "expires_in"),
    "bypass": ("bypass_24h", "bypass_30d"),
    "prless": ("prless_branch",),
    "worklog": ("worklog_age",),
    "models": ("models",),
    "standards": ("standards_age",),
    "checks": ("checks_changed",),
    "merges": ("merges",),
    "env": ("env",),
    "control": ("control",),
    "outcomes": ("outcomes",),
}
DIGEST_FIELDS = ("seq", "date", "runs", "red", "unknown", "reviewer", "findings", "canary", "retention",
                 "expires_in", "bypass_24h", "bypass_30d", "prless_branch", "worklog_age", "models",
                 "standards_age", "checks_changed", "complete", "merges", "env", "control", "outcomes")

RED_CONCLUSIONS = {"failure", "timed_out", "startup_failure", "action_required", "cancelled", "stale"}
MODEL_CHECKS = ("в", "г", "д")

_UPSTREAM = re.compile(r'"run_id": "(\d+)", "trigger": "(\w*)"')
_LEDGER = re.compile(r"REVIEW_LEDGER (\S.*)$", re.M)
_FIELD = re.compile(r"(\w+)=(\S*)")
_HEADS = re.compile(r"DIGEST_HEADS((?: [\w.-]+=[0-9a-f]{40})*)")
_REFUSAL = re.compile(r"REFUSAL_PROBE name=(\S+) status=(\d+) result=(\w+)")
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


def digest_window(now, own_created, previous):
    """Окно сводки (D-133 d): от предыдущей опубликованной сводки до текущей.

    own_created — время создания своего прогона (конец окна; так окна
    соседних сводок стыкуются без зазора и без перекрытия); previous —
    {id, created_at} предыдущей успешной сводки, None или Missing.
    Первая сводка берёт 24 ч и говорит об этом.
    """
    end = parse_time(own_created) if isinstance(own_created, str) else now
    first = end - datetime.timedelta(hours=FIRST_WINDOW_HOURS)
    if isinstance(previous, Missing):
        return first, end, f"предыдущая сводка не прочитана ({previous.reason}): окно 24 ч"
    if previous is None:
        return first, end, "первая сводка: окно 24 ч"
    return parse_time(previous["created_at"]), end, f"от предыдущей сводки {previous['id']}"


def window_of(obs):
    return digest_window(obs["now"], obs["own_created"], obs["previous_digest"])


def in_window(runs, start, end):
    return [r for r in runs if start <= parse_time(r["created_at"]) < end]


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


def heads_of(log):
    """Вершины main, запомненные сводкой (строка DIGEST_HEADS): {репо: sha}; нет строки — None."""
    found = _HEADS.findall(log or "")
    if not found:
        return None
    return dict(kv.split("=", 1) for kv in found[-1].split())


def heads_line(obs):
    """Вершины main на момент этой сводки — начало диапазона следующей (D-138 b)."""
    tips = [(short(r), obs["merges"][r]["tip"]) for r in MERGES_REPOS]
    return "DIGEST_HEADS" + "".join(f" {name}={sha}" for name, sha in tips if isinstance(sha, str))


# --- ночной прогон ---

def nightly(obs):
    """Ночной прогон и журнал ревьюера по нему → (прогон, ревьюер, журнал, пометка).

    Ночь — то, что происходит без человека (D-133 c): берётся ПОСЛЕДНИЙ
    canary-trigger с событием schedule; ручные прогоны в ночь не входят (их
    видно в строке НОЧЬ). Прогонов по расписанию несколько — множественность
    называется в строке.
    """
    start, end, _ = window_of(obs)
    canary = [r for r in in_window(need(obs["runs"]), start, end) if workflow_file(r) == rl.CANARY_WORKFLOW_PATH]
    night = sorted((r for r in canary if r.get("event") == "schedule"), key=lambda r: r["created_at"])
    if not night:
        manual = len(canary)
        raise NotObserved("прогона по расписанию не было" +
                          (f"; ручных прогонов canary-trigger: {manual} — в ночь не входят" if manual else ""))
    cr = night[-1]
    note = f"прогонов по расписанию: {len(night)}, взят последний {cr['id']}" if len(night) > 1 else ""
    unread = []
    for rid, log in sorted(obs["reviewer_logs"].items()):
        if isinstance(log, Missing):
            unread.append(f"{rid}: {log.reason}")
        elif upstream_of(log) == (str(cr["id"]), "canary"):
            return cr, rid, log, note
    if unread:
        raise NotObserved(f"ревьюер по ночному прогону {cr['id']} не найден; не прочитаны журналы {'; '.join(unread)}")
    raise NotObserved(f"ревьюер по ночному прогону {cr['id']} за окно не отчитался")


def with_note(text, note):
    return f"{text} ({note})" if note else text


def nightly_ledger(obs):
    cr, rid, log, note = nightly(obs)
    ledger = ledger_of(log)
    if ledger is None:
        raise NotObserved(f"в журнале ревьюера {rid} нет строки REVIEW_LEDGER")
    return cr, rid, ledger, note


# --- девять строк: (текст, поля DIGEST, пробелы) ---

def line_night(obs):
    start, end, _ = window_of(obs)
    runs = [r for r in in_window(need(obs["runs"]), start, end) if str(r["id"]) != str(obs["own_run_id"])]
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
    cr, rid, ledger, note = nightly_ledger(obs)
    result, findings = ledger.get("result", NOT_OBSERVED), ledger.get("findings", NOT_OBSERVED)
    return with_note(f"{result}, находок {findings} (ревьюер {rid} по ночному прогону {cr['id']})", note), \
        {"reviewer": result, "findings": findings}, []


def line_canary(obs):
    _, rid, ledger, note = nightly_ledger(obs)
    canary = ledger.get("canary", NOT_OBSERVED)
    meaning = {"PASS": "заложенный дефект найден", "FAIL": "заложенный дефект НЕ найден"}.get(canary, "")
    return with_note(f"{canary}" + (f" — {meaning}" if meaning else "") + f" (ревьюер {rid})", note), \
        {"canary": canary}, []


def expires_in(retention, oldest_created, today):
    """Дней до самой ранней даты истечения (D-107): самый старый прогон
    ревьюера + наблюдённая нижняя граница срока. Отрицательное — самая старая
    запись уже за гарантированным сроком и может исчезнуть в любой день."""
    days = int(retention[len("observed="):-1])
    return (parse_time(oldest_created).date() + datetime.timedelta(days=days) - today).days


def line_retention(obs):
    _, rid, ledger, note = nightly_ledger(obs)
    retention = ledger.get("retention")
    if not retention:
        raise NotObserved(f"в REVIEW_LEDGER ревьюера {rid} нет поля retention")
    if not retention.startswith("observed="):
        why = {rl.RETENTION_NOT_OBSERVED: "своего прогона старше N дней ещё нет (D-108)",
               rl.RETENTION_FAILED: "журнал старого прогона не читается — красный (D-108 §c)"}.get(retention, "")
        return with_note(f"{retention}" + (f" — {why}" if why else "") +
                         "; дата истечения не считается, пока срок не наблюдён", note), \
            {"retention": retention, "expires_in": NOT_OBSERVED}, []
    oldest = obs["oldest_reviewer_created"]
    if isinstance(oldest, Missing) or oldest is None:
        reason = oldest.reason if isinstance(oldest, Missing) else "самый старый прогон ревьюера не найден"
        return with_note(f"{retention}; до самой ранней даты истечения — не наблюдалось: {reason}", note), \
            {"retention": retention, "expires_in": NOT_OBSERVED}, [reason]
    n = expires_in(retention, oldest, obs["now"].date())
    return with_note(f"{retention}; до самой ранней даты истечения {n} дн. "
                     f"(самый старый прогон ревьюера от {oldest[:10]})", note), \
        {"retention": retention, "expires_in": n}, []


def short(repo):
    return repo.split("/", 1)[1]


def line_bypass(obs):
    """По репозиториям (D-129 §c, D-133 b). Число и признак — разные величины:
    число не вычислено — репозиторий «не наблюдалось»; число есть, признак не
    прочитан — N/unknown. В обоих случаях репозиторий — пробел сводки:
    unknown — долг, а не нормальное состояние."""
    parts, day_f, all_f, gaps = [], [], [], []
    for repo in BYPASS_REPOS:
        b, name = obs["bypass"][repo], short(repo)
        day, total, allowed = b["day"], b["all"], b["allowed"]
        if isinstance(day, Missing) or isinstance(total, Missing):
            reason = (day if isinstance(day, Missing) else total).reason
            parts.append(f"{name}: не наблюдалось: {reason}")
            day_f.append(f"{name}:{NOT_OBSERVED}")
            all_f.append(f"{name}:{NOT_OBSERVED}")
            gaps.append(name)
            continue
        if isinstance(allowed, Missing):
            flag, note = "unknown", f"разрешён ли обход — не наблюдалось: {allowed.reason}"
            gaps.append(name)
        elif allowed:
            flag, note = "allowed", "обход разрешён настройкой"
        else:
            flag, note = "forbidden", "обход невозможен по настройке — ноль здесь ничего не доказывает"
        parts.append(f"{name}: за сутки {len(day)}, за 30 дней {len(total)}; {note}")
        day_f.append(f"{name}:{len(day)}/{flag}")
        all_f.append(f"{name}:{len(total)}/{flag}")
    return "; ".join(parts), {"bypass_24h": ",".join(day_f), "bypass_30d": ",".join(all_f)}, gaps


def merge_verdict(sha, pulls, pull_detail):
    """Как коммит попал в main (D-137 §b) → ("owner"|"not_owner"|"no_pr", кто).

    pulls — заявки, связанные с коммитом (commits/{sha}/pulls); pull_detail(n) —
    заявка целиком (merged_by есть только в ней) или Missing. Заявка, которой
    коммит влит, — та, чей merge_commit_sha равен коммиту; иначе влитая в main.
    Ни одной влитой — «без заявки»: прямой push в main закрыт защитой, его
    появление само по себе событие. merged_by не прочитался — NotObserved.
    """
    merged = [p for p in pulls if p.get("merged_at") and (p.get("base") or {}).get("ref") == "main"]
    if not merged:
        return "no_pr", None
    own = [p for p in merged if p.get("merge_commit_sha") == sha] or merged
    detail = pull_detail(own[0]["number"])
    if isinstance(detail, Missing):
        raise NotObserved(f"заявка #{own[0]['number']} коммита {sha[:7]}: {detail.reason}")
    login = (detail.get("merged_by") or {}).get("login")
    if not login:
        raise NotObserved(f"у заявки #{own[0]['number']} коммита {sha[:7]} merged_by пуст")
    return ("owner" if login == OWNER_LOGIN else "not_owner"), login


def merges_range(name, m):
    """Коммиты, появившиеся в main с прошлой сводки (D-138 b) → (коммиты, пометка).

    Начало — вершина, запомненная прошлой сводкой; нет её (первая сводка с
    запомненной вершиной) — начало = текущая вершина, коммитов нет, и это
    сказано. История main не продолжает запомненную вершину — КРАСНЫЙ и
    «не наблюдалось»: диапазон не определён.
    """
    tip = need(m["tip"])
    base = m["base"]
    if isinstance(base, Missing):
        raise NotObserved(f"предыдущая вершина не прочитана: {base.reason}")
    if base is None:
        return [], f"запросов не было: начало диапазона — текущая вершина {tip[:7]}, первая сводка с запомненной вершиной"
    if base == tip:
        return [], "запросов не было"
    cmp = need(m["compare"])
    if cmp.get("status") != "ahead":
        raise NotObserved(f"КРАСНЫЙ: история main не продолжает запомненную вершину {base[:7]} "
                          f"(compare {base[:7]}...{tip[:7]}: {cmp.get('status')})")
    commits = cmp.get("commits") or []
    total = cmp.get("total_commits", len(commits))
    if total > len(commits):
        raise NotObserved(f"в диапазоне {base[:7]}...{tip[:7]} коммитов {total}, получено {len(commits)}")
    return commits, ("" if commits else "запросов не было")


def line_merges(obs):
    """<репозиторий>:<всего>/<не владельцем>/<без заявки> (D-137 §c). Не владельцем
    или без заявки — КРАСНЫЙ с перечнем коммитов; merged_by не прочитался —
    репозиторий «не наблюдалось» и пробел сводки. Факт обнаруживается ПОСЛЕ
    вливания: это наблюдение, не доказательство невозможности (D-137 §e).
    Ноль, полученный без единого запроса о заявках, так и называется (D-139)."""
    parts, fields, gaps = [], [], []
    for repo in MERGES_REPOS:
        m, name = obs["merges"][repo], short(repo)
        try:
            commits, note = merges_range(name, m)
            verdicts = []
            for c in commits:
                pulls = m["pulls"].get(c["sha"], Missing("не запрошены"))
                if isinstance(pulls, Missing):
                    raise NotObserved(f"заявки коммита {c['sha'][:7]}: {pulls.reason}")
                verdicts.append((c["sha"], *merge_verdict(c["sha"], pulls, m["pull_detail"])))
        except NotObserved as exc:
            parts.append(f"{name}: не наблюдалось: {exc.reason}")
            fields.append(f"{name}:{NOT_OBSERVED}")
            gaps.append(name)
            continue
        not_owner = [(s, who) for s, v, who in verdicts if v == "not_owner"]
        no_pr = [s for s, v, _ in verdicts if v == "no_pr"]
        text = f"{name}: {len(verdicts)}/{len(not_owner)}/{len(no_pr)}" + (f" ({note})" if note else "")
        red = [f"{s[:7]} без заявки" for s in no_pr] + [f"{s[:7]} влил {who}" for s, who in not_owner]
        if red:
            text += " КРАСНЫЙ: " + ", ".join(red)
        parts.append(text)
        fields.append(f"{name}:{len(verdicts)}/{len(not_owner)}/{len(no_pr)}")
    return (f"всего/не владельцем/без заявки, владелец {OWNER_LOGIN} — " + "; ".join(parts),
            {"merges": ",".join(fields)}, gaps)


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
    _, rid, log, note = nightly(obs)
    checks = model_checks_of(log)
    if set(checks) != set(MODEL_CHECKS):
        raise NotObserved(f"в журнале ревьюера {rid} нет проверок (в)(г)(д): ревью до них не дошло")
    text = ", ".join(f"({k}) {checks[k]}" for k in MODEL_CHECKS)
    value = "PASS" if all(checks[k] == "PASS" for k in MODEL_CHECKS) else ",".join(f"{k}={checks[k]}" for k in MODEL_CHECKS)
    return with_note(f"{text} (ревьюер {rid})", note), {"models": value}, []


def line_standards(obs):
    age = age_days(obs["standards_last"], obs["now"].date(), STANDARDS_PATH + "/")
    return (f"{age} дн. с последнего коммита в {STANDARDS_PATH}/ на main factory-knowledge — косвенно: "
            f"расхождение рабочего дерева владельца отсюда не видно (D-121 §e)"), {"standards_age": age}, []


def touches_checks(files):
    return any(f == CHECKS_PATH or f.startswith(CHECKS_PATH + "/") for f in files)


def line_checks(obs):
    """Коммиты, затронувшие .github/**, среди появившихся в main с прошлой сводки
    (тот же диапазон, что у ВЛИВАНИЙ, D-138 b; не по дате коммиттера), по
    репозиториям (D-134): отказа за ними нет, есть заметность — здесь и в
    блоке «Изменение проверок» гейта. Файлы коммита не прочитались — «не наблюдалось»."""
    parts, fields, gaps = [], [], []
    for repo in CHECKS_REPOS:
        name, files = short(repo), obs["checks"][repo]
        try:
            commits, note = merges_range(name, obs["merges"][repo])
            touched = []
            for c in commits:
                f = files.get(c["sha"], Missing("не запрошены"))
                if isinstance(f, Missing):
                    raise NotObserved(f"файлы коммита {c['sha'][:7]}: {f.reason}")
                if touches_checks(f):
                    touched.append(c["sha"])
        except NotObserved as exc:
            parts.append(f"{name}: не наблюдалось: {exc.reason}")
            fields.append(f"{name}:{NOT_OBSERVED}")
            gaps.append(name)
            continue
        listed = f" ({', '.join(s[:7] for s in touched)})" if touched else ""
        parts.append(f"{name}: {len(touched)}{listed}" + (f" ({note})" if note else ""))
        fields.append(f"{name}:{len(touched)}")
    return "коммитов в .github/ на main — " + "; ".join(parts), {"checks_changed": ",".join(fields)}, gaps


LOCK_NAME = ".github/environment.lock.json"
# Job контрольной в reviewer.yml (§18′ п.18, D-143 §f): прогон без него — до
# введения контрольной, а не слепота механики.
CONTROL_JOB = "refusal-probes"


def line_env(obs):
    """Среда прогона сводки против environment.lock.json (§18′ п.18, D-143 §d)."""
    r = need(obs["env_check"])
    status = r.get("status")
    items = ", ".join(map(str, r.get("unproven_items") or []))
    if status == "match":
        c = r["checked"]
        image = c["image_version"]["actual"]
        return (f"совпадает с {LOCK_NAME}: образ {image}, ImageOS {c['image_os']['actual']}, "
                f"python3 {c['python3']['actual']}"), {"env": f"match@{image}"}, []
    if status in ("drift", "red"):
        changes = "; ".join(f"{d['field']} {d['expected']} → {d['actual']}" for d in r["red"] + r["diffs"])
        unread = f"; не прочитано: {', '.join(r['unread'])}" if r.get("unread") else ""
        return (("КРАСНЫЙ: " if status == "red" else "") + f"отличается от {LOCK_NAME}: {changes}{unread}; "
                f"доказанность пунктов §18′ {items} снята"), \
            {"env": f"{status}:" + "+".join(d["field"] for d in r["red"] + r["diffs"])}, []
    if status == "unknown":
        raise NotObserved(f"не прочитано: {', '.join(r.get('unread') or [])}; доказанность пунктов §18′ {items} не подтверждена")
    raise NotObserved(f"{r.get('reason') or 'статус сверки ' + str(status)}; доказанность пунктов §18′ {items} не подтверждена")


def refusals_of(log):
    """Строки REFUSAL_PROBE журнала: [(имя, статус, исход)]."""
    return _REFUSAL.findall(log or "")


def line_control(obs):
    """Положительная контрольная (D-143 §f): в каждом прогоне ревьюера за окно —
    заведомая проба-отказ в журнале. Ни в одном — механика слепа: blind, прогон
    сводки красный (иначе её устойчивый ноль неотличим от отсутствия событий,
    D-139). Проба, НЕ получившая отказ, — КРАСНЫЙ в строке."""
    logs, jobs = obs["reviewer_logs"], obs["reviewer_jobs"]
    # Пустой словарь журналов при непрочитанном списке прогонов — «не вычислено»,
    # а не «прогонов не было» (§18′ п.17, D-145 §d).
    need(obs["runs"])
    if not logs:
        raise NotObserved("прогонов ревьюера за окно не было — контрольной нечего показать")
    found, missing, before, unread, allowed = [], [], [], [], []
    for rid in sorted(logs):
        log, names = logs[rid], jobs.get(rid, Missing("задания прогона не запрошены"))
        if isinstance(log, Missing) or isinstance(names, Missing):
            unread.append(f"{rid}: {(log if isinstance(log, Missing) else names).reason}")
            continue
        if CONTROL_JOB not in names:
            before.append(str(rid))
            continue
        probes = refusals_of(log)
        allowed += [f"{rid} {n} {s} {res}" for n, s, res in probes if res != "refused"]
        (found if any(res == "refused" for _, _, res in probes) else missing).append(str(rid))
    considered = len(found) + len(missing)
    notes = []
    if before:
        notes.append(f"до введения контрольной (нет job {CONTROL_JOB}): {', '.join(before)}")
    if unread:
        notes.append("не прочитаны: " + "; ".join(unread))
    if allowed:
        notes.append("КРАСНЫЙ: проба не получила отказ — " + ", ".join(allowed))
    tail = ("; " + "; ".join(notes)) if notes else ""
    if not considered:
        raise NotObserved("контрольная не проверялась ни в одном прогоне" + tail)
    if not found:
        return (f"КРАСНЫЙ: механика извлечения отказов слепа — заведомая проба-отказ не найдена ни в одном "
                f"из {considered} прогонов ревьюера ({', '.join(missing)}){tail}"), \
            {"control": f"blind:0/{considered}"}, []
    if missing or unread:
        return (f"проба-отказ найдена в {len(found)} из {considered} прогонов ревьюера; не найдена: "
                f"{', '.join(missing) or '—'}{tail}"), {"control": f"partial:{len(found)}/{considered}"}, \
            ["не во всех прогонах"]
    return (f"проба-отказ найдена во всех {considered} прогонах ревьюера ({', '.join(found)}){tail}"), \
        {"control": f"ok:{len(found)}/{considered}"}, []


# --- ИСХОДЫ (§18′ п.17, D-145): UNKNOWN выглядит как UNKNOWN ---

CONFIG_NAME = ".github/reviewer/digest-config.json"
REVIEWER_WORKFLOW_PATH = ".github/workflows/" + rl.REVIEWER_WORKFLOW_FILE
DEADLINE_FIELD = "run_deadline_minutes"
CI_WORKFLOW_PATH = ".github/workflows/ci.yml"
# Вердикт гейтов — job verdict вызова gates.yml; сработал — дал success или failure.
CI_VERDICT_JOB = "gates / verdict"
VERDICT_FIRED = {"success", "failure"}
# Незавершённые прогоны читаются и вне окна: прогон, начатый до окна и не
# закончившийся, иначе пропал бы из отчёта, не став UNKNOWN.
UNFINISHED_STATUSES = ("queued", "in_progress", "waiting", "requested", "pending")
OUTCOME_STATES = ("done", "running", "timeout", "noverdict", "unread")


def deadline_of(config):
    """Срок завершения прогона в минутах из digest-config.json (D-145 §e) или NotObserved."""
    if isinstance(config, Missing):
        raise NotObserved(f"срок не задан: {config.reason}")
    if not isinstance(config, dict):
        raise NotObserved(f"срок не задан: {CONFIG_NAME} — не объект")
    if DEADLINE_FIELD not in config:
        raise NotObserved(f"срок не задан: в {CONFIG_NAME} нет поля {DEADLINE_FIELD}")
    value = config[DEADLINE_FIELD]
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
        raise NotObserved(f"срок не задан: {DEADLINE_FIELD}={value!r} — не положительное число")
    return value


def verdict_fired(run, reviewer_logs, ci_jobs):
    """Сработал ли вердикт завершённого прогона → True | False | Missing.

    Ревьюер — строка REVIEW_LEDGER в журнале с исходом не UNKNOWN(...): прогон
    с result=UNKNOWN(format_missing) и т.п. вердикта не дал (D-144 §b, D-145
    §c.3); ci.yml — job «gates / verdict» с исходом success/failure; прочие
    потоки вердиктом считают сам conclusion прогона.
    """
    wf = workflow_file(run)
    if wf == REVIEWER_WORKFLOW_PATH:
        log = reviewer_logs.get(run["id"], Missing("журнал ревьюера не запрошен"))
        if isinstance(log, Missing):
            return log
        ledger = ledger_of(log)
        return ledger is not None and not ledger.get("result", rl.UNKNOWN_KIND).startswith(rl.UNKNOWN_KIND)
    if wf == CI_WORKFLOW_PATH:
        jobs = ci_jobs.get(run["id"], Missing("задания гейтов не запрошены"))
        if isinstance(jobs, Missing):
            return jobs
        return any(j.get("name") == CI_VERDICT_JOB and j.get("conclusion") in VERDICT_FIRED for j in jobs)
    return run.get("conclusion") is not None


def classify_run(run, now, deadline, no_deadline, reviewer_logs, ci_jobs):
    """Ровно одно состояние прогона → (состояние, причина).

    done — завершён и исход есть; running — не завершён, срок не истёк (это не
    UNKNOWN); timeout — не завершён, срок истёк (прошло не меньше срока: на
    границе срок уже истёк); noverdict — завершён, вердикт не сработал;
    unread — состояние не вычислено (нет срока, журнал или задания не прочитаны).
    """
    if run.get("status") != "completed":
        if deadline is None:
            return "unread", no_deadline
        started = parse_time(run.get("run_started_at") or run["created_at"])
        if now - started >= datetime.timedelta(minutes=deadline):
            return "timeout", ""
        return "running", ""
    fired = verdict_fired(run, reviewer_logs, ci_jobs)
    if isinstance(fired, Missing):
        return "unread", fired.reason
    return ("done", "") if fired else ("noverdict", "")


def match_requests(requests, request_runs, now, deadline):
    """Сверка «запрос → прогон» (§18′ п.17, случай 1) → None | dict.

    requests — записи источника запросов: {id, requested_at, run_id|None};
    None — источника нет (пульта нет, п.3): тогда и ответа нет, не ноль
    (D-139). request_runs — {run_id: прогон | None (нет такого) | Missing}.
    Запрос без run_id сопоставить нельзя: площадка отдаёт идентификатор на
    workflow_dispatch только по return_run_details, и источник обязан его хранить.
    """
    if requests is None:
        return None
    if isinstance(requests, Missing):
        raise NotObserved(f"источник запросов не прочитан: {requests.reason}")
    out = {"matched": [], "waiting": [], "lost": [], "noref": [], "unread": []}
    for q in requests:
        ref = q.get("run_id")
        if ref is None:
            out["noref"].append(str(q["id"]))
            continue
        found = request_runs.get(str(ref), Missing("прогон запроса не запрошен"))
        if isinstance(found, Missing):
            out["unread"].append(f"{q['id']}: {found.reason}")
        elif found is not None:
            out["matched"].append(str(q["id"]))
        elif deadline is None:
            out["unread"].append(f"{q['id']}: срок не задан")
        elif now - parse_time(q["requested_at"]) >= datetime.timedelta(minutes=deadline):
            out["lost"].append(str(q["id"]))
        else:
            out["waiting"].append(str(q["id"]))
    return out


def ids(items):
    return f" ({', '.join(items)})" if items else ""


def line_outcomes(obs):
    """Исход каждого прогона окна (D-145 §c–§e). Вычисляется всегда: ни от ночи,
    ни от ревьюера не зависит (D-144 §a). Источника запросов нет — так и
    печатается, без «0 потерянных» (D-139, D-145 §d)."""
    start, end, _ = window_of(obs)
    runs = need(obs["runs"])
    pool = {str(r["id"]): r for r in in_window(runs, start, end)}
    gaps = []
    unfinished = obs["unfinished_runs"]
    if isinstance(unfinished, Missing):
        gaps.append(f"незавершённые прогоны до окна не прочитаны: {unfinished.reason}")
    else:
        for r in unfinished:
            pool.setdefault(str(r["id"]), r)
    pool.pop(str(obs["own_run_id"]), None)
    try:
        deadline, no_deadline = deadline_of(obs["digest_config"]), ""
    except NotObserved as exc:
        deadline, no_deadline = None, exc.reason
        gaps.append(no_deadline)
    buckets = {s: [] for s in OUTCOME_STATES}
    for rid in sorted(pool):
        state, reason = classify_run(pool[rid], obs["now"], deadline, no_deadline,
                                     obs["reviewer_logs"], obs["ci_jobs"])
        buckets[state].append(f"{rid}: {reason}" if reason else rid)
    if buckets["unread"]:
        gaps.append("не вычислено: " + "; ".join(buckets["unread"]))
    req = match_requests(obs["requests"], obs["request_runs"], obs["now"], deadline)
    if req is None:
        req_text, req_field = ("запросы: источника нет — пульта нет (§18′ п.3), сверка запрос→прогон "
                               "не выполнялась"), "no_source"
    else:
        req_text = (f"запросы: сопоставлено {len(req['matched'])}, ожидают {len(req['waiting'])}, "
                    + (f"UNKNOWN(запрос без прогона) {len(req['lost'])}{ids(req['lost'])}" if req["lost"]
                       else "без прогона 0") + ", "
                    + (f"UNKNOWN(запрос без run_ref) {len(req['noref'])}{ids(req['noref'])}" if req["noref"]
                       else "без run_ref 0"))
        if req["unread"]:
            req_text += ", не вычислено " + "; ".join(req["unread"])
            gaps.append("запросы не вычислены: " + "; ".join(req["unread"]))
        req_field = "/".join(f"{k}={len(req[k])}" for k in ("matched", "waiting", "lost", "noref", "unread"))
    due = f"срок {deadline:g} мин ({CONFIG_NAME})" if deadline is not None else no_deadline
    b = buckets
    # Слово UNKNOWN — только при ненулевом счёте: ноль печатается словами,
    # иначе благополучная ночь выглядела бы как тревога, и наоборот (D-145 §b).
    def unknown(_, items, label, zero):
        return f"UNKNOWN({label}) {len(items)}{ids(items)}" if items else zero
    text = (f"завершено с исходом {len(b['done'])}; идёт {len(b['running'])}{ids(b['running'])}; "
            + unknown(0, b["timeout"], "не завершён за срок", "не завершённых за срок 0") + "; "
            + unknown(0, b["noverdict"], "вердикт не сработал", "без вердикта 0")
            + (f"; не вычислено {len(b['unread'])}{ids(b['unread'])}" if b["unread"] else "")
            + f"; {due}; {req_text}")
    unknown = b["timeout"] or b["noverdict"] or (req is not None and (req["lost"] or req["noref"]))
    state = "UNKNOWN" if unknown else NOT_OBSERVED if gaps else "ok"
    field = (f"{state}:" + ",".join(f"{s}={len(b[s])}" for s in OUTCOME_STATES) + f",requests={req_field}")
    return text, {"outcomes": field}, gaps


LINE_FUNCS = {"night": line_night, "reviewer": line_reviewer, "canary": line_canary, "retention": line_retention,
              "bypass": line_bypass, "prless": line_prless, "worklog": line_worklog, "models": line_models,
              "standards": line_standards, "checks": line_checks, "merges": line_merges,
              "env": line_env, "control": line_control, "outcomes": line_outcomes}


def compute_line(key, obs):
    """Строка всегда есть: невычисленная — «не наблюдалось: <причина>» (BB-28).

    → (текст, поля, пробелы, репозитории-пробелы). Для строк по репозиториям
    пробел — имя репозитория: он называется в СВОДКА НЕПОЛНАЯ (D-133 b).
    """
    try:
        text, fields, gaps = LINE_FUNCS[key](obs)
        repos = gaps if key in PER_REPO_LINES else []
    except NotObserved as exc:
        text, fields, gaps, repos = f"не наблюдалось: {exc.reason}", {}, [exc.reason], []
    except Exception as exc:  # пропуск строки — дефект: ошибка кода тоже печатается
        reason = f"ошибка вычисления {type(exc).__name__}"
        text, fields, gaps, repos = f"не наблюдалось: {reason}", {}, [reason], []
    fields = {f: fields.get(f, NOT_OBSERVED) for f in FIELDS_OF[key]}
    return text, fields, gaps, repos


def _value(v):
    return re.sub(r"\s+", "_", str(v)).replace("`", "′") or NOT_OBSERVED


def digest_line(values):
    return " ".join(["DIGEST"] + [f"{k}={_value(values[k])}" for k in DIGEST_FIELDS])


def build(obs, seq):
    """Комментарий сводки → (тело, строка DIGEST, перечень невычисленного)."""
    start, end, note = window_of(obs)
    date = end.date().isoformat()
    values = {"seq": seq, "date": date}
    human, incomplete = [], []
    for key, title in LINES:
        text, fields, gaps, repos = compute_line(key, obs)
        values.update(fields)
        human.append(rl.clean(f"{title}: {text}", 1200))
        if gaps:
            incomplete.append((key, title, repos))
    values["complete"] = "yes" if not incomplete else "no:" + ",".join(
        k + (f"({'+'.join(r)})" if r else "") for k, _, r in incomplete)
    dline = digest_line(values)
    labels = [t + (f" ({', '.join(r)})" if r else "") for _, t, r in incomplete]
    last = "СВОДКА ПОЛНАЯ" if not incomplete else "СВОДКА НЕПОЛНАЯ: " + ", ".join(labels)
    body = "\n".join([
        f"<!-- factory-digest seq={seq} date={date} -->",
        f"<!-- {heads_line(obs)} -->",
        f"**Ночная сводка {date}** · окно {start:%Y-%m-%dT%H:%MZ} … {end:%Y-%m-%dT%H:%MZ} ({note}) · "
        f"прогон сводки {obs['own_run_id']}",
        "",
        "```text",
        *human,
        "",
        dline,
        "```",
        "",
        last,
    ]) + "\n"
    return body, dline, labels
