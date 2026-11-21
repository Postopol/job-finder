"""Web UI: feed screen (A) with filters, list and detail panel."""
from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

import nh3
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from .. import db
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
HIDDEN_LABELS = {"hybrid": "гибрид", "office": "офис",
                 "restricted": "не для твоей страны"}
CURRENCY = {"USD": ("$", ""), "EUR": ("€", ""), "GBP": ("£", ""),
            "RUB": ("", " ₽"), "KZT": ("", " ₸")}
PERIODS = {"month": " / мес", "year": " / год", "hour": " / час"}


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
    postings = [p for p in job["postings"] if p.get("url")]
    primary = next((p for p in postings if p["source"] == job["source_primary"]), None)
    if primary is None:
        primary = postings[0] if postings else {"source": job["source_primary"], "url": job["url"]}
    others = [dict(p, label=source_label(p["source"])) for p in postings
              if p is not primary and p["url"] != primary["url"]]
    reasons = []
    if job["status"] == "rejected":
        reasons.append("отклонил я")
    if job.get("hidden_reason"):
        reasons.append(hidden_label(job["hidden_reason"]))
    raw_html = job.get("description_html") or ""
    desc_html = nh3.clean(raw_html) if raw_html.strip() else ""
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


# --- app ---------------------------------------------------------------------

def create_app(db_path: Path | str, start_scheduler: bool = True) -> FastAPI:
    # start_scheduler is wired in a later task; accepted here for a stable signature.
    app = FastAPI(title="Job Finder", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.db_path = Path(db_path)
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
            resp.headers["HX-Trigger"] = "list-changed"
        return resp

    @app.post("/jobs/{job_id}/status", response_class=HTMLResponse)
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
        resp.headers["HX-Trigger"] = "list-changed"
        return resp

    return app
