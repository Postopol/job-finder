# Job Finder Phase 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A local tool that collects remote IT vacancies from 13 RU/EN sites into SQLite and shows them on a browser page with statuses, triage and search.

**Architecture:** Each site is a pluggable source module with a pure `parse_item(item) -> Job` and a `fetch()` that pages politely and stops at known jobs. A collector runs sources in isolation, normalizes, filters, dedups and upserts into SQLite (with FTS5 search). A FastAPI + Jinja2 + HTMX app renders three screens; APScheduler runs collection every 6 h inside the server.

**Tech Stack:** Python ≥3.12 (machine has 3.14), uv, httpx, feedparser, selectolax, PyStemmer, nh3, FastAPI, uvicorn, Jinja2, HTMX (vendored JS file), APScheduler 3.x, pytest.

**Spec:** `docs/superpowers/specs/2026-11-22-job-finder-parser-design.md`

## Global Constraints

- Single user, local only; server binds `127.0.0.1:8000`.
- DB file `data/jobs.db`; SQLite WAL mode and `busy_timeout=5000` on every connection.
- User-Agent for all requests: `Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0` — no personal data, no email.
- Per-site requests strictly sequential, random pause 1–2 s between requests; timeout 30 s; 2 retries with backoff, except 429/403 which stop the source until the next run.
- Max pages per source per run: setting `max_pages`, default 5.
- Collection interval default 6 h; archive rule 7 days; raw purge 90 days; feed freshness default 3 days.
- User country default `KZ`; visible scopes: `worldwide`, `cis`, `countries` containing the user country, `unknown` (marked «уточнить»); `restricted` hidden.
- Statuses: `new`, `seen`, `interesting`, `applied`, `rejected`. Triage «позже» = `seen`.
- UI language Russian; style = qymyz.dev night theme (square corners, Bitcount Prop Single for labels/headings, Mona Sans for text, violet `#a970ff` primary, canvas `#0b0a0e`); see mockups (boards A, C, D).
- Every vacancy shows a link to its original (RemoteOK/Jobicy/Remote First Jobs requirement).
- Tests never hit the network; live checks only via `jobfinder check-sources`.
- **Deviation from spec, decided here:** user-editable settings live in a `settings` table (defaults in code), not in `config.toml` — screen D edits them; no config file is needed.
- **Archive rule refinement, decided here:** incremental sources stop paging at known jobs, so old jobs are not re-seen. Each source declares `full_listing: bool`. Full-listing sources (one request returns the whole current list): archive when not seen 7 days and the source had an ok run in the last 2 days. Incremental sources: archive when `first_seen_at` is older than 30 days. A job is archived when all its postings qualify.

## Review Focus

1. **Collection writing while the user clicks a status** — must not fail with `database is locked`; expected: both writes succeed (WAL + busy_timeout). Test in Task 2.
2. **A site changes its layout** (no `__NEXT_DATA__`/`__NUXT_DATA__`, unexpected JSON) — expected: that source's run is marked failed with «формат страницы изменился», other sources still run, nothing crashes. Tests in Tasks 6 and 9.
3. **Odd salary strings** («от 300 000 ₽», «$70k–90k», «€3,500 - 4,500 per month», «до 200 тыс. руб.», «competitive») — expected: parsed or `None` with `salary_raw` kept, never an exception. Test in Task 1.
4. **Search input with FTS syntax characters** (`C++`, `C#`, `.NET`, `node.js`, a lone `"`, `*`, `-`) — expected: results or empty list, never HTTP 500. Test in Task 5.
5. **Malicious or broken HTML in descriptions** (`<script>`, `onerror=`, unclosed tags) — expected: rendered sanitized (nh3), no script runs. Test in Task 12.

---

## File Structure

```
pyproject.toml                  # deps, [project.scripts] jobfinder = "jobfinder.cli:main"
jobfinder/
  __init__.py
  models.py        # Job dataclass, scope/status constants
  normalize.py     # parse_salary, detect_seniority, extract_stack, html_to_text, normalize_job
  filters.py       # classify_scope, hidden_reason, FilterConfig
  dedup.py         # dedup_key
  db.py            # connect/schema, upsert_job, statuses, runs, settings, get_job
  search.py        # stem_text, expand_query, index_job, search_jobs, SearchParams
  synonyms.toml
  http.py          # PoliteClient, SourceBlocked, SourceError
  sources/
    __init__.py    # REGISTRY: dict[str, Source]
    base.py        # Source base class, ParseError, embedded-JSON helpers
    himalayas.py remoteok.py jobicy.py workingnomads.py
    wwr.py remotefirst.py hn.py
    arc.py rocketship.py hirify.py
    hh.py habr.py getmatch.py
  collector.py     # collect()
  archive.py       # archive_stale, purge_raw, reparse
  scheduler.py     # start_scheduler
  web/
    app.py         # create_app
    templates/     # base.html, feed.html, _list.html, _detail.html, triage.html, sources.html
    static/        # style.css, htmx.min.js, keys.js
  cli.py           # serve | collect | check-sources | reparse
tests/
  fixtures/        # one real response per source
  test_normalize.py test_filters.py test_dedup.py test_db.py test_search.py
  test_http.py test_collector.py test_sources_api.py test_sources_rss.py
  test_sources_embedded.py test_sources_ru.py test_archive.py test_web.py
```

---

### Task 1: Project scaffold, Job model, normalization

**Files:**
- Create: `pyproject.toml`, `jobfinder/__init__.py`, `jobfinder/models.py`, `jobfinder/normalize.py`, `.gitignore` (`data/`, `.venv/`, `__pycache__/`)
- Test: `tests/test_normalize.py`

**Interfaces:**
- Produces:
  - `models.Job` dataclass: `source: str`, `source_id: str`, `url: str`, `title: str`, `company: str | None = None`, `lang: str = "en"`, `description_html: str = ""`, `description_text: str = ""`, `salary_raw: str | None = None`, `salary_min: int | None = None`, `salary_max: int | None = None`, `salary_currency: str | None = None` (ISO: USD, EUR, RUB, KZT, GBP), `salary_period: str | None = None` (`month|year|hour`), `location_raw: str | None = None`, `work_format: str | None = None` (`remote|hybrid|office`), `remote_scope: str = "unknown"`, `countries: list[str]` (ISO-2), `timezones: list[str]`, `seniority: str | None = None` (`junior|middle|senior|lead`), `stack: list[str]`, `published_at: datetime | None = None` (UTC-aware), `raw: dict | None = None` (the source item, for reparse).
  - `models.SCOPES = ("worldwide", "cis", "countries", "restricted", "unknown")`, `models.STATUSES = ("new", "seen", "interesting", "applied", "rejected")`, `models.CIS = {"KZ","RU","BY","UZ","KG","AM","AZ","TJ","MD","GE"}`.
  - `normalize.Salary` NamedTuple `(min: int|None, max: int|None, currency: str|None, period: str|None)`.
  - `normalize.parse_salary(text: str | None) -> Salary | None`
  - `normalize.detect_seniority(title: str, text: str = "") -> str | None`
  - `normalize.extract_stack(text: str, tags: list[str] = ()) -> list[str]` — canonical names from a `STACK_TERMS` dict in the module (~80 terms: languages, frameworks, DBs, cloud, devops, data/ML tools; aliases map to canonical, e.g. `k8s→Kubernetes`, `golang→Go`, `js→JavaScript`, `postgres→PostgreSQL`). Matching is whole-word, case-insensitive; `C++`, `C#`, `.NET`, `Node.js` handled.
  - `normalize.html_to_text(html: str) -> str`
  - `normalize.normalize_job(job: Job) -> Job` — fills `description_text` from html if empty; parses salary from `salary_raw` if `salary_min/max` empty; seniority from title/text if empty; merges `extract_stack` into `stack` (dedup, keep order).

- [ ] **Step 1: Create `pyproject.toml`** with project `jobfinder`, `requires-python = ">=3.12"`, deps listed in Tech Stack (APScheduler `>=3.10,<4`), dev dep `pytest`, script entry `jobfinder = "jobfinder.cli:main"`. Run `uv sync` — expected: environment created without errors.

- [ ] **Step 2: Write failing tests** in `tests/test_normalize.py`:

```python
import pytest
from jobfinder.normalize import parse_salary, detect_seniority, extract_stack, html_to_text, Salary

@pytest.mark.parametrize("text,expected", [
    ("от 300 000 ₽", Salary(300000, None, "RUB", "month")),
    ("до 200 тыс. руб.", Salary(None, 200000, "RUB", "month")),
    ("350 000–450 000 ₽", Salary(350000, 450000, "RUB", "month")),
    ("$70k–90k", Salary(70000, 90000, "USD", "year")),
    ("$5,000 - $6,500 / month", Salary(5000, 6500, "USD", "month")),
    ("€3,500 - 4,500 per month", Salary(3500, 4500, "EUR", "month")),
    ("$45/hr", Salary(45, None, "USD", "hour")),
    ("500 000 ₸", Salary(500000, None, "KZT", "month")),
])
def test_parse_salary(text, expected):
    assert parse_salary(text) == expected

@pytest.mark.parametrize("text", ["competitive", "", None, "по договорённости", "💰💰"])
def test_parse_salary_unparseable_returns_none(text):
    assert parse_salary(text) is None

def test_period_defaults():
    # bare USD amount >= 20000 is yearly, below is monthly; RUB/KZT default monthly
    assert parse_salary("$120,000").period == "year"
    assert parse_salary("$4000").period == "month"

@pytest.mark.parametrize("title,expected", [
    ("Senior Python Developer", "senior"), ("Старший разработчик", "senior"),
    ("Ведущий инженер", "senior"), ("Middle+ Go-разработчик", "middle"),
    ("Junior QA", "junior"), ("Team Lead Backend", "lead"), ("Developer", None),
])
def test_detect_seniority(title, expected):
    assert detect_seniority(title) == expected

def test_extract_stack_aliases_and_symbols():
    text = "We use golang, k8s, Postgres, C++, C# and .NET; Node.js is a plus"
    assert extract_stack(text) == ["Go", "Kubernetes", "PostgreSQL", "C++", "C#", ".NET", "Node.js"]

def test_extract_stack_whole_words_only():
    assert "Go" not in extract_stack("Good communication, Django")
    assert extract_stack("Django") == ["Django"]

def test_html_to_text_strips_tags_and_keeps_breaks():
    assert html_to_text("<p>One</p><ul><li>Two</li></ul><script>x()</script>") == "One\nTwo"
```

- [ ] **Step 3: Run** `uv run pytest tests/test_normalize.py -v` — expected: FAIL (module not found).

- [ ] **Step 4: Implement** `models.py` and `normalize.py` per Interfaces. Salary: regex over normalized text (strip NBSP/thin spaces, unify dashes), currency from symbol/word (`₽ руб RUB → RUB`, `$ USD → USD`, `€ EUR → EUR`, `₸ тенге KZT → KZT`, `£ → GBP`), multipliers `k`/`тыс`, «от»=min only, «до»=max only, period words (`month|mo|мес`, `year|yr|annual|год`, `hour|hr|час`), else the default rule from `test_period_defaults`. Any exception inside → `None`. `html_to_text` via selectolax, dropping `script/style`, block elements become newlines, collapse blank lines.

- [ ] **Step 5: Run** `uv run pytest tests/test_normalize.py -v` — expected: all PASS.

- [ ] **Step 6: Commit** `git add -A && git commit -m "feat: scaffold, Job model, normalization"`

---

### Task 2: Database, dedup key, statuses, runs, settings

**Files:**
- Create: `jobfinder/dedup.py`, `jobfinder/db.py`
- Test: `tests/test_dedup.py`, `tests/test_db.py`

**Interfaces:**
- Consumes: `models.Job`.
- Produces:
  - `dedup.dedup_key(company: str | None, title: str) -> str` — lowercase, `ё→е`, drop punctuation, drop words `remote|удаленно|удалённо|fulltime|full-time`, drop seniority words and anything in parentheses/brackets, collapse spaces; `company or ""` + `"|"` + title.
  - `db.connect(path: Path | str) -> sqlite3.Connection` — creates parent dir, WAL, busy_timeout 5000, `row_factory = sqlite3.Row`, creates schema if missing.
  - Schema: `jobs(id, dedup_key, source_primary, title, company, lang, url, description_html, description_text, salary_raw, salary_min, salary_max, salary_currency, salary_period, salary_usd_month, location_raw, work_format, remote_scope, countries JSON, timezones JSON, seniority, stack JSON, published_at, first_seen_at, last_seen_at, archived_at, hidden_reason)`; `postings(id, job_id, source, source_id, url, first_seen_at, last_seen_at, raw BLOB, UNIQUE(source, source_id))`; `user_status(job_id PK, status, updated_at)`; `runs(id, source, started_at, finished_at, ok, fetched, new, error)`; `settings(key PK, value JSON)`; `jobs_fts` (created in Task 5 via `search.ensure_fts(conn)`, called from `connect`).
  - `db.upsert_job(conn, job: Job, hidden_reason: str | None, now: datetime) -> tuple[int, bool]` — returns `(job_id, is_new)`. Lookup order: existing posting `(source, source_id)` → its job; else a job with same `dedup_key` and `last_seen_at >= now - 30 days` → add posting; else insert job. On update: refresh fields (keep the longer `description_html`), set `last_seen_at=now`, `archived_at=NULL`, update `hidden_reason`. `raw` stored as `zlib.compress(json.dumps(job.raw).encode())`. `salary_usd_month` computed with `get_setting(conn, "rates")`. Never touches `user_status`.
  - `db.known_source_ids(conn, source: str) -> set[str]`
  - `db.set_status(conn, job_id: int, status: str, now: datetime) -> None` (validates against `STATUSES`), `db.get_status(conn, job_id: int) -> str` (default `"new"`).
  - `db.start_run(conn, source: str, now: datetime) -> int`, `db.finish_run(conn, run_id: int, ok: bool, fetched: int, new: int, error: str | None, now: datetime) -> None`, `db.last_runs(conn) -> dict[str, sqlite3.Row]` (latest per source).
  - `db.DEFAULT_SETTINGS = {"country": "KZ", "interval_hours": 6, "max_pages": 5, "fresh_days": 3, "archive_days": 7, "purge_days": 90, "stopwords": [], "hh_token": "", "disabled_sources": [], "rates": {"USD": 1, "EUR": 1.08, "GBP": 1.27, "RUB": 0.011, "KZT": 0.002}}`; `db.get_setting(conn, key)`, `db.set_setting(conn, key, value)`.
  - `db.get_job(conn, job_id: int) -> dict | None` — job row with JSON fields decoded, `status`, and `postings` list (`source`, `url`).

- [ ] **Step 1: Write failing tests** `tests/test_dedup.py`:

```python
from jobfinder.dedup import dedup_key

def test_same_job_different_sites_same_key():
    assert dedup_key("Northwind Labs", "Senior Python Developer (Remote)") == \
           dedup_key("northwind labs", "Python Developer — remote")

def test_different_titles_differ():
    assert dedup_key("Acme", "Backend Developer") != dedup_key("Acme", "Frontend Developer")
```

and `tests/test_db.py` (use `tmp_path`; helper `mk(**kw) -> Job` with defaults `source="s1", source_id="1", url="https://x/1", title="Python Developer", company="Acme"`):

```python
def test_insert_then_update_same_posting(conn, now):
    jid, new = upsert_job(conn, mk(), None, now)
    jid2, new2 = upsert_job(conn, mk(title="Python Developer"), None, now + timedelta(hours=6))
    assert new and not new2 and jid == jid2

def test_cross_source_duplicate_merges_postings(conn, now):
    a, _ = upsert_job(conn, mk(source="hh", source_id="1"), None, now)
    b, new = upsert_job(conn, mk(source="habr", source_id="9", url="https://h/9"), None, now)
    assert a == b and not new
    assert {p["source"] for p in get_job(conn, a)["postings"]} == {"hh", "habr"}

def test_status_survives_recollect(conn, now):
    jid, _ = upsert_job(conn, mk(), None, now)
    set_status(conn, jid, "interesting", now)
    upsert_job(conn, mk(), None, now + timedelta(days=1))
    assert get_status(conn, jid) == "interesting"

def test_reappearing_job_is_unarchived(conn, now):
    jid, _ = upsert_job(conn, mk(), None, now)
    conn.execute("UPDATE jobs SET archived_at=? WHERE id=?", (now.isoformat(), jid))
    upsert_job(conn, mk(), None, now + timedelta(days=10))
    assert get_job(conn, jid)["archived_at"] is None

def test_concurrent_status_write_during_collection(tmp_path, now):  # Review Focus 1
    path = tmp_path / "j.db"
    c1, c2 = connect(path), connect(path)
    jid, _ = upsert_job(c1, mk(), None, now)
    c1.commit()
    c1.execute("BEGIN IMMEDIATE"); upsert_job(c1, mk(source_id="2", url="https://x/2", title="Go Dev"), None, now)
    t = threading.Timer(0.3, c1.commit); t.start()
    set_status(c2, jid, "applied", now)   # waits on busy_timeout, must not raise
    t.join()
    assert get_status(c2, jid) == "applied"

def test_settings_defaults_and_override(conn):
    assert get_setting(conn, "interval_hours") == 6
    set_setting(conn, "stopwords", ["1С"]); assert get_setting(conn, "stopwords") == ["1С"]

def test_runs_roundtrip(conn, now):
    rid = start_run(conn, "remoteok", now)
    finish_run(conn, rid, False, 0, 0, "HTTP 429", now)
    assert last_runs(conn)["remoteok"]["error"] == "HTTP 429"
```

- [ ] **Step 2: Run** `uv run pytest tests/test_dedup.py tests/test_db.py -v` — expected: FAIL.
- [ ] **Step 3: Implement** `dedup.py` and `db.py` per Interfaces. Each mutating function commits unless the caller is inside an explicit transaction (`conn.in_transaction`). Datetimes stored as ISO-8601 UTC strings.
- [ ] **Step 4: Run** the same tests — expected: all PASS.
- [ ] **Step 5: Commit** `git commit -am "feat: sqlite storage, dedup, statuses, runs, settings"` (add new files first).

---

### Task 3: Filters (where you can work, format, stop-words)

**Files:**
- Create: `jobfinder/filters.py`
- Test: `tests/test_filters.py`

**Interfaces:**
- Consumes: `models.Job`, `models.CIS`.
- Produces:
  - `filters.FilterConfig` dataclass: `country: str = "KZ"`, `stopwords: list[str]`.
  - `filters.classify_scope(job: Job) -> tuple[str, list[str]]` — if the source already set `remote_scope != "unknown"` or `countries`, respect it (`countries` non-empty → `"countries"`, unless all are CIS → `"cis"`); otherwise scan `title + location_raw + description_text` with phrase lists: restricted (`us only`, `usa only`, `u.s. only`, `must be based in the us`, `must reside in`, `eu only`, `europe only`, `uk only`, `только рф`, `гражданство рф`, `только россия`, `only candidates from`); worldwide (`worldwide`, `anywhere`, `work from anywhere`, `global`, `весь мир`, `любой стране`, `любая страна`); cis (`снг`, `cis`, `казахстан`, `kazakhstan`, `из любой точки снг`). Restricted wins over worldwide only when it appears in `location_raw` or the first 400 chars of the description.
  - `filters.hidden_reason(job: Job, cfg: FilterConfig) -> str | None` — returns first of: `"office"` / `"hybrid"` (from `work_format`, else words `hybrid|on-site|onsite|гибрид|в офисе|офис` in `location_raw` or title), `"restricted"` (scope `restricted`, or scope `countries` without `cfg.country`), `"stopword:<w>"` (case-insensitive whole word in title or description), else `None`.

- [ ] **Step 1: Write failing tests** — table-driven:

```python
@pytest.mark.parametrize("loc,desc,expected", [
    ("Anywhere in the World", "", "worldwide"),
    ("USA Only", "", "restricted"),
    ("Remote", "You must reside in the United States.", "restricted"),
    ("Удалённо", "Работа из любой точки СНГ", "cis"),
    ("Remote", "Join our global team", "worldwide"),
    ("Remote", "Nothing about location", "unknown"),
])
def test_classify_scope_from_text(loc, desc, expected):
    assert classify_scope(mk(location_raw=loc, description_text=desc))[0] == expected

def test_structured_countries_respected():
    assert classify_scope(mk(countries=["KZ", "UZ"])) == ("cis", ["KZ", "UZ"])
    assert classify_scope(mk(countries=["US", "CA"])) == ("countries", ["US", "CA"])

@pytest.mark.parametrize("job,reason", [
    (dict(work_format="hybrid"), "hybrid"),
    (dict(location_raw="Berlin, on-site"), "office"),
    (dict(remote_scope="countries", countries=["US"]), "restricted"),
    (dict(remote_scope="countries", countries=["US", "KZ"]), None),
    (dict(title="Программист 1С"), "stopword:1с"),
    (dict(remote_scope="unknown"), None),
])
def test_hidden_reason(job, reason):
    assert hidden_reason(mk(**job), FilterConfig(country="KZ", stopwords=["1С"])) == reason
```

- [ ] **Step 2: Run** `uv run pytest tests/test_filters.py -v` — expected: FAIL.
- [ ] **Step 3: Implement** `filters.py` per Interfaces (stop-word reasons lowercased).
- [ ] **Step 4: Run** — expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: location/format/stopword filters"`.

---

### Task 4: HTTP client and source base

**Files:**
- Create: `jobfinder/http.py`, `jobfinder/sources/__init__.py`, `jobfinder/sources/base.py`
- Test: `tests/test_http.py`

**Interfaces:**
- Produces:
  - `http.SourceBlocked(Exception)` (carries status code), `http.SourceError(Exception)`.
  - `http.PoliteClient(delay: tuple[float, float] = (1.0, 2.0), timeout: float = 30, retries: int = 2, headers: dict | None = None, transport: httpx.BaseTransport | None = None, sleep=time.sleep)` with `.get(url: str, params: dict | None = None) -> httpx.Response`, `.close()`. Sleeps a random delay before every request except the first; on 429/403 raises `SourceBlocked` immediately; on network errors/5xx retries with backoff `2**attempt` s, then raises `SourceError`. Sets the Global Constraints User-Agent.
  - `base.ParseError(Exception)` — message «формат страницы изменился: …».
  - `PoliteClient.requests: int` — number of HTTP requests made (for run stats).
  - `base.Source` base class: class attrs `name: str`, `lang: str`, `full_listing: bool`, `method: str` (UI label: «Открытый API», «RSS», «JSON сайта», «Страница сайта»); methods `parse_item(self, item: dict) -> Job | None` (abstract), `fetch(self, client: PoliteClient, known: set[str], wants: Callable[[Job], bool], settings: dict) -> list[Job]` (abstract). Helper `base.paged(fetch_page: Callable[[int], list[dict]], parse, known, max_pages) -> list[Job]` — iterates pages from 1, stops after a page containing any known `source_id`, an empty page, or `max_pages`.
  - `base.next_data(html: str) -> dict` (content of `<script id="__NEXT_DATA__">`), `base.nuxt_data(html: str) -> object` (decode `<script id="__NUXT_DATA__">`), both raise `ParseError` when the tag is missing or JSON invalid.
  - Nuxt payload decoding (devalue format), used by `nuxt_data`:

```python
def _revive(arr, idx, memo):
    # arr is the flat JSON array; ints inside containers are indices into arr.
    if idx in memo: return memo[idx]
    v = arr[idx]
    if isinstance(v, list):
        if v and isinstance(v[0], str) and v[0] in ("Reactive", "ShallowReactive", "Ref", "ShallowRef", "EmptyRef", "EmptyShallowRef"):
            out = _revive(arr, v[1], memo) if len(v) > 1 else None
        elif v and v[0] == "Set":  out = [_revive(arr, i, memo) for i in v[1:]]
        elif v and v[0] == "Map":  out = {str(_revive(arr, v[i], memo)): _revive(arr, v[i+1], memo) for i in range(1, len(v), 2)}
        elif v and v[0] == "Date": out = v[1]
        else: out = [_revive(arr, i, memo) for i in v]
    elif isinstance(v, dict): out = {k: _revive(arr, i, memo) for k, i in v.items()}
    else: out = v
    memo[idx] = out
    return out
# nuxt_data returns _revive(arr, 0, {}); negative ints (-1 undefined etc.) map to None.
```

  - `sources.REGISTRY: dict[str, Source]` — filled as sources are added in Tasks 7–10.

- [ ] **Step 1: Write failing tests** with `httpx.MockTransport` and a fake `sleep` recording calls:

```python
def test_429_raises_blocked_without_retry(): ...      # handler returns 429; assert SourceBlocked, 1 call
def test_5xx_retries_then_source_error(): ...         # 500 x3 → SourceError, 3 calls
def test_delay_between_requests(): ...                # two gets → sleep called once with 1.0 <= s <= 2.0
def test_user_agent_has_no_email(): ...               # header captured, "@" not in it
def test_paged_stops_at_known(): ...                  # pages [[a,b],[c,known],[d]] → returns a,b,c,known-parsed; page 3 never requested
def test_next_data_missing_raises_parse_error(): ...  # base.next_data("<html></html>") → ParseError, message contains "формат страницы изменился"
def test_nuxt_data_revives_references(): ...          # '[{"a":1},["Reactive",2],{"b":3},"x"]' → {"a": {"b": "x"}}
```

- [ ] **Step 2: Run** `uv run pytest tests/test_http.py -v` — expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** — expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: polite http client and source base"`.

---

### Task 5: Search (FTS5, stemming, synonyms)

**Files:**
- Create: `jobfinder/search.py`, `jobfinder/synonyms.toml`
- Modify: `jobfinder/db.py` (`connect` calls `search.ensure_fts`; `upsert_job` calls `search.index_job` after write)
- Test: `tests/test_search.py`

**Interfaces:**
- Consumes: `db.connect`, `db.upsert_job`, `db.get_setting`.
- Produces:
  - `search.ensure_fts(conn)` — `CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(body, tokenize='unicode61 remove_diacritics 2')` with `rowid = jobs.id`.
  - `search.stem_text(text: str) -> str` — tokens `[\w+#.]+`, lowercase, `ё→е`; Cyrillic tokens via `Stemmer.Stemmer("russian")`, others via `"english"`; tech tokens with symbols mapped to safe words first (`c++→cplusplus`, `c#→csharp`, `.net→dotnet`, `node.js→nodejs`).
  - `search.index_job(conn, job_id: int)` — body = stemmed `title + company + stack + description_text`.
  - `search.expand_query(q: str) -> str | None` — tokenize like `stem_text`; each token → OR-group of itself + synonyms from `synonyms.toml` (groups of equivalent terms, e.g. `["js","javascript"]`, `["k8s","kubernetes"]`, `["go","golang","голанг"]`, `["senior","старший","ведущий","сеньор"]`, `["middle","мидл"]`, `["junior","джун","младший","джуниор"]`, `["python","питон"]`, `["devops","девопс"]`, `["frontend","фронтенд"]`, `["backend","бэкенд","бекенд"]`); each term stemmed and double-quoted with a trailing `*`; groups joined with `AND`. Returns `None` for an empty query. Never emits raw user syntax.
  - `search.SearchParams` dataclass: `text: str = ""`, `section: str = "feed"` (`feed|mine|archive|hidden`), `sources: list[str] | None = None`, `langs: list[str] | None = None`, `scopes: list[str] | None = None`, `salary_min_usd: int | None = None`, `include_no_salary: bool = True`, `fresh_days: int | None = 3`, `limit: int = 50`, `offset: int = 0`.
  - `search.search_jobs(conn, p: SearchParams, now: datetime) -> list[dict]` — sections: `feed` = not archived, `hidden_reason IS NULL`, status not `rejected`, `first_seen_at >= now - fresh_days`; `mine` = status in (`interesting`,`applied`) regardless of age/archive; `archive` = `archived_at IS NOT NULL`; `hidden` = status `rejected` or `hidden_reason IS NOT NULL` (row includes the reason). Ordered by `first_seen_at DESC`. Each dict: `id, title, company, salary_raw, salary_min, salary_max, salary_currency, salary_period, remote_scope, location_raw, source_primary, lang, first_seen_at, status, hidden_reason`.
  - `search.count_sections(conn, p: SearchParams, now) -> dict[str, int]` for tab counters.

- [ ] **Step 1: Write failing tests:**

```python
def test_word_forms_ru(conn, now):
    add(conn, title="Python-разработчик")
    assert titles(search_jobs(conn, SearchParams(text="разработчика"), now)) == ["Python-разработчик"]

def test_synonyms(conn, now):
    add(conn, title="Senior Go Engineer", stack=["Kubernetes"])
    for q in ["голанг", "golang", "k8s", "старший"]:
        assert search_jobs(conn, SearchParams(text=q), now), q

@pytest.mark.parametrize("q", ['C++', 'C#', '.NET', 'node.js', '"', '*', '-', 'AND', 'NEAR(', "'; DROP TABLE jobs;--"])
def test_fts_special_input_never_raises(conn, now, q):   # Review Focus 4
    add(conn, title="C++ developer")
    search_jobs(conn, SearchParams(text=q), now)

def test_cplusplus_found(conn, now):
    add(conn, title="C++ developer"); add(conn, title="C developer", source_id="2")
    assert titles(search_jobs(conn, SearchParams(text="C++"), now)) == ["C++ developer"]

def test_sections(conn, now):
    a = add(conn, title="A"); b = add(conn, title="B", source_id="2"); c = add(conn, title="C", source_id="3", hidden="restricted")
    set_status(conn, b, "rejected", now)
    assert titles(search_jobs(conn, SearchParams(), now)) == ["A"]
    assert set(titles(search_jobs(conn, SearchParams(section="hidden"), now))) == {"B", "C"}

def test_salary_filter_uses_usd(conn, now):
    add(conn, title="RU", salary_raw="300 000 ₽"); add(conn, title="EN", source_id="2", salary_raw="$1,000 / month")
    assert titles(search_jobs(conn, SearchParams(salary_min_usd=2500, include_no_salary=False), now)) == ["RU"]
```

- [ ] **Step 2: Run** `uv run pytest tests/test_search.py -v` — expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces. Salary filter compares `COALESCE(salary_max, salary_min)` in `salary_usd_month` terms (yearly ÷ 12, hourly × 160).
- [ ] **Step 4: Run** full suite `uv run pytest -v` — expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: full-text search with stemming and synonyms"`.

---

### Task 6: Collector

**Files:**
- Create: `jobfinder/collector.py`
- Test: `tests/test_collector.py`

**Interfaces:**
- Consumes: `Source`, `PoliteClient`, `SourceBlocked`, `SourceError`, `ParseError`, `normalize_job`, `classify_scope`, `hidden_reason`, `FilterConfig`, `db.*`.
- Produces:
  - `collector.RunResult` dataclass: `source: str`, `ok: bool`, `fetched: int`, `new: int`, `skipped: int`, `requests: int` (from `client.requests`), `error: str | None`.
  - `collector.collect(conn, sources: dict[str, Source] | None = None, now_fn=lambda: datetime.now(UTC), client_factory=PoliteClient, only: str | None = None) -> list[RunResult]` — default `sources=REGISTRY`; skips names in setting `disabled_sources`; per source: `start_run`, build `wants` (`normalize → classify_scope → hidden_reason is None`), `fetch(client, known_source_ids, wants, settings)`; per job: drop if no `title`/`url` (count `skipped`), normalize, set scope/countries, compute `hidden_reason`, `upsert_job`; `finish_run`. Errors: `SourceBlocked` → `"сайт ограничил доступ (HTTP 429)"`-style message; `ParseError` → its message; `SourceError`/any other `Exception` → `str(exc)`; the next source still runs. A module-level `threading.Lock` makes concurrent `collect` calls return `[]` immediately.

- [ ] **Step 1: Write failing tests** with fake sources:

```python
def test_failing_source_does_not_stop_others(conn): # Review Focus 2
    res = collect(conn, sources={"bad": Raising(ParseError("формат страницы изменился: no __NEXT_DATA__")), "good": Fixed([job1])}, client_factory=FakeClient)
    assert [r.ok for r in res] == [False, True]
    assert "формат страницы изменился" in last_runs(conn)["bad"]["error"]

def test_blocked_source_message(conn): ...      # Raising(SourceBlocked(429)) → error contains "429"
def test_job_without_title_skipped(conn): ...   # skipped == 1, nothing inserted
def test_hidden_jobs_stored_with_reason(conn): ...  # location "USA Only" → row exists, hidden_reason == "restricted"
def test_disabled_source_not_run(conn): ...     # set_setting disabled_sources ["good"] → no run row for good
def test_wants_passed_to_source(conn): ...      # source records wants(job_us_only) is False, wants(job_worldwide) is True
```

- [ ] **Step 2: Run** `uv run pytest tests/test_collector.py -v` — expected: FAIL.
- [ ] **Step 3: Implement** per Interfaces.
- [ ] **Step 4: Run** — expected: PASS.
- [ ] **Step 5: Commit** `git commit -m "feat: collector with per-source isolation"`.

---

### Tasks 7–10: Sources — common pattern

Every source module:
1. Saves one real response into `tests/fixtures/` with the curl command given (use the Global Constraints UA: `curl -sL -A "$UA" '<url>' -o tests/fixtures/<file>`). Fixtures are committed.
2. Implements `parse_item(item) -> Job | None` (pure) and a module-level `parse_payload(payload) -> list[dict]` that extracts items from the raw response; `fetch()` = request(s) → `parse_payload` → `parse_item`, using `base.paged` when the site pages, and requesting detail pages only for jobs where `source_id not in known and wants(job)`.
3. Sets `raw=item`, `lang`, structured `countries`/`remote_scope`/`work_format`/`timezones` whenever the site provides them, `published_at` UTC.
4. Registers in `sources.REGISTRY`.
5. Tests (per source, from the fixture): `parse_payload` returns ≥ 1 item; first parsed `Job` has non-empty `title`, `url` starting with `https://`, `source_id`; plus the source-specific assertion listed below.

### Task 7: Open-API sources — Himalayas, RemoteOK, Jobicy, Working Nomads

**Files:** Create `jobfinder/sources/{himalayas,remoteok,jobicy,workingnomads}.py`, fixtures, `tests/test_sources_api.py`.

**Interfaces:** Consumes `Source`, `paged`, `PoliteClient`. Produces registry entries `himalayas`, `remoteok`, `jobicy`, `workingnomads` (all `lang="en"`).

| Source | Request | full_listing | Mapping notes | Specific test |
|---|---|---|---|---|
| himalayas | `https://himalayas.app/jobs/api/search?worldwide=true&q=<term>` for terms `developer, engineer, devops, data`, plus `page` param while paging | False | `locationRestrictions` → `countries` (map names to ISO-2; empty + worldwide → `worldwide`), `timezoneRestrictions` → `timezones`, salary min/max/currency/period from fields | worldwide job → `remote_scope == "worldwide"` |
| remoteok | `https://remoteok.com/api` (first element is legal notice — skip) | True | `location` → `location_raw`; `tags` → stack; `salary_min/max` USD year when non-zero | legal element skipped; `url` is the remoteok link |
| jobicy | `https://jobicy.com/api/v2/remote-jobs?count=100&industry=<slug>` for IT industry slugs listed by `https://jobicy.com/api/v2/remote-jobs?get=industries` (verify, store the chosen slugs as a module constant) | True | `jobGeo` → `location_raw`; `"Anywhere"` → `worldwide` | `jobGeo: "Anywhere"` → worldwide |
| workingnomads | `https://www.workingnomads.com/api/exposed_jobs/` | True | keep `category_name` in IT set (Development, DevOps, Data, QA, Design only if UI/UX dev); `location` (`Global`→worldwide, `USA only`→restricted) | non-IT category dropped by `parse_item` returning None |

- [ ] **Step 1:** capture four fixtures.
- [ ] **Step 2:** write the tests (common + specific). Run `uv run pytest tests/test_sources_api.py -v` — expected FAIL.
- [ ] **Step 3:** implement the four modules.
- [ ] **Step 4:** run — expected PASS.
- [ ] **Step 5:** commit `feat: himalayas, remoteok, jobicy, workingnomads sources`.

### Task 8: Feed sources — We Work Remotely, Remote First Jobs, HN Who is hiring

**Files:** Create `jobfinder/sources/{wwr,remotefirst,hn}.py`, fixtures, `tests/test_sources_rss.py`.

| Source | Request | full_listing | Mapping notes | Specific test |
|---|---|---|---|---|
| wwr | `https://weworkremotely.com/remote-jobs.rss` (one request) | True | title is `Company: Role` → split; `region` → `Anywhere in the World`=worldwide, `USA Only`=restricted; keep categories in IT set; description HTML from `description` | `"Anywhere in the World"` → worldwide; company split correct |
| remotefirst | RSS `https://remotefirstjobs.com/rss/jobs/<slug>.rss` for `software-development` and the DevOps/data/QA slugs present on the site (verify, module constant) | True | no country field → scope from text in Task 3 | items from two feeds deduped by link |
| hn | `https://hn.algolia.com/api/v1/search_by_date?tags=story,author_whoishiring&hitsPerPage=5` → newest title starting «Ask HN: Who is hiring?» → `https://hn.algolia.com/api/v1/search?tags=comment,story_<id>&hitsPerPage=1000` | True | top-level comments only (`parent_id == story_id`); keep if `remote` in text; first line split by `|` → company, title, location; url `https://news.ycombinator.com/item?id=<objectID>`; `source_id = objectID` | reply comments excluded; `"Acme | Backend Engineer | Remote (Global)"` → company `Acme`, title `Backend Engineer`, location_raw `Remote (Global)` |

HN collection runs with every collect but only issues the second request when the story id differs from setting `hn_last_story` or the last fetch was > 24 h ago (store both in settings).

- [ ] Steps 1–5 as in Task 7; commit `feat: wwr, remotefirst, hn sources`.

### Task 9: Embedded-JSON sources — Arc.dev, Remote Rocketship, Hirify

**Files:** Create `jobfinder/sources/{arc,rocketship,hirify}.py`, fixtures, `tests/test_sources_embedded.py`.

| Source | Request | full_listing | Mapping notes | Specific test |
|---|---|---|---|---|
| arc | `https://arc.dev/remote-jobs` (`base.next_data`) | False (first page only, `max_pages` effectively 1) | `requiredCountries` empty → worldwide, else `countries`; timezone/overlap → `timezones`; locate the jobs list inside `props.pageProps` by inspection and store the key path as a module constant | empty `requiredCountries` → worldwide |
| rocketship | `https://www.remoterocketship.com/country/worldwide/jobs/<role>` for roles `software-engineer, backend-engineer, frontend-engineer, devops-engineer, data-engineer` (verify slugs) | False (first page only) | `location: "Worldwide"` → worldwide, `locationCountries` → countries; `techStack` → stack; `isSenior/isJunior` → seniority | techStack mapped into stack |
| hirify | `https://hirify.me/?work_format=remote&vacancy_language=ru&hide_global_vacancies=1&specializations=<s>` for each IT specialization slug found in the page's filter data (module constant, e.g. `backend_dev`); **no `page` param** (robots) | False | `lang="ru"`; `regions` → countries/cis; `grades` → seniority; `tags` → stack; `work_format` → work_format; `source` kept in `raw` | specialization list built from constant; `work_format` mapped |

Each module raises `ParseError` when the expected list key is missing.

- [ ] **Step 1:** capture fixtures (one page per source).
- [ ] **Step 2:** tests: common + specific + `test_<source>_layout_change_raises` feeding `"<html><body>new design</body></html>"` and a valid `__NEXT_DATA__`/`__NUXT_DATA__` without the jobs key → `ParseError` with «формат страницы изменился» (Review Focus 2). Run — FAIL.
- [ ] **Step 3:** implement. **Step 4:** run — PASS. **Step 5:** commit `feat: arc, rocketship, hirify sources`.

### Task 10: Russian sites — hh.ru, Хабр Карьера, Getmatch

**Files:** Create `jobfinder/sources/{hh,habr,getmatch}.py`, fixtures, `tests/test_sources_ru.py`.

| Source | Request | full_listing | Mapping notes | Specific test |
|---|---|---|---|---|
| hh | **With** setting `hh_token`: `https://api.hh.ru/vacancies?schedule=remote&professional_role=<id>&per_page=100&page=<n>&order_by=publication_time` with `Authorization: Bearer <token>` for IT role ids from `https://api.hh.ru/professional_roles` (category «Информационные технологии»; module constant); detail `https://api.hh.ru/vacancies/<id>` for new wanted jobs. **Without** token: `https://hh.ru/search/vacancy?schedule=remote&professional_role=<id>&order_by=publication_time&items_on_page=50&page=<n>`; read the embedded initial-state JSON (inspect fixture; ParseError if missing); detail page `https://hh.ru/vacancy/<id>` for new wanted jobs, description from `[data-qa="vacancy-description"]` | False | `lang="ru"`; `salary.from/to/currency` (`RUR→RUB`); `work_format=remote`; `area.name` → location_raw; `key_skills` → stack | token path builds API URL with header (MockTransport asserts header); no-token path parses fixture |
| habr | `https://career.habr.com/api/frontend/vacancies?remote=true&type=all&sort=date&per_page=50&page=<n>`; detail page `https://career.habr.com/vacancies/<id>` (description `.vacancy-description__text` or embedded JSON — verify) for new wanted jobs | False | `lang="ru"`; salary from `salary` object; `skills` → stack; `qualification` → seniority; `company.title` | salary and skills mapped |
| getmatch | `https://getmatch.ru/api/offers?pa=all&limit=100&offset=<n*100>` | False | keep only offers where any `location_requirements[].format == "remote"`; `lang="ru"`; salary fields; `stack` field | non-remote offer → `parse_item` returns None |

- [ ] Steps 1–5 as in Task 7; commit `feat: hh, habr, getmatch sources`.

---

### Task 11: Archive, purge, reparse

**Files:**
- Create: `jobfinder/archive.py`
- Test: `tests/test_archive.py`

**Interfaces:**
- Consumes: `db.*`, `REGISTRY` (`full_listing`, `parse_item`), `normalize_job`, `classify_scope`, `hidden_reason`, `search.index_job`.
- Produces:
  - `archive.archive_stale(conn, now: datetime, sources: dict[str, Source] | None = None) -> int` — Global Constraints archive rule; sets `archived_at=now`; returns count.
  - `archive.purge_raw(conn, now: datetime) -> int` — `raw=NULL` on postings of jobs archived more than `purge_days` ago whose status is `new` or `seen`.
  - `archive.reparse(conn, source: str | None = None) -> int` — for postings with `raw`, `parse_item(json.loads(zlib.decompress(raw)))`, normalize, re-filter, update the job's parsed fields and FTS row; does not change `first_seen_at`, `last_seen_at`, statuses.

- [ ] **Step 1: Write failing tests:**

```python
def test_full_listing_job_archived_after_7_days_when_source_healthy(conn, now): ...
def test_not_archived_when_source_failing(conn, now):   # all runs of the source in last 7 days failed → stays active
def test_incremental_source_archived_after_30_days(conn, now): ...
def test_job_with_two_postings_needs_both_stale(conn, now): ...
def test_purge_keeps_marked_jobs(conn, now):            # interesting job archived 100 days ago keeps raw; seen job loses raw
def test_reparse_updates_fields_keeps_status(conn, now):  # change a source's parse_item output, reparse → new title, status unchanged
```

- [ ] **Step 2: Run** `uv run pytest tests/test_archive.py -v` — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: archive, raw purge, reparse`.

---

### Task 12: Web — feed screen (A) with detail panel

**Files:**
- Create: `jobfinder/web/app.py`, `jobfinder/web/templates/{base,feed,_list,_detail}.html`, `jobfinder/web/static/{style.css,htmx.min.js}`
- Test: `tests/test_web.py`

**Interfaces:**
- Consumes: `db.connect/get_job/set_status/get_setting`, `search.SearchParams/search_jobs/count_sections`.
- Produces:
  - `web.app.create_app(db_path: Path | str, start_scheduler: bool = True) -> FastAPI` (Task 13 adds the scheduler; here the flag is accepted and ignored).
  - Routes: `GET /` (query params: `q, section, src (multi), lang (multi), scope (multi), salary, nosalary, fresh, job`) → full page, layout as mockup A; `GET /list` → `_list.html` partial (HTMX target on filter change, `hx-push-url`); `GET /jobs/{id}` → `_detail.html` partial, and marks `new → seen`; `POST /jobs/{id}/status` form `status` → `_detail.html` partial with `HX-Trigger: list-changed`.
  - `review_links(company: str) -> list[dict]` in `app.py`: Glassdoor `https://www.glassdoor.com/Search/results.htm?keyword=<q>`, Dreamjob `https://dreamjob.ru/search?query=<q>`, Хабр Карьера `https://career.habr.com/companies?q=<q>`, Google `https://www.google.com/search?q=<q>+отзывы+сотрудников`, Reddit `https://www.reddit.com/search/?q=<q>`; `<q>` url-encoded; opened with `target="_blank" rel="noopener"`.
  - Description rendered through `nh3.clean(description_html)` and Jinja `|safe` only after cleaning; everything else autoescaped.
  - Detail panel shows: source + age, title, company, salary (or «не указана»), «где можно работать» (scope label: весь мир / СНГ / страны: … / «уточнить» for unknown), seniority, language, stack tags, «Открыть на <source>» button (+ other postings' links), «Найти отзывы о компании» dropdown, status buttons Посмотрел / Интересно / Откликнулся / Не подходит, full description, hidden reason when in «Скрытые».
  - Tabs: Лента, Мои, Архив, Скрытые with counts.
  - `style.css` carries the qymyz.dev tokens as CSS variables (values in Global Constraints and mockups), Google Fonts link in `base.html`; `htmx.min.js` vendored (download htmx 2.0.x once, commit the file).

- [ ] **Step 1: Write failing tests** with `fastapi.testclient.TestClient` on a temp DB seeded via `upsert_job`:

```python
def test_feed_renders_jobs(client, seeded): assert "Python Developer" in client.get("/").text
def test_open_marks_seen(client, seeded):   client.get(f"/jobs/{jid}"); assert get_status(conn, jid) == "seen"
def test_status_change_persists(client, seeded):
    r = client.post(f"/jobs/{jid}/status", data={"status": "applied"}); assert r.status_code == 200
    assert get_status(conn, jid) == "applied"
def test_bad_status_rejected(client, seeded): assert client.post(f"/jobs/{jid}/status", data={"status": "x"}).status_code == 422
def test_search_special_chars_no_500(client, seeded):
    for q in ['C++', '"', 'NEAR(']: assert client.get("/list", params={"q": q}).status_code == 200
def test_description_sanitized(client, conn):   # Review Focus 5
    jid = seed(conn, description_html='<p>ok</p><script>alert(1)</script><img src=x onerror="alert(2)">')
    html = client.get(f"/jobs/{jid}").text
    assert "<script>alert(1)" not in html and "onerror" not in html and "<p>ok</p>" in html
def test_review_links_encode_company(): assert "Northwind%20Labs" in review_links("Northwind Labs")[0]["href"]
def test_unknown_job_404(client): assert client.get("/jobs/999999").status_code == 404
```

- [ ] **Step 2: Run** `uv run pytest tests/test_web.py -v` — FAIL. **Step 3: Implement.** **Step 4: Run** — PASS.
- [ ] **Step 5: Commit** `feat: feed screen with detail panel`.

---

### Task 13: Triage (C), Sources & settings (D), scheduler, CLI

**Files:**
- Create: `jobfinder/web/templates/{triage,sources}.html`, `jobfinder/web/static/keys.js`, `jobfinder/scheduler.py`, `jobfinder/cli.py`
- Modify: `jobfinder/web/app.py`
- Test: extend `tests/test_web.py`; `tests/test_cli.py`

**Interfaces:**
- Consumes: everything above; `collector.collect`, `archive.archive_stale/purge_raw/reparse`, `REGISTRY`.
- Produces:
  - `GET /triage` → next job in the feed section with status `new` (oldest first), counter «N из M» (M = new jobs when the triage session started = count of `new` + already decided today; simplest acceptable: decided-today / (decided-today + remaining new)); empty state «Новых вакансий нет». `POST /triage/{id}` form `action` in `reject|later|interesting` → status `rejected|seen|interesting`, returns next card (HTMX swap). `keys.js`: ←/↓/→ click the matching buttons; ignored while focus is in an input.
  - `GET /sources` → table per `REGISTRY` source: name, lang, method label (`Source.method`), last run time, new count, state (ok / error text / «выключен»), enable checkbox; settings form: interval hours (1–24), stop-words (comma-separated), hh token (password field), freshness days. `POST /sources/{name}/toggle`, `POST /settings` (validates ranges; 422 on bad input), `POST /collect` → starts `collect` in a background thread (returns immediately; if already running, says «Сбор уже идёт»).
  - `scheduler.start_scheduler(db_path) -> BackgroundScheduler` — job `collect` every `interval_hours` (first run 10 s after start), job `archive_stale + purge_raw` daily; each job opens its own connection; rescheduled when `interval_hours` changes (`POST /settings` calls `scheduler.reschedule(hours)`).
  - `create_app(..., start_scheduler=True)` starts/stops the scheduler in FastAPI lifespan.
  - `cli.main()` (argparse): `serve [--port 8000]` (uvicorn on 127.0.0.1, prints the URL), `collect [--source NAME]` (prints one line per source: name, ok/error, fetched, new, requests), `check-sources` (runs each source live with `max_pages=1`, prints item count or error, writes nothing to the DB), `reparse [--source NAME]`. DB path `data/jobs.db` relative to the project root (`--db` override).

- [ ] **Step 1: Write failing tests:**

```python
def test_triage_shows_new_and_advances(client, seeded2):
    first = client.get("/triage").text
    r = client.post(f"/triage/{j1}", data={"action": "interesting"})
    assert get_status(conn, j1) == "interesting" and "Go Developer" in r.text
def test_triage_later_is_seen(client, seeded2): ...
def test_triage_empty_state(client, conn): assert "Новых вакансий нет" in client.get("/triage").text
def test_sources_page_lists_registry(client): assert all(n in client.get("/sources").text for n in REGISTRY)
def test_sources_page_shows_last_error(client, conn): ...   # finish_run(..., error="HTTP 429") → text visible
def test_settings_validation(client): assert client.post("/settings", data={"interval_hours": "0"}).status_code == 422
def test_toggle_source(client, conn): client.post("/sources/remoteok/toggle"); assert "remoteok" in get_setting(conn, "disabled_sources")
def test_cli_collect_prints_per_source(monkeypatch, capsys, tmp_path): ...  # REGISTRY patched to one fake source
```

- [ ] **Step 2: Run** `uv run pytest -v` — new tests FAIL. **Step 3: Implement.** **Step 4: Run** — all PASS.
- [ ] **Step 5: Commit** `feat: triage, sources screen, scheduler, cli`.

---

### Task 14: Live check, README, first real run

**Files:**
- Create: `README.md` (Russian: what it is, `uv sync`, `uv run jobfinder serve`, where the DB lives, how to get an hh token at dev.hh.ru and paste it on «Источники», commands list)

- [ ] **Step 1:** Run `uv run jobfinder check-sources` — expected: each of the 13 sources prints a positive count or a clear error. Fix any parser whose live page differs from its fixture (refresh the fixture, keep tests green).
- [ ] **Step 2:** Run `uv run jobfinder collect` — expected: per-source lines, most `ok`, total new > 0. Run it again — expected: `new` near 0 and each source stopped after 1–2 pages (the `collect` output prints `requests` per source).
- [ ] **Step 3:** Run `uv run jobfinder serve`, open `http://127.0.0.1:8000`: feed shows jobs, detail panel, statuses persist after reload, triage keys work, «Источники» shows last runs.
- [ ] **Step 4:** Report DB size after the first collection (`du -h data/jobs.db`) to calibrate the storage estimate.
- [ ] **Step 5:** `uv run pytest -v` all green; commit `docs: README; fixtures refreshed`.
