import Database from "better-sqlite3";
import fs from "node:fs";
import path from "node:path";
import { newId, nowIso } from "./utils";
import type { ResumeData, TemplateSettings } from "./schema";

/**
 * SQLite persistence layer — a dict facade over raw SQL, mirroring the
 * original's design (database.py returns plain rows, never ORM objects).
 */

const DATA_DIR = process.env.DATA_DIR || path.join(process.cwd(), "data");

export interface ResumeRow {
  resume_id: string;
  content: string;
  content_type: string;
  filename: string | null;
  is_master: number;
  is_default_master: number;
  parent_id: string | null;
  processed_data: ResumeData | null;
  processing_status: string;
  processing_error: string | null;
  original_markdown: string | null;
  title: string | null;
  template_settings: TemplateSettings | null;
  created_at: string;
  updated_at: string;
}

export interface ResumeListItem {
  resume_id: string;
  title: string | null;
  filename: string | null;
  is_master: boolean;
  is_default_master: boolean;
  parent_id: string | null;
  processing_status: string;
  updated_at: string;
}

function createDatabase(): Database.Database {
  fs.mkdirSync(DATA_DIR, { recursive: true });
  const db = new Database(path.join(DATA_DIR, "resumes.sqlite"));
  db.pragma("journal_mode = WAL");
  db.pragma("busy_timeout = 5000");
  db.exec(`
    CREATE TABLE IF NOT EXISTS resumes (
      resume_id TEXT PRIMARY KEY,
      content TEXT NOT NULL,
      content_type TEXT NOT NULL DEFAULT 'md',
      filename TEXT,
      is_master INTEGER NOT NULL DEFAULT 0,
      is_default_master INTEGER NOT NULL DEFAULT 0,
      parent_id TEXT,
      processed_data TEXT,
      processing_status TEXT NOT NULL DEFAULT 'pending',
      processing_error TEXT,
      original_markdown TEXT,
      title TEXT,
      template_settings TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE UNIQUE INDEX IF NOT EXISTS ux_resumes_single_default_master
      ON resumes(is_default_master) WHERE is_default_master = 1;
    CREATE TABLE IF NOT EXISTS jobs (
      job_id TEXT PRIMARY KEY,
      content TEXT NOT NULL,
      company TEXT,
      role TEXT,
      metadata TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
  `);
  return db;
}

const g = globalThis as unknown as { __resumeStudioDb?: Database.Database };
export const db = g.__resumeStudioDb ?? createDatabase();
if (!g.__resumeStudioDb) g.__resumeStudioDb = db;

function rowToResume(row: Record<string, unknown> | undefined): ResumeRow | null {
  if (!row) return null;
  return {
    ...(row as unknown as ResumeRow),
    is_master: Number(row.is_master),
    is_default_master: Number(row.is_default_master),
    processed_data: row.processed_data
      ? (JSON.parse(row.processed_data as string) as ResumeData)
      : null,
    template_settings: row.template_settings
      ? (JSON.parse(row.template_settings as string) as TemplateSettings)
      : null,
  };
}

// ---------------------------------------------------------------------------
// Resumes

export interface CreateResumeInput {
  content: string;
  content_type?: string;
  filename?: string | null;
  is_master?: boolean;
  processed_data?: ResumeData | null;
  processing_status?: string;
  processing_error?: string | null;
  original_markdown?: string | null;
  title?: string | null;
}

export function createResume(input: CreateResumeInput): ResumeRow {
  const id = newId();
  const now = nowIso();
  const isMaster = input.is_master ?? true;
  const makeDefault =
    isMaster && !db.prepare(`SELECT 1 FROM resumes WHERE is_default_master = 1`).get();
  db.prepare(
    `INSERT INTO resumes
       (resume_id, content, content_type, filename, is_master, is_default_master,
        parent_id, processed_data, processing_status, processing_error,
        original_markdown, title, template_settings, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, ?, ?)`,
  ).run(
    id,
    input.content,
    input.content_type ?? "md",
    input.filename ?? null,
    isMaster ? 1 : 0,
    makeDefault ? 1 : 0,
    input.processed_data ? JSON.stringify(input.processed_data) : null,
    input.processing_status ?? "pending",
    input.processing_error ?? null,
    input.original_markdown ?? null,
    input.title ?? input.filename ?? null,
    now,
    now,
  );
  return getResume(id)!;
}

export function getResume(id: string): ResumeRow | null {
  const row = db.prepare(`SELECT * FROM resumes WHERE resume_id = ?`).get(id) as
    | Record<string, unknown>
    | undefined;
  return rowToResume(row);
}

export function listResumes(includeMaster = true): ResumeListItem[] {
  const rows = includeMaster
    ? db.prepare(`SELECT * FROM resumes ORDER BY updated_at DESC`).all()
    : db
        .prepare(`SELECT * FROM resumes WHERE is_master = 0 ORDER BY updated_at DESC`)
        .all();
  return (rows as Record<string, unknown>[]).map((row) => ({
    resume_id: row.resume_id as string,
    title: (row.title as string) ?? (row.filename as string) ?? null,
    filename: row.filename as string | null,
    is_master: Number(row.is_master) === 1,
    is_default_master: Number(row.is_default_master) === 1,
    parent_id: row.parent_id as string | null,
    processing_status: row.processing_status as string,
    updated_at: row.updated_at as string,
  }));
}

export interface UpdateResumeFields {
  content?: string;
  content_type?: string;
  processed_data?: ResumeData;
  processing_status?: string;
  processing_error?: string | null;
  title?: string | null;
  template_settings?: TemplateSettings;
}

export function updateResume(
  id: string,
  fields: UpdateResumeFields,
): ResumeRow | null {
  const sets: string[] = [];
  const values: unknown[] = [];
  if (fields.content !== undefined) {
    sets.push("content = ?");
    values.push(fields.content);
  }
  if (fields.content_type !== undefined) {
    sets.push("content_type = ?");
    values.push(fields.content_type);
  }
  if (fields.processed_data !== undefined) {
    sets.push("processed_data = ?");
    values.push(JSON.stringify(fields.processed_data));
  }
  if (fields.processing_status !== undefined) {
    sets.push("processing_status = ?");
    values.push(fields.processing_status);
  }
  if (fields.processing_error !== undefined) {
    sets.push("processing_error = ?");
    values.push(fields.processing_error);
  }
  if (fields.title !== undefined) {
    sets.push("title = ?");
    values.push(fields.title);
  }
  if (fields.template_settings !== undefined) {
    sets.push("template_settings = ?");
    values.push(JSON.stringify(fields.template_settings));
  }
  if (!sets.length) return getResume(id);
  sets.push("updated_at = ?");
  values.push(nowIso());
  values.push(id);
  db.prepare(`UPDATE resumes SET ${sets.join(", ")} WHERE resume_id = ?`).run(
    ...values,
  );
  return getResume(id);
}

export function deleteResume(id: string): boolean {
  const resume = getResume(id);
  if (!resume) return false;
  const tx = db.transaction(() => {
    db.prepare(`DELETE FROM resumes WHERE resume_id = ?`).run(id);
    if (resume.is_default_master) {
      const next = db
        .prepare(
          `SELECT resume_id FROM resumes WHERE is_master = 1
           ORDER BY updated_at DESC LIMIT 1`,
        )
        .get() as { resume_id: string } | undefined;
      if (next) {
        db.prepare(`UPDATE resumes SET is_default_master = 1 WHERE resume_id = ?`).run(
          next.resume_id,
        );
      }
    }
  });
  tx();
  return true;
}

export function setDefaultMaster(id: string): ResumeRow | null {
  const resume = getResume(id);
  if (!resume || !resume.is_master) return null;
  const tx = db.transaction(() => {
    db.prepare(`UPDATE resumes SET is_default_master = 0`).run();
    db.prepare(
      `UPDATE resumes SET is_default_master = 1, updated_at = ? WHERE resume_id = ?`,
    ).run(nowIso(), id);
  });
  tx();
  return getResume(id);
}

// ---------------------------------------------------------------------------
// Jobs (pasted job descriptions; keyword cache lives in metadata)

/** Loose shape: the keyword cache is validated by lib/tailor/keywords.ts. */
export interface JobMetadata {
  job_keywords?: unknown;
  job_keywords_hash?: string;
  [key: string]: unknown;
}

export interface JobRow {
  job_id: string;
  content: string;
  company: string | null;
  role: string | null;
  metadata: JobMetadata | null;
  created_at: string;
  updated_at: string;
}

export interface JobListItem {
  job_id: string;
  company: string | null;
  role: string | null;
  snippet: string;
  created_at: string;
}

function rowToJob(row: Record<string, unknown> | undefined): JobRow | null {
  if (!row) return null;
  return {
    ...(row as unknown as JobRow),
    metadata: row.metadata
      ? (JSON.parse(row.metadata as string) as JobMetadata)
      : null,
  };
}

export function createJob(input: {
  content: string;
  company?: string | null;
  role?: string | null;
  metadata?: JobMetadata | null;
}): JobRow {
  const id = newId();
  const now = nowIso();
  db.prepare(
    `INSERT INTO jobs (job_id, content, company, role, metadata, created_at, updated_at)
     VALUES (?, ?, ?, ?, ?, ?, ?)`,
  ).run(
    id,
    input.content,
    input.company ?? null,
    input.role ?? null,
    input.metadata ? JSON.stringify(input.metadata) : null,
    now,
    now,
  );
  return getJob(id)!;
}

export function getJob(id: string): JobRow | null {
  return rowToJob(
    db.prepare(`SELECT * FROM jobs WHERE job_id = ?`).get(id) as
      | Record<string, unknown>
      | undefined,
  );
}

export function listJobs(limit = 50): JobListItem[] {
  const rows = db
    .prepare(`SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?`)
    .all(limit) as Record<string, unknown>[];
  return rows.map((row) => {
    const content = row.content as string;
    return {
      job_id: row.job_id as string,
      company: (row.company as string) ?? null,
      role: (row.role as string) ?? null,
      snippet: content.length > 140 ? `${content.slice(0, 140)}…` : content,
      created_at: row.created_at as string,
    };
  });
}

export interface UpdateJobFields {
  content?: string;
  company?: string | null;
  role?: string | null;
  metadata?: JobMetadata;
}

export function updateJob(id: string, fields: UpdateJobFields): JobRow | null {
  const sets: string[] = [];
  const values: unknown[] = [];
  if (fields.content !== undefined) {
    sets.push("content = ?");
    values.push(fields.content);
  }
  if (fields.company !== undefined) {
    sets.push("company = ?");
    values.push(fields.company);
  }
  if (fields.role !== undefined) {
    sets.push("role = ?");
    values.push(fields.role);
  }
  if (fields.metadata !== undefined) {
    sets.push("metadata = ?");
    values.push(JSON.stringify(fields.metadata));
  }
  if (!sets.length) return getJob(id);
  sets.push("updated_at = ?");
  values.push(nowIso());
  values.push(id);
  db.prepare(`UPDATE jobs SET ${sets.join(", ")} WHERE job_id = ?`).run(
    ...values,
  );
  return getJob(id);
}

export function deleteJob(id: string): boolean {
  return (
    db.prepare(`DELETE FROM jobs WHERE job_id = ?`).run(id).changes > 0
  );
}

// ---------------------------------------------------------------------------
// Settings (key/value JSON store)

export function getSetting<T>(key: string): T | null {
  const row = db.prepare(`SELECT value FROM settings WHERE key = ?`).get(key) as
    | { value: string }
    | undefined;
  if (!row) return null;
  try {
    return JSON.parse(row.value) as T;
  } catch {
    return null;
  }
}

export function setSetting(key: string, value: unknown): void {
  db.prepare(
    `INSERT INTO settings (key, value) VALUES (?, ?)
     ON CONFLICT(key) DO UPDATE SET value = excluded.value`,
  ).run(key, JSON.stringify(value));
}
