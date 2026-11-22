# Resume Studio

Local-first AI resume builder — a reimplementation of Resume-Matcher's core loop (see `ARCHITECTURE.md`) as a single Next.js app.

**Current scope (steps 1–2):** master resume ingestion (PDF/DOCX/paste) → LLM parse into a structured schema → visual builder with live preview and 2 templates → pixel-identical PDF export via headless Chromium. JD Match: paste job descriptions, LLM keyword extraction (cached by content hash), deterministic ATS score (keyword match, skills coverage, title match, section completeness, date consistency) and a highlighted keyword view. Multi-provider AI (OpenAI, Anthropic, Gemini, DeepSeek, OpenRouter, Groq, Ollama, any OpenAI-compatible endpoint), keys encrypted at rest, everything stored in a local SQLite file.

## Run

```bash
npm install
npx playwright install chromium   # only if no Playwright browser is present
npm run dev                       # http://localhost:3000
```

Then open **Settings**, pick a provider (or point it at a local Ollama), and upload your resume.

## Local-only by design

Resume Studio answers only this computer: the dev and production servers bind to `127.0.0.1`, and `proxy.ts` refuses API and print requests whose `Host` is not loopback (other machines, DNS rebinding) and state-changing requests from any other origin — even another app on this computer (the `Origin` must be exactly this host and port; `Sec-Fetch-Site`, when sent, must be `same-origin` or `none`). Requests without those headers — curl, Job Finder server-to-server — pass. The saved API key is used by «Test connection» only for the provider and base URL it was saved for. The PDF printer's headless browser may load nothing outside the print page's own origin.

## Scripts

| Command | Purpose |
|---|---|
| `npm run dev` / `build` / `start` | usual Next.js lifecycle |
| `npm run typecheck` / `lint` | tsc / oxlint |
| `npm run mock-llm` | mock OpenAI-compatible server on :8787 for e2e testing without an API key |
| `npm run sample:resume` | generates `data/sample-resume.pdf` for upload testing |

## Environment

See `.env.example`. Env vars (`LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, `LLM_API_BASE`) override Settings-UI values; `DATA_DIR` moves the SQLite database.

## Layout

```
lib/            schema (zod), db (SQLite facade), crypto, settings, llm,
                parse-doc, parse-resume (+repairs), pdf-render (Playwright),
                ats (deterministic scoring), text-match, tailor/keywords
                (JD extraction + hash cache)
app/api/v1/     health, settings, resumes CRUD, upload, retry, pdf,
                jobs CRUD, ats (score resume × job)
app/builder/    two-pane editor + live preview
app/match/      JD Match — paste a JD, ATS score + keyword highlighting
app/print/      Chromium-printed PDF route (token-gated)
components/     resume templates (classic/modern), builder editors,
                match score card + highlighted resume view
```

Roadmap (steps 3–7 in `ARCHITECTURE.md` §10.4): diff-based tailoring with review/confirm, tracker, refinement loops, queue, MCP.
