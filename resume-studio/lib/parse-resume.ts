import {
  normalizeResumeData,
  resumeLLMOutputSchema,
  type ResumeData,
} from "./schema";
import { generateStructured } from "./llm";

/**
 * Resume text → structured ResumeData.
 * Prompt adapted from the original's PARSE_RESUME_PROMPT; the post-LLM
 * repairs (date months, dropped skills) are simplified ports of the
 * original's restore_dates_from_markdown / restore_skills_from_markdown —
 * the theme is always the same: never trust the model with facts.
 */

const SYSTEM_PROMPT =
  "You are a JSON extraction engine. Output only valid JSON, no explanations.";

const PARSE_RESUME_PROMPT = `Parse this resume into JSON.

Map content to the standard sections when possible. Put non-standard sections (Publications, Volunteer Work, Research, Hobbies, ...) into customSections with an appropriate type.

Rules:
- Use "" for missing text fields, [] for missing arrays, null for optional fields (website, linkedin, github, experience location, education description)
- workExperience and personalProjects entries carry descriptionStyles: one value per description row. "bullet" for normal bullets, "plain" for rows that render without a bullet marker (subheadings, standalone labels)
- Dates: preserve the original precision. Keep months when present ("Jan 2020 - Dec 2023", "May 2021 - Present"). Use "YYYY - YYYY" only when the source has no months. Normalize separators ("2020-2021" -> "2020 - 2021", "Current"/"Ongoing" -> "Present"). Never drop months.
- Copy EVERY skill, tool, framework, programming language and technology the resume lists into skills, one item each, keeping the original wording. Split comma-separated lists into separate items. Never summarize, merge, shorten or drop skills, however long the list is.
- Spoken languages (English, Hindi, ...) go in languages, not skills. Certifications/training go in certifications. Awards/honors go in awards.
- customSections: use a snake_case key, keep the original section title, and pick sectionType "text" (single text block), "itemList" (items with title/subtitle/years/description) or "stringList" (simple string list)
- Copy names, companies, locations and proper nouns exactly as written

Resume to parse:
---
{resume_text}
---`;

export async function parseResumeWithLLM(
  markdownText: string,
): Promise<ResumeData> {
  const raw = await generateStructured({
    system: SYSTEM_PROMPT,
    prompt: PARSE_RESUME_PROMPT.replace("{resume_text}", markdownText),
    schema: resumeLLMOutputSchema,
    maxOutputTokens: 16_000,
  });
  const repaired = restoreMissingFacts(raw as ResumeData, markdownText);
  return normalizeResumeData(repaired);
}

// ---------------------------------------------------------------------------
// Post-LLM repairs

const MONTHS =
  "Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?";
const YEAR_ONLY_RE = /^\s*(?:19|20)\d{2}\s*[-–—to]+\s*((?:19|20)\d{2}|Present|Current|Now)\s*$/i;
const ANY_DATE_RE = new RegExp(
  `((?:${MONTHS})\\.?,?\\s*(?:19|20)\\d{2}\\s*[-–—to]+\\s*(?:(?:${MONTHS})\\.?,?\\s*(?:19|20)\\d{2}|Present|Current|Now))`,
  "i",
);

function looksYearOnly(years: string): boolean {
  return YEAR_ONLY_RE.test(years);
}

/**
 * If the LLM collapsed a date to years only, find a line in the original
 * markdown that mentions the entry (company/institution/title) and carries a
 * month-precise range — then restore the months.
 */
function restoreDates<T extends { years: string }>(
  entries: T[],
  matchKeys: (entry: T) => string[],
  markdown: string,
): T[] {
  const lines = markdown.split("\n");
  return entries.map((entry) => {
    if (!looksYearOnly(entry.years)) return entry;
    const keys = matchKeys(entry)
      .map((k) => k.trim().toLowerCase())
      .filter((k) => k.length > 2);
    if (!keys.length) return entry;
    for (const windowStart of [0, -1]) {
      for (let i = 0; i < lines.length; i++) {
        const line = lines[i].toLowerCase();
        if (!keys.some((k) => line.includes(k))) continue;
        for (const j of [i + windowStart, i, i + 1]) {
          const candidate = lines[j];
          if (!candidate) continue;
          const found = candidate.match(ANY_DATE_RE);
          if (found) return { ...entry, years: found[1].replace(/\s+/g, " ") };
        }
      }
    }
    return entry;
  });
}

/**
 * Re-add skills the LLM summarized away: collect items from markdown lines
 * that look like skill lists, then union them with the parsed skills.
 */
const SKILL_SEPARATOR_RE = /[,;|•·]| \/ /;
const SKILL_HEADING_RE =
  /^(technical\s+)?(skills?|technologies|tech stack|competencies|tools)\b/i;

function restoreSkills(resume: ResumeData, markdown: string): ResumeData {
  const lines = markdown.split("\n");
  const markdownSkills: string[] = [];
  let inSkillsSection = false;
  let blankSeen = 0;
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) {
      blankSeen++;
      if (inSkillsSection && blankSeen >= 2) inSkillsSection = false;
      continue;
    }
    blankSeen = 0;
    const headingMatch = trimmed.replace(/[:*#]+$/g, "").match(SKILL_HEADING_RE);
    if (headingMatch) {
      inSkillsSection = true;
      const rest = trimmed.replace(/^[^:]*:/, "");
      if (rest.trim()) {
        markdownSkills.push(...rest.split(SKILL_SEPARATOR_RE));
      }
      continue;
    }
    if (inSkillsSection) {
      const isProse = trimmed.split(/\s+/).length > 9;
      if (isProse) {
        inSkillsSection = false;
        continue;
      }
      markdownSkills.push(...trimmed.split(SKILL_SEPARATOR_RE));
    }
  }

  const existing = new Set(resume.skills.map((s) => s.trim().toLowerCase()));
  const missing = markdownSkills
    .map((s) => s.replace(/^[-•*]\s*/, "").trim())
    .filter((s) => s.length > 1 && s.length < 40)
    .filter((s) => !existing.has(s.toLowerCase()));
  if (!missing.length) return resume;
  return { ...resume, skills: [...resume.skills, ...missing] };
}

export function restoreMissingFacts(
  resume: ResumeData,
  markdown: string,
): ResumeData {
  let out: ResumeData = {
    ...resume,
    workExperience: restoreDates(
      resume.workExperience,
      (e) => [e.company, e.title],
      markdown,
    ),
    education: restoreDates(
      resume.education,
      (e) => [e.institution, e.degree],
      markdown,
    ),
    personalProjects: restoreDates(
      resume.personalProjects,
      (e) => [e.name, e.role],
      markdown,
    ),
  };
  out = restoreSkills(out, markdown);
  return out;
}
