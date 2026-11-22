import { createHash } from "node:crypto";
import { z } from "zod";
import { generateStructured } from "../llm";
import { updateJob, type JobRow } from "../db";

/**
 * JD keyword extraction — port of the original's extract_job_keywords +
 * the hash-based cache on the job row (ARCHITECTURE.md §4.1). Keywords are
 * re-extracted only when the JD text hash changes; the cache also lets the
 * match view recompute the ATS score later without another LLM call.
 */

export const MAX_JOB_CHARACTERS = 100_000;

export const jobKeywordsSchema = z.object({
  company: z.string().default(""),
  role: z.string().default(""),
  required_skills: z.array(z.string()).default([]),
  preferred_skills: z.array(z.string()).default([]),
  experience_requirements: z.array(z.string()).default([]),
  education_requirements: z.array(z.string()).default([]),
  key_responsibilities: z.array(z.string()).default([]),
  keywords: z.array(z.string()).default([]),
  experience_years: z.number().nullable().default(null),
  seniority_level: z.string().default(""),
});
export type JobKeywords = z.infer<typeof jobKeywordsSchema>;

const EXTRACT_KEYWORDS_PROMPT = `Extract job requirements as JSON.

Rules:
- Set "company" to the hiring company name and "role" to the job title exactly as written in the posting; use an empty string for either if it is not stated.
- required_skills / preferred_skills: concrete tools, technologies and competencies, one item each, keeping the original wording. Split comma-separated lists into separate items.
- keywords: other important terms worth matching in a resume (domain terms, methodologies, "microservices", "agile", ...).
- Extract numeric years (e.g. "5+ years" → 5) and infer the seniority level (junior / mid / senior / staff / lead).
- Never invent requirements that are not in the posting.

Job description:
---
{job_description}
---`;

export async function extractJobKeywords(
  jobDescription: string,
): Promise<JobKeywords> {
  const keywords = jobKeywordsSchema.parse(
    await generateStructured({
      system: "You are an expert job description analyzer.",
      prompt: EXTRACT_KEYWORDS_PROMPT.replace(
        "{job_description}",
        jobDescription,
      ),
      schema: jobKeywordsSchema,
      maxOutputTokens: 4_000,
    }),
  );
  // Guard: a real JD always yields terms or a role. An empty result means
  // the model returned something off-schema that zod defaults swallowed —
  // fail loudly instead of caching garbage.
  if (
    !keywords.role.trim() &&
    !keywords.required_skills.length &&
    !keywords.preferred_skills.length &&
    !keywords.keywords.length
  ) {
    throw new Error(
      "Keyword extraction returned no usable keywords — the model reply was off-schema.",
    );
  }
  return keywords;
}

export function hashJobContent(content: string): string {
  return createHash("sha256").update(content, "utf-8").digest("hex");
}

/**
 * Return the job's cached keywords, extracting (LLM) and caching them when
 * missing or stale (JD text hash changed). Company/role surface to the job's
 * top level so list views can read them without an extra LLM call.
 */
export async function ensureJobKeywords(job: JobRow): Promise<JobKeywords> {
  const contentHash = hashJobContent(job.content);
  const metadata = job.metadata ?? {};
  if (
    metadata.job_keywords &&
    metadata.job_keywords_hash === contentHash
  ) {
    return jobKeywordsSchema.parse(metadata.job_keywords);
  }
  const jobKeywords = await extractJobKeywords(job.content);
  const company = jobKeywords.company.trim();
  const role = jobKeywords.role.trim();
  updateJob(job.job_id, {
    metadata: {
      ...metadata,
      job_keywords: jobKeywords,
      job_keywords_hash: contentHash,
    },
    ...(company ? { company } : {}),
    ...(role ? { role } : {}),
  });
  return jobKeywords;
}

// ---------------------------------------------------------------------------
// Heuristic metadata (0 LLM calls) — port of extract_job_details

export interface JobDetails {
  role: string;
  company: string;
}

/**
 * Heuristically extract role/company from common job posting formats:
 * explicit "Role: ..." labels, "Senior Engineer at Stripe" first lines,
 * "About <Company>" / "<Company> is looking for".
 */
export function extractJobDetails(text: string): JobDetails {
  const details: JobDetails = { role: "", company: "" };
  if (!text.trim()) return details;

  const lines = text
    .trim()
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  // 1. Explicit key-value labels in the first 25 lines
  for (const line of lines.slice(0, 25)) {
    if (!details.role) {
      const m = line.match(
        /^(?:job\s+title|role|position|title)\s*[:-]\s*(\S.*)$/i,
      );
      if (m) details.role = m[1].trim();
    }
    if (!details.company) {
      const m = line.match(
        /^(?:company|organization|employer|client)\s*[:-]\s*(\S.*)$/i,
      );
      if (m) details.company = m[1].trim();
    }
  }

  // 2. Role still empty → look at first 3 non-empty lines
  if (!details.role) {
    for (const line of lines.slice(0, 3)) {
      const atSplit = line.match(/^(.{3,60}?)\s+(?:at|@|–|-)\s+([A-Z][\w&.\s]{1,35})$/);
      if (atSplit) {
        details.role = atSplit[1].trim();
        if (!details.company) details.company = atSplit[2].trim();
        break;
      }
      if (
        line.length < 70 &&
        !["about us", "overview", "description", "welcome"].some((w) =>
          line.toLowerCase().includes(w),
        ) &&
        line.toLowerCase() !== details.company.toLowerCase()
      ) {
        details.role = line;
        break;
      }
    }
  }

  // 3. Company still empty → "About <Company>" / "<Company> is looking for"
  if (!details.company) {
    for (const line of lines.slice(0, 20)) {
      const about = line.match(/^about\s+([A-Z][A-Za-z0-9&.\s]{2,35})\b/i);
      if (about) {
        details.company = about[1].trim();
        break;
      }
      const hiring = line.match(
        /^([A-Z][A-Za-z0-9&.\s]{2,35})\s+is\s+(?:looking|hiring|seeking)/,
      );
      if (hiring) {
        details.company = hiring[1].trim();
        break;
      }
    }
  }

  return { role: details.role.slice(0, 70).trim(), company: details.company.slice(0, 60).trim() };
}
