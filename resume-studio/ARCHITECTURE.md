# Resume Matcher — Architecture Breakdown

Reverse-engineered from source: `github.com/srbhr/Resume-Matcher` (v1.4 "Short Circuit", Apache-2.0, ~28k stars).
Purpose of this document: (1) explain how the real system works, (2) serve as the blueprint for a full-featured reimplementation in a single Next.js full-stack app with multi-provider AI.

---

## 1. System topology

```
┌─────────────────────────────────────────────────────────────┐
│ Docker container (single published port :3000)              │
│                                                             │
│  ┌──────────────────┐   /api/* rewrites    ┌─────────────┐  │
│  │ Next.js 16 UI    │ ───────────────────▶ │ FastAPI     │  │
│  │ (React 19,       │   (next.config.ts)   │ (uvicorn)   │  │
│  │  Tailwind 4)     │                       │ :8000       │  │
│  └────────┬─────────┘                       └──────┬──────┘  │
│           │                                        │         │
│   /print/resumes/[id]              ┌──────────────┼──────┐  │
│   /print/cover-letter/[id] ◀───────┤ Playwright   │      │  │
│   (hidden print routes)            │ (Chromium)   │      │  │
│                                    └──────────────┼──────┘  │
│  SQLite file (data/) ◀── SQLAlchemy/aiosqlite ───┘         │
│  (optional PostgreSQL via docker-compose.postgres.yml)      │
└─────────────────────────────────────────────────────────────┘
          │                              │
          ▼                              ▼
   LiteLLM ──▶ OpenAI / Anthropic /   MCP server (stdio)
   Gemini / DeepSeek / OpenRouter /   ── Claude Code, Cursor,
   Groq / Azure / Ollama (local)         Codex drive the app
```

Key decisions worth copying:

| Decision | Why it exists |
|---|---|
| One published port; Next.js proxies `/api/*` to FastAPI | Zero CORS pain in the common case; single `docker compose up` |
| PDF = headless Chromium screenshotting a **frontend print route** | One template codebase renders preview *and* PDF; pixel-identical output |
| SQLite by default, Postgres optional | "Private by default" — everything in one local file |
| All AI calls go through one `complete_json()` chokepoint | Uniform retries, JSON repair, token budgets, timeouts across 8 providers |
| Scores are plain deterministic code, never LLM output | Trustworthy ATS score; cheap to recompute |

---

## 2. Data model (`apps/backend/app/models.py`)

Six tables, all facade'd through `app/database.py` (returns plain dicts, no ORM objects leak):

| Table | Role | Notable columns |
|---|---|---|
| `resumes` | Master **and** tailored resumes | `is_master`, `parent_id` (tailored → master lineage), `content` (markdown *or* JSON), `processed_data` (structured `ResumeData`), `processing_status`, `original_markdown` (kept forever as ground truth), `cover_letter`, `outreach_message`, `interview_prep`, `title`, `template_settings` (JSON), partial unique index ⇒ at most one `is_default_master` |
| `jobs` | Pasted job descriptions | `content`, `metadata_json` holds cached `job_keywords` + `job_keywords_hash`, extracted `company`/`role` |
| `improvements` | One row per completed tailoring | `original_resume_id`, `tailored_resume_id`, `job_id`, `ats_score` (JSON snapshot), `forced_keywords` |
| `tailoring_previews` | The "nothing is saved until you confirm" mechanism | `payload_hash`, `source_hash`, `job_hash`, `expires_at` (TTL), `claim_token`/`claim_expires_at` (lease), `response_data` (durable replay), `source_data` (condensed bullet-selected source) |
| `applications` | Kanban tracker cards | unique `(job_id, resume_id)` — idempotent auto-creation of cards on confirm |
| `api_keys` | LLM provider keys, **ciphertext only** | `provider` + encrypted blob (AES via `app/crypto.py`) |
| `queue_items` | Sequential bulk-tailoring queue | `status`, `rate_limit_seconds` (default 5s), `prompt_id` |

The `ResumeData` schema (Pydantic in `app/schemas/models.py`, mirrored in TypeScript at `components/dashboard/resume-component.tsx:153`) is the canonical interchange format for everything:

```
ResumeData
├── personalInfo        { name, title, email, phone, location, website, linkedin, github }
├── summary             string                                  (sectionType: text)
├── workExperience[]    { title, company, location, years, description[], descriptionStyles[] }
├── education[]         { institution, degree, years, description }
├── personalProjects[]  { title, description[], descriptionStyles[], years }
├── skills[]            string[]                                 (sectionType: stringList)
├── certifications[] / languages[] / awards[]
├── customSections[]    arbitrary user-defined sections, structure-protected
└── sectionMeta[]       { key, isVisible, label } — visibility & ordering
```

Every bullet list carries a parallel `descriptionStyles: ("bullet" | "plain")[]` array that must stay index-aligned with `description` — a contract the prompts and validators enforce repeatedly.

---

## 3. Ingestion: file → structured resume

`POST /api/v1/resumes/upload` (`app/routers/resumes.py:1042`):

1. **Validate** file type/size; **bounded decode**. `app/services/parser.py` subclasses pdfminer with hard budgets (`_PDFDecodeBudget`, bounded Flate/LZW/CCITT decoders, `MAX_UNPACKED_DOCUMENT_BYTES`, page-count preflight) — this is zip-bomb / crypto-bomb defense, not parsing logic.
2. **Extract text** via MarkItDown (+ python-docx) → Markdown. Image-only PDFs are rejected with an "run OCR first" message.
3. **Insert row** with `processing_status="processing"`, `original_markdown` saved permanently.
4. **LLM parse**: `parse_resume_to_json()` (`parser.py:1029`) — `PARSE_RESUME_PROMPT` + a full `RESUME_SCHEMA_EXAMPLE` (few-shot JSON shape), system prompt "You are a JSON extraction engine", 3 retries, Pydantic validation.
5. **Post-LLM repair** (the recurring theme — never trust the model):
   - `restore_dates_from_markdown()` — patches year-only dates back to month-inclusive ones found in the raw markdown;
   - `restore_skills_from_markdown()` — re-adds skills the LLM summarized away from long skill lines.

---

## 4. The tailoring pipeline (the core of the product)

Two entry points share one flow:

- `POST /resumes/improve/preview` → `_improve_preview_flow()` (`routers/resumes.py:1376`) — interactive, diff-review UI, saves nothing.
- `execute_tailoring_pipeline()` (`routers/resumes.py:2062`) — used by the bulk **queue worker** and the **MCP server**; saves directly (no human review), then auto-creates the tracker card.

Stages (progress is streamed to the UI via `GET /improve/progress/{id}` SSE):

```
JD text ──▶ (1) keyword extraction (LLM, cached by content hash)
master ResumeData ──▶ (2) bullet selection / page fit (optional)
                   ──▶ (3) skill-target planning (LLM propose → code verify)
                   ──▶ (4) diff generation (LLM emits CHANGES, not a resume)
                   ──▶ (5) apply_diffs (path-whitelisted JSON edits)
                   ──▶ (6) preservation safety nets (code)
                   ──▶ (7) refinement loop (multi-pass, LLM+code)
                   ──▶ (8) writing-quality loop (AI critic + fact check)
                   ──▶ (9) finalize_ai_resume (grounding contract)
                   ──▶ (10) final page-count check (Playwright)
                   ──▶ (11) register preview (hashed, TTL) — STILL UNSAVED
```

### 4.1 Keyword extraction
LLM call with cached result stored on the job row (`job_keywords` + `job_keywords_hash`); re-extracted only when the JD text hash changes. The cache also lets the builder recompute the ATS score later without another call.

### 4.2 Bullet selection & page fit (`services/bullet_selector.py`)
Optional per-request knobs: `max_bullets_per_entry`, `page_fit` ("fits"/"trimmed" one page etc.), `max_pages`. An LLM scores each bullet's relevance to the JD (`BULLET_RELEVANCE_PROMPT`); the harness then keeps the top-N bullets per entry in `SELECTABLE_SECTIONS = ("workExperience", "personalProjects")`. The **condensed** resume replaces the master for all downstream steps, so preservation contracts still hold at confirm time. This is the "8 of 14 bullets were kept to fit the page limit" feature.

### 4.3 Skill-target planning (`improver.py:1031`)
LLM proposes which JD keywords/skills to weave in; `verify_skill_target_plan()` (`improver.py:946`) **rejects any target the resume can't support** (skill must already exist somewhere in the resume text or be legitimately derivable). Rejected targets surface as user warnings. Downstream, `apply_diffs` receives the accepted list as `allowed_skill_targets` — an injection outside that list is dropped.

### 4.4 Diff generation instead of full rewrite (`prompts/templates.py:638`)
The LLM does **not** return a whole resume. `DIFF_IMPROVE_PROMPT` returns a JSON list of targeted changes (`generate_resume_diffs`, `improver.py:722`). Four selectable aggressiveness strategies — `nudge`, `keywords` (default), `full`, `heavy` — each with its own prompt *and* its own rule 7 in the truthfulness block; `heavy` alone is allowed to reorder bullets.

### 4.5 Applying diffs — the security kernel (`apply_diffs`, `improver.py:368`, the highest fan-in function in the codebase)
- Changes address fields by **JSON path**, matched against `_ALLOWED_PATH_PATTERNS` (whitelist), with `_BLOCKED_PATH_PREFIXES` and `_BLOCKED_FIELD_NAMES` (e.g. `personalInfo`, `years`).
- `_verify_original_matches()` — the change must quote the original value it claims to replace; mismatch ⇒ rejected.
- Metric guard `_METRIC_RE` — new numbers that weren't in the original are stripped/rejected (no invented "30%").
- `fixed_row_sections` — when the harness chose the bullet set, `append` actions on those sections are refused (no new bullets sneaked in).
- Every applied/rejected change is returned and shown in the review dialog as the before/after diff.

### 4.6 Preservation safety nets (pure code, `routers/resumes.py:1519+`)
Even after verified diffs: `_preserve_personal_info`, `_restore_original_dates` (+ `restore_dates_from_markdown` against the permanently stored `original_markdown`), `_preserve_original_skills` (skills are a union — the model may reorder but never drop), `_protect_custom_sections`.

### 4.7 Refinement loop (`services/refiner.py`, ~900 lines)
Multi-pass improvement with a `RefinementConfig` budget: keyword injection where a keyword is supported but missing, **AI-phrase removal** ("spearheaded", "leveraged"…), alignment re-validation against the master resume. Produces `RefinementStats` (pass count, phrases removed, keyword match before/after) shown in the UI.

### 4.8 Writing loop (`services/writing_loop.py`)
Code rules + an AI critic pass over the text; every candidate rewrite must pass a **fact check or it is dropped**. Emits a writing report surfaced in the review dialog.

### 4.9 Grounding finalize (`services/resume_preservation.py:finalize_ai_resume`)
Last-line contract enforcement before anything leaves the pipeline; `grounding_review_warnings()` flags anything suspicious (e.g. identity changes, high-risk edits) for the review dialog.

### 4.10 Page-fit verification
If page-fit was requested, the final resume is rendered (Playwright) once more to count pages; overflow becomes a user warning.

---

## 5. The preview / confirm protocol (why "nothing is saved until you confirm" is honest)

**Preview** (`POST /improve/preview`):
- After the pipeline, `db.register_preview()` stores `payload_hash = sha256(improved_data)`, `source_hash`, `job_hash`, a TTL, and the improvements list. No resume row is created. The response carries `preview_id`, the full tailored `ResumeData`, a computed diff summary (`calculate_resume_diff`, `improver.py:1395` — structural, section-aware, feeds the review dialog), the ATS score, refinement stats, writing report, and warnings.

**Confirm** (`POST /improve/confirm`, `routers/resumes.py:1869`):
1. `db.claim_preview()` — lease-based, **idempotent**: if this preview was already confirmed, the stored `response_data` is replayed verbatim (no duplicate work, no duplicate rows, safe retries).
2. Client-sent `improved_data` is re-hashed and must equal the registered `payload_hash`, **and** is re-run through `finalize_ai_resume` + `_validate_confirm_payload` server-side ⇒ the review UI's "Reject & Regenerate / Confirm & Save" cannot be bypassed by a tampered client.
3. Auxiliary generation (bounded by the request deadline): cover letter, outreach message, interview-prep, auto-title — each its own prompt (`prompts/templates.py:406-561`), all grounded in resume + JD, language-aware.
4. `db.complete_preview()` — single transaction: create the tailored resume row (`parent_id` = master, `content` = JSON, `processing_status="ready"`, template settings inherited), store the ATS snapshot on `improvements`, merge user-forced keywords into master skills.
5. `_auto_create_tracker_application()` — the Kanban card appears (unique constraint dedupes races).

Hash mismatches ⇒ 409/400; busy DB ⇒ 503 + Retry-After; every claim is released in `finally`.

---

## 6. LLM layer (`app/llm.py`, ~2,000 lines)

- **LiteLLM** underneath; provider normalization (`_normalize_api_base` handles Azure Foundry, OpenCode-Zen, Ollama base URLs, `openai-compatible` endpoints).
- `complete_json()` is the only door: JSON-mode when the provider supports it, otherwise `_extract_json()` repairs fenced/markdown-wrapped/truncated JSON; retries with temperature fallback; `_appears_truncated()` detection; `get_safe_max_tokens()` per model; `response_validator` hooks let callers reject semantically-bad outputs and retry.
- Per-operation **token budgets and deadlines** (`ai_budget.py`, `ai_limits.py`, `AIOperationRoute` route class) — a slow local Ollama can't wedge the server; oversized prompts raise `PromptSizeError` instead of burning money.
- `check_llm_health()` powers the Settings UI status dot.
- Keys: encrypted at rest (`api_keys` table, AES via `crypto.py`), env-var fallback, secrets scrubbed from logs (`_scrub_secrets`).

## 7. Scoring — deterministic, no LLM

**ATS score** (`services/ats.py`): weighted composite, weights redistributed when a component is `None`:

| Component | Weight | Measures |
|---|---|---|
| keyword_match | 0.40 | final keyword match % from the refinement pipeline |
| skills_coverage | 0.20 | resume skills ∩ JD required skills |
| title_match | 0.15 | exact JD title in headline (100) > summary (75) > word overlap (50) |
| section_completeness | 0.15 | contact info + essential sections present *and visible* |
| date_consistency | 0.10 | single date format across the resume |

Scores only what an ATS would actually parse: hidden sections (`sectionMeta.isVisible=false`) and non-rendered config are excluded from scoring.

**ATS check** (`services/ats_parse/`): round-trips your *exported PDF* through pdfminer the way an ATS text extractor would (headings, normalization, column detection) and flags anything an ATS can't read. Pure code.

## 8. PDF export (`app/pdf.py` + frontend `/print/*` routes)

`render_resume_pdf()` launches/keeps a pooled headless Chromium, navigates to the Next.js print route (`/print/resumes/[id]`), waits for data, verifies no `data-print-error` attribute, then `page.pdf()` with `print_background`. The print route authenticates via short-lived draft tokens (`/render-drafts/{token}`), locks navigation to same-origin, and closes foreign sockets. Render slots + browser quarantine/restart keep a crashed Chromium from poisoning the app. One template codebase ⇒ preview and PDF are pixel-identical.

## 9. Everything else

- **Queue worker** (`services/queue_worker.py`): sequential processing of `queue_items` (paste many JDs at once), per-item rate limit, writes results via `execute_tailoring_pipeline`, surfaces errors per item. UI at `/queue`.
- **Enrichment** (`routers/enrichment.py`, ~1,000 lines): an interview-style Q&A about your real work; answers become stronger bullets **in the master resume**, so every future tailoring starts better.
- **Resume wizard** (`services/resume_wizard.py` + prompts): build a master resume from scratch through guided questions.
- **MCP server** (`app/mcp_server/`, 25+ tools: `add_job`, `create_master_resume`, `tailor_and_verify`, `save_tailored_resume`, `export_resume_pdf`, `score_resume`, `parse_check_resume`, …): external agents (Claude Code/Cursor/Codex) drive the whole app; Resume Matcher then acts as storage/scoring/rendering with **no LLM key needed**.
- **Frontend** (`apps/frontend`): App Router, route group `(default)` = dashboard / tailor / builder / resumes / resume-wizard / settings / tracker / queue; `lib/api/*` typed clients with a shared timeout constant kept in sync across client/proxy/server; builder = section editors + live paginated preview + template picker (clean, modern, two-column, vivid, deedy, modern-deedy, LaTeX-style…); JD Match tab renders highlighted keyword views (`highlighted-resume-view`, `jd-comparison-view`); tracker = dnd-kit Kanban; i18n = 7 locales via `messages/`; state persisted as local drafts until saved.
- **Hardening details worth copying**: HostGuard middleware (rejects foreign Host headers), CORS from config, Windows ProactorEventLoop for Playwright, graceful ordered shutdown (queue → cleanup → browser → DB), `DatabaseBusyError` → 503 + Retry-After, legacy TinyDB→SQLite and plaintext-key→encrypted migrations at startup, fail-fast on migration errors.

---

## 10. Blueprint: rebuilding it as one Next.js full-stack app

Target: same features, single Next.js app (App Router + Route Handlers), multi-provider AI, local-first.

### 10.1 Stack mapping

| Original | Rebuild | Notes |
|---|---|---|
| FastAPI routers | `app/api/v1/**/route.ts` (Node runtime) | Keep the `/api/v1` prefix; the frontend `lib/api` layer ports almost 1:1 |
| SQLAlchemy + aiosqlite + SQLite | Drizzle ORM + better-sqlite3 (libsql for Postgres later) | Keep the exact table shapes (§2); the preview/claim/lease semantics are the hard part — port them literally |
| Pydantic schemas | Zod schemas shared client/server | Single `resume-data.ts` with the `ResumeData` tree + `descriptionStyles` contract |
| LiteLLM `complete_json` | **Vercel AI SDK** `generateObject()` + provider registry | Covers OpenAI/Anthropic/Gemini/DeepSeek/OpenRouter/Groq/Ollama/OpenAI-compatible; AI SDK already handles schema-constrained output and retries; add your own token/deadline budget wrapper |
| markitdown + python-docx + bounded pdfminer | `mammoth` (DOCX→HTML/text) + `pdf-parse`/PDF.js | Keep upload size caps; you can skip the deep decode-budget hardening for v1 (add page + byte limits) |
| Playwright + print routes | Keep the pattern: `playwright-core` + hidden `/print/*` routes + `page.pdf()` | The single-template trick is too good to give up; alternative: `@react-pdf/renderer` (faster, but a second template codebase) |
| MCP server (Python) | `@modelcontextprotocol/sdk` server calling the same Route Handlers | Tool list in §9 ports directly |
| SSE progress | Route Handler streaming (`ReadableStream`) | Same stage-keyed progress events |
| Queue worker | DB-backed `queue_items` + in-process interval worker in a singleton module (or a tiny `worker.ts` run via `tsx` in the same container) | Sequential + rate-limited is deliberate — keep it |

### 10.2 What to port verbatim (pure logic, no I/O — highest value per line)

1. **`apply_diffs` + path whitelists** (`improver.py:368-626`) — the anti-hallucination kernel.
2. **Truthfulness prompt blocks** (`templates.py:212-244`) — battle-tested wording; keep the 4-strategy split.
3. **Preservation functions** — personal info, dates, skills-union, custom-section protection, `finalize_ai_resume` contract.
4. **Preview/confirm hashing + claim/lease/replay** — copy the state machine, including "re-run finalize server-side at confirm".
5. **ATS weights + keyword/title/date heuristics** (`ats.py`) — deterministic, cheap, trustworthy.
6. **`calculate_resume_diff`** — powers the review dialog; section-aware structural diff, not text diff.
7. **`restore_dates_from_markdown` / `restore_skills_from_markdown`** — post-parse repair.

### 10.3 Pipeline as Next.js code

```
lib/tailor/
  keywords.ts        extract + cache by JD hash
  bullets.ts         relevance scoring + page-fit selection
  skill-targets.ts   propose → verify against master
  diffs.ts           prompt → changes[] (zod-validated)
  apply.ts           whitelisted path edits + verification   ← port of apply_diffs
  preserve.ts        safety nets + finalize contract
  refine.ts          keyword injection + AI-phrase removal loop
  writing.ts         critic pass + fact check
  run.ts             stage orchestration, emits progress events
app/api/v1/resumes/improve/preview/route.ts   → registers preview row, returns diff + ATS + stats
app/api/v1/resumes/improve/confirm/route.ts   → claim/lease/replay + aux generation + transaction
```

### 10.4 Build order (tracer bullets)

1. Schema (`ResumeData` zod) + DB + upload → markdown → LLM parse → builder with live preview + one template + PDF export. *(End-to-end value first.)*
2. JD ingestion + keyword extraction + JD Match tab + ATS score (deterministic parts only).
3. Tailoring: diff generation + `apply.ts` + preservation + preview/confirm + review dialog.
4. Tracker (auto-cards on confirm) + templates 2-7.
5. Refinement + writing loops; page-fit bullet selection.
6. Queue, enrichment Q&A, resume wizard, cover letter/outreach/interview prep.
7. MCP server + i18n + encrypted key store + HostGuard middleware.

### 10.5 Honest difficulty notes

- **Hard:** the preview claim/lease/replay transaction; diff path security; page-count measurement requires a real browser; keeping `descriptionStyles` aligned everywhere; token budgets across 8 providers.
- **Easier than it looks:** ATS scoring, keyword matching, tracker, templates (they're just React components over `ResumeData`), the API surface.
- **De-scoping options for v1:** queue (use preview flow only), enrichment, MCP, multi-language.

---

## Appendix: source map

| Concern | File |
|---|---|
| App wiring, ordered shutdown | `apps/backend/app/main.py` |
| Upload, improve preview/confirm, pipeline entry | `apps/backend/app/routers/resumes.py` (3,200 lines) |
| Diff engine, skill targets, structural diff | `apps/backend/app/services/improver.py` |
| Grounding contract | `apps/backend/app/services/resume_preservation.py` |
| Refinement / writing loops | `services/refiner.py`, `services/writing_loop.py` |
| Prompts (all) | `apps/backend/app/prompts/templates.py` |
| LLM chokepoint | `apps/backend/app/llm.py` (`complete_json`:1857) |
| Parser + repair | `apps/backend/app/services/parser.py` |
| ATS score / ATS check | `services/ats.py`, `services/ats_parse/` |
| PDF via Chromium | `apps/backend/app/pdf.py` |
| Tables | `apps/backend/app/models.py` |
| Proxy config | `apps/frontend/next.config.ts` |
| Typed API clients | `apps/frontend/lib/api/*` |
| Resume templates | `apps/frontend/components/resume/*` |
| Review UI / builder / tracker | `components/tailor/*`, `components/builder/*`, `components/tracker/*` |
