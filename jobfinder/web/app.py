"""Web UI: feed (A), triage (C), sources & settings (D)."""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode, urlsplit

import nh3
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from .. import collector, db, scheduler
from ..models import STATUSES
from ..search import SECTIONS, SearchParams, count_sections, search_jobs
from ..sources import REGISTRY

HERE = Path(__file__).parent
LIST_LIMIT = 200
MAX_FRESH_DAYS = 3650

SOURCE_LABELS = {
    "himalayas": "Himalayas", "remoteok": "RemoteOK", "jobicy": "Jobicy",
    "workingnomads": "Working Nomads", "wwr": "We Work Remotely",
    "remotefirst": "Remote First Jobs", "hn": "HN Who is hiring", "arc": "Arc",
    "rocketship": "Rocketship", "hirify": "Hirify", "hh": "hh.ru", "habr": "Хабр Карьера",
    "getmatch": "Getmatch",
}
SECTION_LABELS = {"feed": "Лента", "mine": "Мои", "archive": "Архив", "hidden": "Скрытые"}
SCOPE_OPTIONS = [("worldwide", "Весь мир"), ("cis", "СНГ"),
                 ("countries", "Страны, где есть твоя"), ("unknown", "Не указано (уточнить)")]
LANG_OPTIONS = [("ru", "RU"), ("en", "EN")]
LANG_LABELS = {"ru": "Русский", "en": "Английский"}
FRESH_OPTIONS = [(1, "За сутки"), (3, "За 3 дня"), (7, "За неделю"), (30, "За месяц")]
STATUS_LABELS = {"new": "Новая", "seen": "Посмотрел", "interesting": "Интересно",
                 "applied": "Откликнулся", "rejected": "Не подходит"}
STATUS_BUTTONS = ("seen", "interesting", "applied", "rejected")
HIDDEN_LABELS = {"hybrid": "гибрид", "office": "офис", "non_it": "не IT",
                 "restricted": "не для твоей страны"}
CURRENCY = {"USD": ("$", ""), "EUR": ("€", ""), "GBP": ("£", ""),
            "RUB": ("", " ₽"), "KZT": ("", " ₸")}
PERIODS = {"month": " / мес", "year": " / год", "hour": " / час"}


# --- security helpers ---------------------------------------------------------

LOCAL_HOSTS = {"127.0.0.1", "localhost", "testserver"}
_DEFAULT_PORTS = {"http": 80, "https": 443}


def safe_url(url: str | None) -> str | None:
    """Only http(s) URLs may become links (no javascript:, data:, …)."""
    url = (url or "").strip()
    return url if urlsplit(url).scheme.lower() in ("http", "https") else None


def origin_allowed(request: Request, origin: str) -> bool:
    """Origin/Referer must be this local app: a local host name on the port we serve.

    The Host header is not trusted for the name (DNS rebinding sends Host: evil.example).
    """
    try:
        o = urlsplit(origin)
        o_port = o.port or _DEFAULT_PORTS.get(o.scheme)
        h = urlsplit("//" + request.headers.get("host", ""))
        h_port = h.port or _DEFAULT_PORTS.get(request.url.scheme)
    except ValueError:  # malformed port
        return False
    return (o.scheme in _DEFAULT_PORTS and o.hostname in LOCAL_HOSTS
            and h.hostname in LOCAL_HOSTS and o_port == h_port)


def require_same_origin(request: Request) -> None:
    """CSRF guard for state-changing routes: a browser request from another site → 403.

    Requests without Origin and Referer (curl, CLI) are allowed.
    """
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin is not None and not origin_allowed(request, origin):
        raise HTTPException(403, "Запрос с чужого сайта отклонён")


# --- helpers used by templates ----------------------------------------------

def review_links(company: str) -> list[dict]:
    q = quote(company or "", safe="")
    tail = "+" + quote("отзывы") + "+" + quote("сотрудников")
    return [
        {"label": "Glassdoor", "hint": "отзывы и зарплаты",
         "href": f"https://www.glassdoor.com/Search/results.htm?keyword={q}"},
        {"label": "Dreamjob", "hint": "отзывы СНГ",
         "href": f"https://dreamjob.ru/search?query={q}"},
        {"label": "Хабр Карьера", "hint": "оценки компаний",
         "href": f"https://career.habr.com/companies?q={q}"},
        {"label": "Google", "hint": "«отзывы сотрудников»",
         "href": f"https://www.google.com/search?q={q}{tail}"},
        {"label": "Reddit", "hint": "обсуждения", "href": f"https://www.reddit.com/search/?q={q}"},
    ]


def source_label(name: str | None) -> str:
    return SOURCE_LABELS.get(name or "", name or "")


def _num(n: int) -> str:
    return f"{n:,}".replace(",", " ")


def salary_label(j: dict) -> str:
    smin, smax = j.get("salary_min"), j.get("salary_max")
    if smin is None and smax is None:
        return j.get("salary_raw") or "не указана"
    currency = j.get("salary_currency") or ""
    pre, post = CURRENCY.get(currency, ("", f" {currency}" if currency else ""))
    if smin is not None and smax is not None and smin != smax:
        amount = f"{pre}{_num(smin)}–{_num(smax)}{post}"
    elif smin is not None and smax is not None:
        amount = f"{pre}{_num(smin)}{post}"
    elif smin is not None:
        amount = f"от {pre}{_num(smin)}{post}"
    else:
        amount = f"до {pre}{_num(smax)}{post}"
    return amount + PERIODS.get(j.get("salary_period") or "", "")


def scope_label(j: dict) -> str:
    scope = j.get("remote_scope")
    if scope == "worldwide":
        return "весь мир"
    if scope == "cis":
        return "СНГ"
    if scope == "countries":
        countries = j.get("countries") or []
        return "страны: " + ", ".join(countries) if countries else "страны: уточнить"
    if scope == "restricted":
        return "ограничено по стране"
    return "уточнить"


def hidden_label(reason: str | None) -> str:
    if not reason:
        return ""
    if reason.startswith("stopword:"):
        return "стоп-слово: " + reason.split(":", 1)[1]
    return HIDDEN_LABELS.get(reason, reason)


def ago(iso: str | None, now: datetime | None = None) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso)
    except ValueError:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    minutes = int(((now or datetime.now(UTC)) - dt).total_seconds() // 60)
    if minutes < 1:
        return "только что"
    if minutes < 60:
        return f"{minutes} мин назад"
    if minutes < 24 * 60:
        return f"{minutes // 60} ч назад"
    days = minutes // (24 * 60)
    return "вчера" if days == 1 else f"{days} дн назад"


def nl2br(text: str | None) -> Markup:
    return Markup("<br>\n").join(escape(line) for line in (text or "").splitlines())


# --- request parsing -------------------------------------------------------

MAX_INT = 10**12  # keeps query values far from SQLite/timedelta overflow


def _int(value: str | None) -> int | None:
    try:
        n = int((value or "").replace(" ", "").replace(" ", ""))
    except ValueError:
        return None
    return n if 0 <= n <= MAX_INT else None


def parse_filters(request: Request, conn: sqlite3.Connection) -> dict:
    """Query string → normalized filter state (tolerant: bad values are ignored)."""
    qp = request.query_params

    # A present-but-empty key (the form sends a hidden «src=») means «nothing selected»;
    # an absent key means «no restriction».
    def multi(name: str) -> list[str] | None:
        if name not in qp:
            return None
        return [v for v in qp.getlist(name) if v]

    fresh_raw = qp.get("fresh")
    if fresh_raw == "all":
        fresh = None
    else:
        fresh = _int(fresh_raw)
        if fresh is None or not 0 < fresh <= MAX_FRESH_DAYS:
            fresh = _int(str(db.get_setting(conn, "fresh_days"))) or 3
    section = qp.get("section", "feed")
    return {
        "q": qp.get("q", "").strip(),
        "section": section if section in SECTIONS else "feed",
        "src": multi("src"),
        "lang": multi("lang"),
        "scope": multi("scope"),
        "salary": _int(qp.get("salary")),
        # form sends hidden nosalary=0 plus checkbox nosalary=1; absent → default «show»
        "nosalary": "1" in qp.getlist("nosalary") if "nosalary" in qp else True,
        "fresh": fresh,
        "fresh_raw": "all" if fresh is None else str(fresh),
        "job": _int(qp.get("job")),
    }


def to_params(f: dict) -> SearchParams:
    return SearchParams(text=f["q"], section=f["section"], sources=f["src"], langs=f["lang"],
                        scopes=f["scope"], salary_min_usd=f["salary"],
                        include_no_salary=f["nosalary"], fresh_days=f["fresh"], limit=LIST_LIMIT)


def page_url(f: dict, **override) -> str:
    """Full-page URL for the filter state (deep link)."""
    state = {**f, **override}
    pairs: list[tuple[str, str]] = []
    if state["q"]:
        pairs.append(("q", state["q"]))
    if state["section"] != "feed":
        pairs.append(("section", state["section"]))
    for key in ("src", "lang", "scope"):
        if state[key] is not None:
            pairs += [(key, v) for v in state[key]] or [(key, "")]
    if state["salary"] is not None:
        pairs.append(("salary", str(state["salary"])))
    if not state["nosalary"]:
        pairs.append(("nosalary", "0"))
    pairs.append(("fresh", state["fresh_raw"]))
    if state.get("job"):
        pairs.append(("job", str(state["job"])))
    return "/?" + urlencode(pairs)


# --- view models -------------------------------------------------------------

def _list_context(conn: sqlite3.Connection, f: dict, now: datetime) -> dict:
    params = to_params(f)
    items = search_jobs(conn, params, now)
    ids = [it["id"] for it in items if it["remote_scope"] == "countries"]
    countries = {}
    if ids:
        marks = ",".join("?" * len(ids))
        rows = conn.execute(f"SELECT id, countries FROM jobs WHERE id IN ({marks})", ids)
        countries = {r["id"]: json.loads(r["countries"] or "[]") for r in rows}
    for it in items:
        it["countries"] = countries.get(it["id"], [])
        it["source_label"] = source_label(it["source_primary"])
        it["salary_label"] = salary_label(it)
        it["scope_label"] = scope_label(it)
        it["ago"] = ago(it["first_seen_at"], now)
        it["status_label"] = STATUS_LABELS.get(it["status"], it["status"])
        it["hidden_label"] = ("отклонил я" if it["status"] == "rejected"
                              else hidden_label(it["hidden_reason"]))
        it["url"] = page_url(f, job=it["id"])
    counts = count_sections(conn, params, now)
    tabs = [{"id": s, "label": SECTION_LABELS[s], "count": counts.get(s, 0),
             "url": page_url(f, section=s, job=None), "selected": s == f["section"]}
            for s in SECTIONS]
    return {"items": items, "tabs": tabs, "f": f, "limit_hit": len(items) >= LIST_LIMIT}


def _detail_context(job: dict, now: datetime) -> dict:
    postings = [dict(p, url=safe_url(p.get("url"))) for p in job["postings"]]
    postings = [p for p in postings if p["url"]]
    primary = next((p for p in postings if p["source"] == job["source_primary"]), None)
    if primary is None:
        primary = postings[0] if postings else {"source": job["source_primary"],
                                                "url": safe_url(job["url"])}
    others = [dict(p, label=source_label(p["source"])) for p in postings
              if p is not primary and p["url"] != primary["url"]]
    reasons = []
    if job["status"] == "rejected":
        reasons.append("отклонил я")
    if job.get("hidden_reason"):
        reasons.append(hidden_label(job["hidden_reason"]))
    raw_html = job.get("description_html") or ""
    desc_html = nh3.clean(raw_html, set_tag_attribute_values={"a": {"target": "_blank"}},
                          link_rel="noopener noreferrer") if raw_html.strip() else ""
    return {
        "job": job,
        "source": source_label(job["source_primary"]),
        "ago": ago(job.get("published_at") or job["first_seen_at"], now),
        "salary": salary_label(job),
        "scope": scope_label(job),
        "level": (job.get("seniority") or "").capitalize() or "не указан",
        "lang": LANG_LABELS.get(job.get("lang") or "", job.get("lang") or "—"),
        "primary": {"label": source_label(primary["source"]), "url": primary["url"]},
        "others": others,
        "reviews": review_links(job.get("company") or job["title"]),
        "buttons": [{"value": s, "label": STATUS_LABELS[s], "pressed": job["status"] == s}
                    for s in STATUS_BUTTONS],
        "hidden_reasons": reasons,
        "description_html": desc_html,
    }


def _header_context(conn: sqlite3.Connection, now: datetime) -> dict:
    runs = db.last_runs(conn).values()
    finished = [r["finished_at"] for r in runs if r["finished_at"]]
    return {"updated_ago": ago(max(finished), now) if finished else "",
            "new_total": sum(r["new"] or 0 for r in runs)}


def _source_options(conn: sqlite3.Connection, f: dict) -> list[dict]:
    counts = dict(conn.execute(
        "SELECT source_primary, COUNT(*) FROM jobs "
        "WHERE archived_at IS NULL AND hidden_reason IS NULL GROUP BY source_primary").fetchall())
    names = list(dict.fromkeys([*REGISTRY, *sorted(counts)]))
    return [{"name": n, "label": source_label(n), "count": counts.get(n, 0),
             "on": f["src"] is None or n in f["src"]} for n in names]


def _open_job(conn: sqlite3.Connection, job_id: int, now: datetime) -> tuple[dict, bool]:
    """Load a job for the detail panel; first open marks it `seen`."""
    job = db.get_job(conn, job_id) if 0 < job_id <= MAX_INT else None
    if job is None:
        raise HTTPException(404, "Вакансия не найдена")
    changed = job["status"] == "new"
    if changed:
        db.set_status(conn, job_id, "seen", now)
        job["status"] = "seen"
    return job, changed


# --- triage (screen C) ---------------------------------------------------------

TRIAGE_ACTIONS = {"reject": "rejected", "later": "seen", "interesting": "interesting"}
TRIAGE_BUTTONS = [
    {"action": "reject", "label": "Не подходит", "key": "←", "primary": False},
    {"action": "later", "label": "Позже", "key": "↓", "primary": False},
    {"action": "interesting", "label": "Интересно", "key": "→", "primary": True},
]
# Feed-section jobs the user has not decided on (freshness is not applied: nothing
# undecided should silently drop out of the queue before it is archived).
_TRIAGE_QUEUE = ("FROM jobs j LEFT JOIN user_status s ON s.job_id = j.id "
                 "WHERE j.archived_at IS NULL AND j.hidden_reason IS NULL "
                 "AND COALESCE(s.status, 'new') = 'new'")


def _local_midnight(now: datetime) -> datetime:
    return now.astimezone().replace(hour=0, minute=0, second=0, microsecond=0)


def _triage_context(conn: sqlite3.Connection, now: datetime) -> dict:
    """Next card plus the «N из M» counter: decided today / (decided today + remaining new)."""
    rows = conn.execute(f"SELECT j.id {_TRIAGE_QUEUE} ORDER BY j.first_seen_at, j.id LIMIT 2"
                        ).fetchall()
    remaining = conn.execute(f"SELECT COUNT(*) {_TRIAGE_QUEUE}").fetchone()[0]
    decided = conn.execute(
        "SELECT COUNT(*) FROM user_status s JOIN jobs j ON j.id = s.job_id "
        "WHERE s.status != 'new' AND s.updated_at >= ? AND j.hidden_reason IS NULL",
        (db._iso(_local_midnight(now)),)).fetchone()[0]
    total = decided + remaining
    nxt = db.get_job(conn, rows[1]["id"]) if len(rows) > 1 else None
    return {
        "d": _detail_context(db.get_job(conn, rows[0]["id"]), now) if rows else None,
        "next": {"title": nxt["title"], "company": nxt["company"],
                 "source": source_label(nxt["source_primary"])} if nxt else None,
        "done": decided, "total": total,
        "percent": round(100 * decided / total, 1) if total else 100,
        "buttons": TRIAGE_BUTTONS,
    }


# --- sources & settings (screen D) ----------------------------------------------

def clock(dt: datetime, now: datetime) -> tuple[str, str]:
    """Local (day word, HH:MM): ("сегодня", "09:00"), ("вчера", …), ("завтра", …), ("21.11", …)."""
    local, today = dt.astimezone(), now.astimezone().date()
    day = {0: "сегодня", -1: "вчера", 1: "завтра"}.get((local.date() - today).days,
                                                       local.strftime("%d.%m"))
    return day, local.strftime("%H:%M")


def _parse_iso(iso: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat(iso) if iso else None
    except ValueError:
        return None
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


def _source_row(name: str, run: sqlite3.Row | None, disabled: set[str],
                now: datetime) -> dict:
    src = REGISTRY[name]
    row = {"name": name, "label": source_label(name), "lang": (src.lang or "").upper(),
           "method": src.method, "on": name not in disabled, "last": "—", "new": "—",
           "skipped": 0}
    if run is not None:
        row["last"] = ago(run["finished_at"] or run["started_at"], now) or "—"
        if run["finished_at"]:
            row["new"] = run["new"] or 0
            row["skipped"] = run["skipped"] or 0
    if not row["on"]:
        row["state"], row["tone"] = "выключен", "off"
    elif run is None:
        row["state"], row["tone"] = "ещё не запускался", "idle"
    elif not run["finished_at"]:
        row["state"], row["tone"] = "сбор не завершён", "idle"
    elif run["ok"]:
        row["state"] = f"работает · {run['error']}" if run["error"] else "работает"
        row["tone"] = "ok"
    else:
        row["state"], row["tone"] = run["error"] or "ошибка", "error"
    return row


def _source_rows(conn: sqlite3.Connection, now: datetime) -> list[dict]:
    runs = db.last_runs(conn)
    disabled = set(db.get_setting(conn, "disabled_sources") or [])
    return [_source_row(n, runs.get(n), disabled, now) for n in REGISTRY]


def _schedule_line(conn: sqlite3.Connection, sched, now: datetime) -> str:
    finished = [r["finished_at"] for r in db.last_runs(conn).values() if r["finished_at"]]
    last = _parse_iso(max(finished)) if finished else None
    parts = ["Последний сбор: " + " ".join(clock(last, now)) if last else "Сбора ещё не было"]
    job = sched.get_job("collect") if sched is not None else None
    if job is not None and job.next_run_time is not None:
        day, hm = clock(job.next_run_time, now)
        parts.append(f"следующий в {hm}" + ("" if day == "сегодня" else f", {day}"))
    return " · ".join(parts)


SETTINGS_LIMITS = {"interval_hours": (1, 24, "Интервал сбора — целое число часов от 1 до 24"),
                   "fresh_days": (1, 30, "Свежесть ленты — целое число дней от 1 до 30")}


def parse_settings_form(form: dict[str, str | None]) -> tuple[dict, list[str]]:
    """Form strings → settings changes; absent fields are left alone. Returns (changes, errors).

    hh_token: an empty value keeps the stored token unless `hh_token_clear` is ticked.
    """
    changes: dict = {}
    errors: list[str] = []
    for key, (lo, hi, message) in SETTINGS_LIMITS.items():
        raw = form.get(key)
        if raw is None:
            continue
        try:
            value = int(raw.strip())
        except ValueError:
            value = None
        if value is None or not lo <= value <= hi:
            errors.append(message)
        else:
            changes[key] = value
    if form.get("stopwords") is not None:
        words = form["stopwords"].replace("\n", ",").split(",")
        changes["stopwords"] = list(dict.fromkeys(w.strip() for w in words if w.strip()))
    token = (form.get("hh_token") or "").strip()
    if form.get("hh_token_clear"):
        changes["hh_token"] = ""
    elif token:
        changes["hh_token"] = token
    return changes, errors


def _settings_context(conn: sqlite3.Connection, form: dict | None = None,
                      errors: list[str] | None = None, saved: bool = False) -> dict:
    s = db.all_settings(conn)
    values = {"interval_hours": str(s["interval_hours"]), "fresh_days": str(s["fresh_days"]),
              "stopwords": ", ".join(s["stopwords"] or [])}
    for key in values:  # on error, show what the user typed so it can be fixed
        if form and form.get(key) is not None:
            values[key] = form[key]
    return {"settings": values, "token_set": bool(s.get("hh_token")),
            "errors": errors or [], "saved": saved}


# --- app ---------------------------------------------------------------------

def create_app(db_path: Path | str, start_scheduler: bool = True) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if start_scheduler:
            app.state.scheduler = scheduler.start_scheduler(app.state.db_path)
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                app.state.scheduler.shutdown(wait=False)
                app.state.scheduler = None

    app = FastAPI(title="Job Finder", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=lifespan)
    app.state.db_path = Path(db_path)
    app.state.scheduler = None
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["nl2br"] = nl2br

    def get_conn() -> Iterator[sqlite3.Connection]:
        conn = db.connect(app.state.db_path)
        try:
            yield conn
        finally:
            conn.close()

    @app.get("/", response_class=HTMLResponse)
    def feed(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        now = datetime.now(UTC)
        f = parse_filters(request, conn)
        detail = None
        if f["job"] is not None:
            job, _ = _open_job(conn, f["job"], now)
            detail = _detail_context(job, now)
        ctx = {
            **_list_context(conn, f, now), **_header_context(conn, now),
            "d": detail, "sources": _source_options(conn, f),
            "scope_options": SCOPE_OPTIONS, "lang_options": LANG_OPTIONS,
            "fresh_options": FRESH_OPTIONS, "active": "feed", "oob": False,
        }
        return templates.TemplateResponse(request, "feed.html", ctx)

    @app.get("/list", response_class=HTMLResponse)
    def job_list(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        now = datetime.now(UTC)
        f = parse_filters(request, conn)
        resp = templates.TemplateResponse(request, "_list.html",
                                          {**_list_context(conn, f, now), "oob": True})
        resp.headers["HX-Replace-Url"] = page_url(f)
        return resp

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: int, conn: sqlite3.Connection = Depends(get_conn)):
        now = datetime.now(UTC)
        job, changed = _open_job(conn, job_id, now)
        resp = templates.TemplateResponse(request, "_detail.html",
                                          {"d": _detail_context(job, now), "oob": True})
        if changed:
            resp.headers["HX-Trigger-After-Swap"] = "list-changed"
        return resp

    @app.post("/jobs/{job_id}/status", response_class=HTMLResponse,
              dependencies=[Depends(require_same_origin)])
    def job_status(request: Request, job_id: int, status: str = Form(...),
                   conn: sqlite3.Connection = Depends(get_conn)):
        now = datetime.now(UTC)
        if not 0 < job_id <= MAX_INT or db.get_job(conn, job_id) is None:
            raise HTTPException(404, "Вакансия не найдена")
        if status not in STATUSES:
            raise HTTPException(422, f"Неизвестный статус: {status}")
        db.set_status(conn, job_id, status, now)
        job = db.get_job(conn, job_id)
        resp = templates.TemplateResponse(request, "_detail.html",
                                          {"d": _detail_context(job, now), "oob": True})
        # After-swap: the OOB #job-input update must land before #list refreshes.
        resp.headers["HX-Trigger-After-Swap"] = "list-changed"
        return resp

    # --- triage (screen C) ---

    @app.get("/triage", response_class=HTMLResponse)
    def triage(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        ctx = {**_triage_context(conn, datetime.now(UTC)), "active": "triage", "oob": False}
        return templates.TemplateResponse(request, "triage.html", ctx)

    @app.post("/triage/{job_id}", response_class=HTMLResponse,
              dependencies=[Depends(require_same_origin)])
    def triage_decide(request: Request, job_id: int, action: str = Form(...),
                      conn: sqlite3.Connection = Depends(get_conn)):
        now = datetime.now(UTC)
        if not 0 < job_id <= MAX_INT or db.get_job(conn, job_id) is None:
            raise HTTPException(404, "Вакансия не найдена")
        if action not in TRIAGE_ACTIONS:
            raise HTTPException(422, f"Неизвестное действие: {action}")
        # A stale tab must not overwrite a decision made elsewhere: only `new` changes.
        if db.get_status(conn, job_id) == "new":
            db.set_status(conn, job_id, TRIAGE_ACTIONS[action], now)
        if "hx-request" not in request.headers:  # plain form post: back to the page
            return RedirectResponse("/triage", status_code=303)
        return templates.TemplateResponse(request, "_triage_card.html",
                                          {**_triage_context(conn, now), "oob": True})

    # --- sources & settings (screen D) ---

    def sources_page(request: Request, conn: sqlite3.Connection, status_code: int = 200,
                     **settings_kw) -> HTMLResponse:
        now = datetime.now(UTC)
        ctx = {"rows": _source_rows(conn, now),
               "schedule": _schedule_line(conn, app.state.scheduler, now),
               **_settings_context(conn, **settings_kw), "active": "sources"}
        return templates.TemplateResponse(request, "sources.html", ctx, status_code=status_code)

    @app.get("/sources", response_class=HTMLResponse)
    def sources(request: Request, conn: sqlite3.Connection = Depends(get_conn)):
        return sources_page(request, conn)

    @app.post("/sources/{name}/toggle", response_class=HTMLResponse,
              dependencies=[Depends(require_same_origin)])
    def toggle_source(request: Request, name: str, conn: sqlite3.Connection = Depends(get_conn)):
        if name not in REGISTRY:
            raise HTTPException(404, "Источник не найден")
        current = db.get_setting(conn, "disabled_sources") or []
        disabled = [n for n in current if n != name] if name in current else [*current, name]
        db.set_setting(conn, "disabled_sources", disabled)
        now = datetime.now(UTC)
        row = _source_row(name, db.last_runs(conn).get(name), set(disabled), now)
        return templates.TemplateResponse(request, "_source_row.html", {"s": row})

    @app.post("/settings", response_class=HTMLResponse,
              dependencies=[Depends(require_same_origin)])
    def save_settings(request: Request, interval_hours: str | None = Form(None),
                      fresh_days: str | None = Form(None), stopwords: str | None = Form(None),
                      hh_token: str | None = Form(None), hh_token_clear: str | None = Form(None),
                      conn: sqlite3.Connection = Depends(get_conn)):
        form = {"interval_hours": interval_hours, "fresh_days": fresh_days,
                "stopwords": stopwords, "hh_token": hh_token, "hh_token_clear": hh_token_clear}
        changes, errors = parse_settings_form(form)
        htmx = "hx-request" in request.headers
        if errors:
            kw = {"form": form, "errors": errors}
            if not htmx:
                return sources_page(request, conn, status_code=422, **kw)
            return templates.TemplateResponse(request, "_settings.html",
                                              _settings_context(conn, **kw), status_code=422)
        old_hours = db.get_setting(conn, "interval_hours")
        for key, value in changes.items():
            db.set_setting(conn, key, value)
        hours = changes.get("interval_hours", old_hours)
        if hours != old_hours and app.state.scheduler is not None:
            scheduler.reschedule(app.state.scheduler, hours)
        if not htmx:
            return RedirectResponse("/sources", status_code=303)
        return templates.TemplateResponse(request, "_settings.html",
                                          _settings_context(conn, saved=True))

    @app.post("/collect", response_class=HTMLResponse,
              dependencies=[Depends(require_same_origin)])
    def collect_now():
        if collector.is_running(app.state.db_path):
            message = "Сбор уже идёт"
        else:
            threading.Thread(target=scheduler.run_collect, args=(app.state.db_path,),
                             name="collect-now", daemon=True).start()
            message = "Сбор запущен — обнови страницу через несколько минут"
        return HTMLResponse(f'<span class="collect-status">{escape(message)}</span>')

    return app
