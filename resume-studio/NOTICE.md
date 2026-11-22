# Notice

Resume Studio is an independent reimplementation, in TypeScript and Next.js, of the core loop of
**Resume Matcher** — https://github.com/srbhr/Resume-Matcher — by Saurabh Rai and contributors,
licensed under the Apache License, Version 2.0 (full text in `LICENSE-Resume-Matcher`).

Adapted from Resume Matcher (see `ARCHITECTURE.md` for the source map):

- the `ResumeData` schema and the parse-and-repair flow for uploaded resumes;
- the job-description keyword extraction prompt and its content-hash cache;
- the deterministic ATS score: its components, weights and title/date rules;
- the idea of printing PDFs by opening the app's own print page in headless Chromium.

Changes: everything is rewritten from scratch as one Next.js app (no Python backend), with SQLite
storage, multi-provider AI through the AI SDK, encrypted key storage and a local-only request
guard. Ported logic was translated from Python; prompt texts may follow the original wording.
