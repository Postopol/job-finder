import type { ResumeData } from "./schema";
import { sectionVisible } from "./schema";
import { keywordInText } from "./text-match";
import type { JobKeywords } from "./tailor/keywords";

/**
 * Deterministic ATS scoring — a port of the original's services/ats.py.
 * No LLM anywhere: scores are plain code so they are cheap to recompute
 * and trustworthy. Only what an ATS would actually parse is scored:
 * hidden sections (sectionMeta.isVisible=false) are excluded.
 */

// Weights must sum to 1.0
export const ATS_WEIGHTS = {
  keyword_match: 0.4,
  skills_coverage: 0.2,
  title_match: 0.15,
  section_completeness: 0.15,
  date_consistency: 0.1,
} as const;

// Title-match scores: exact title in the headline is what recruiters'
// title filters hit; the summary is a weaker placement; word overlap is a
// near miss.
const TITLE_IN_HEADLINE = 100;
const TITLE_IN_SUMMARY = 75;
const TITLE_OVERLAP_MAX = 50;
const TITLE_STOPWORDS = new Set([
  "a",
  "an",
  "and",
  "the",
  "of",
  "for",
  "in",
  "to",
  "at",
  "&",
]);

// Date styles, tried left to right at each position. Only English month
// names and abbreviations count as month dates: parsers don't recognise
// "Ene 2020", so that reads as a bare year.
const YEAR = "(?:19|20)\\d{2}";
const MONTH =
  "(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)";
const DATE_PATTERN = new RegExp(
  `(?<iso>\\b${YEAR}[-/]\\d{1,2}\\b)` +
    `|(?<numeric>\\b\\d{1,2}[/.\\-]${YEAR}\\b)` +
    `|(?<name_year>\\b${MONTH}\\.?,?\\s+${YEAR}\\b)` +
    `|(?<name_short_year>\\b${MONTH}\\.?\\s+'\\d{2}\\b)` +
    `|(?<year>\\b${YEAR}\\b)`,
  "gi",
);
const MIN_DATES_FOR_CONSISTENCY = 2;

export interface AtsScore {
  overall_score: number;
  sub_scores: {
    keyword_match: number;
    skills_coverage: number;
    title_match: number | null;
    section_completeness: number;
    date_consistency: number | null;
  };
  matched_keywords: string[];
  missing_keywords: string[];
  injectable_keywords: string[];
  recommendations: string[];
}

// ---------------------------------------------------------------------------
// Rendered content — the resume minus what never reaches the page

function extractAllText(data: unknown): string {
  const parts: string[] = [];
  const walk = (obj: unknown) => {
    if (typeof obj === "string") {
      parts.push(obj);
    } else if (Array.isArray(obj)) {
      obj.forEach(walk);
    } else if (obj && typeof obj === "object") {
      Object.values(obj as Record<string, unknown>).forEach(walk);
    }
  };
  walk(data);
  return parts.join(" ");
}

/**
 * The resume minus what never reaches the page, so an ATS cannot read it.
 * Section labels in sectionMeta are configuration, not content, and hidden
 * sections are not rendered.
 */
function renderedContent(resume: ResumeData): Omit<ResumeData, "sectionMeta"> {
  const content: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(resume)) {
    if (key === "sectionMeta") continue;
    if (!sectionVisible(resume, key)) continue;
    content[key] = value;
  }
  content.customSections = resume.customSections.filter((s) =>
    sectionVisible(resume, s.key),
  );
  return content as Omit<ResumeData, "sectionMeta">;
}

// ---------------------------------------------------------------------------
// Keyword terms

/** Distinct JD terms that keyword match is scored on, in posting order. */
export function jobKeywordTerms(jobKeywords: JobKeywords): string[] {
  const terms = new Map<string, string>();
  for (const field of [
    "required_skills",
    "preferred_skills",
    "keywords",
  ] as const) {
    for (const term of jobKeywords[field] ?? []) {
      if (typeof term === "string" && term.trim()) {
        const key = term.trim().toLowerCase();
        if (!terms.has(key)) terms.set(key, term.trim());
      }
    }
  }
  return [...terms.values()];
}

/** Keyword match percentage: how many JD terms appear in the rendered resume. */
export function calculateKeywordMatch(
  resume: ResumeData,
  jobKeywords: JobKeywords,
): number {
  const resumeText = extractAllText(renderedContent(resume)).toLowerCase();
  const allKeywords = jobKeywordTerms(jobKeywords);
  if (!allKeywords.length) return 0;
  const matched = allKeywords.filter((kw) => keywordInText(kw, resumeText));
  return (matched.length / allKeywords.length) * 100;
}

// ---------------------------------------------------------------------------
// Sub-scores

function computeSkillsCoverage(
  resume: ResumeData,
  jobKeywords: JobKeywords,
): number {
  const jdSkills = [
    ...(jobKeywords.required_skills ?? []),
    ...(jobKeywords.preferred_skills ?? []),
  ].filter((s): s is string => typeof s === "string" && s.trim().length > 0);
  if (!jdSkills.length) return 0;

  const content = renderedContent(resume);
  const resumeSkills = new Set(
    content.skills.map((s) => s.trim().toLowerCase()).filter(Boolean),
  );
  const resumeText = extractAllText(content).toLowerCase();

  let matched = 0;
  for (const skill of jdSkills) {
    if (resumeSkills.has(skill.toLowerCase()) || keywordInText(skill, resumeText)) {
      matched++;
    }
  }
  return Math.min(100, (matched / jdSkills.length) * 100);
}

function titleTokens(text: string): Set<string> {
  return new Set(
    (text.toLowerCase().match(/[^\W_]+/g) ?? []).filter(
      (token) => !TITLE_STOPWORDS.has(token),
    ),
  );
}

/**
 * How literally the posting's job title appears (0–100), or null when the
 * posting has no title. 100 = exact title in the headline, 75 = only in the
 * summary, up to 50 for partial word overlap (synonyms such as "Product
 * Lead" for "Product Manager" do not match recruiter title searches).
 */
function computeTitleMatch(
  resume: ResumeData,
  jobKeywords: JobKeywords,
): number | null {
  const role = jobKeywords.role?.trim();
  if (!role) return null;

  const headline = resume.personalInfo.title ?? "";
  const summary = sectionVisible(resume, "summary") ? resume.summary : "";

  if (keywordInText(role, headline.toLowerCase())) return TITLE_IN_HEADLINE;
  if (keywordInText(role, summary.toLowerCase())) return TITLE_IN_SUMMARY;

  const roleTokens = titleTokens(role);
  if (!roleTokens.size) return 0;
  const overlap =
    [...roleTokens].filter((t) => titleTokens(headline).has(t)).length /
    roleTokens.size;
  return Math.round(overlap * TITLE_OVERLAP_MAX * 10) / 10;
}

function collectDateStrings(resume: ResumeData): string[] {
  const entries: { years?: string }[] = [];
  for (const key of [
    "workExperience",
    "education",
    "personalProjects",
  ] as const) {
    if (sectionVisible(resume, key)) entries.push(...resume[key]);
  }
  for (const section of resume.customSections) {
    if (section.sectionType === "itemList" && sectionVisible(resume, section.key)) {
      entries.push(...section.items);
    }
  }
  return entries
    .map((entry) => entry.years)
    .filter((years): years is string => typeof years === "string");
}

/**
 * Share of dates written in the dominant format (0–100), or null when the
 * resume has fewer than two dates, since consistency cannot be judged.
 * "Present"/"Current" markers are ignored.
 */
function computeDateConsistency(resume: ResumeData): number | null {
  const styleCounts = new Map<string, number>();
  for (const value of collectDateStrings(resume)) {
    for (const match of value.matchAll(DATE_PATTERN)) {
      const style = Object.keys(match.groups ?? {}).find(
        (name) => match.groups?.[name] !== undefined,
      );
      if (style) styleCounts.set(style, (styleCounts.get(style) ?? 0) + 1);
    }
  }
  const total = [...styleCounts.values()].reduce((a, b) => a + b, 0);
  if (total < MIN_DATES_FOR_CONSISTENCY) return null;
  const dominant = Math.max(...styleCounts.values());
  return Math.round((dominant / total) * 1000) / 10;
}

/**
 * Contact info (email or phone) plus the summary, experience, education and
 * skills sections — present *and* visible.
 */
function computeSectionCompleteness(resume: ResumeData): number {
  const hasContact = Boolean(
    resume.personalInfo.email || resume.personalInfo.phone,
  );
  const sectionsFound = [
    Boolean(resume.summary) && sectionVisible(resume, "summary"),
    Boolean(resume.workExperience.length) &&
      sectionVisible(resume, "workExperience"),
    Boolean(resume.education.length) && sectionVisible(resume, "education"),
    Boolean(resume.skills.length) && sectionVisible(resume, "skills"),
  ].filter(Boolean).length;
  return ((sectionsFound + (hasContact ? 1 : 0)) / 5) * 100;
}

// ---------------------------------------------------------------------------
// Ordering + recommendations

/** Order keywords as the job posting lists them; unknown ones last, A–Z. */
function inPostingOrder(keywords: string[], jobKeywords: JobKeywords): string[] {
  const rank = new Map<string, number>();
  for (const field of [
    "required_skills",
    "preferred_skills",
    "keywords",
  ] as const) {
    for (const keyword of jobKeywords[field] ?? []) {
      if (typeof keyword === "string" && keyword.trim()) {
        const key = keyword.trim().toLowerCase();
        if (!rank.has(key)) rank.set(key, rank.size);
      }
    }
  }
  return [...keywords].sort((a, b) => {
    const ra = rank.get(a.toLowerCase()) ?? rank.size;
    const rb = rank.get(b.toLowerCase()) ?? rank.size;
    return ra !== rb ? ra - rb : a.toLowerCase().localeCompare(b.toLowerCase());
  });
}

function generateRecommendations(
  subScores: AtsScore["sub_scores"],
  role: string,
  missingKeywords: string[],
  injectableKeywords: string[],
): string[] {
  const tips: string[] = [];
  const keywordScore = subScores.keyword_match;
  const skillsScore = subScores.skills_coverage;
  const sectionScore = subScores.section_completeness;
  const titleScore = subScores.title_match;
  const dateScore = subScores.date_consistency;

  if (titleScore !== null && titleScore < TITLE_IN_HEADLINE) {
    tips.push(
      `Use the exact job title "${role}" in your resume headline. Recruiters filter by title literally, so synonyms are missed. Edit the headline in the Builder.`,
    );
  }

  if (keywordScore < 60 && missingKeywords.length) {
    const top = missingKeywords.slice(0, 5).join(", ");
    tips.push(`Add these high-priority missing keywords: ${top}.`);
  }

  if (injectableKeywords.length) {
    const top = injectableKeywords.slice(0, 5).join(", ");
    tips.push(
      `The following skills are in your master resume but not in this version — consider adding them: ${top}.`,
    );
  }

  if (skillsScore < 60) {
    tips.push(
      "Expand your Skills section to include more of the tools and technologies listed in the job description.",
    );
  }

  if (sectionScore < 100) {
    tips.push(
      "Make sure your resume shows contact details and visible Summary, Work Experience, Education, and Skills sections.",
    );
  }

  if (dateScore !== null && dateScore < 100) {
    tips.push(
      'Write every date range in one format (e.g. "Jan 2020 - Mar 2023"). Mixed formats can make an ATS miscount your years of experience.',
    );
  }

  if (keywordScore >= 80 && skillsScore >= 80) {
    tips.push(
      "Strong keyword and skills alignment. Consider quantifying your achievements with metrics and numbers.",
    );
  }

  if (!tips.length) {
    tips.push(
      "Your resume is well-aligned with the job description. Review for any niche certifications or tools to add.",
    );
  }

  return tips;
}

// ---------------------------------------------------------------------------
// Composite

/**
 * Compute the ATS score breakdown for a resume against a job's keywords.
 * `master` (optional) separates missing keywords into injectable ones —
 * terms the master resume can support but the scored version lacks.
 */
export function computeAtsScore(
  resume: ResumeData,
  jobKeywords: JobKeywords,
  master?: ResumeData,
): AtsScore {
  const resumeText = extractAllText(renderedContent(resume)).toLowerCase();
  const terms = jobKeywordTerms(jobKeywords);
  const matched = terms.filter((kw) => keywordInText(kw, resumeText));
  const missing = terms.filter((kw) => !keywordInText(kw, resumeText));
  const masterText = master
    ? extractAllText(renderedContent(master)).toLowerCase()
    : "";
  const injectable = masterText
    ? missing.filter((kw) => keywordInText(kw, masterText))
    : [];

  const subScores: AtsScore["sub_scores"] = {
    keyword_match: Math.min(100, Math.max(0, (matched.length / Math.max(1, terms.length)) * 100)),
    skills_coverage: computeSkillsCoverage(resume, jobKeywords),
    title_match: computeTitleMatch(resume, jobKeywords),
    section_completeness: computeSectionCompleteness(resume),
    date_consistency: computeDateConsistency(resume),
  };

  const scored = Object.entries(subScores).filter(
    ([, value]) => value !== null,
  ) as [keyof typeof ATS_WEIGHTS, number][];
  const totalWeight = scored.reduce((sum, [key]) => sum + ATS_WEIGHTS[key], 0);
  const overall =
    totalWeight > 0
      ? scored.reduce((sum, [key, value]) => sum + value * ATS_WEIGHTS[key], 0) /
        totalWeight
      : 0;

  return {
    overall_score: Math.round(overall * 10) / 10,
    sub_scores: {
      keyword_match: Math.round(subScores.keyword_match * 10) / 10,
      skills_coverage: Math.round(subScores.skills_coverage * 10) / 10,
      title_match:
        subScores.title_match === null
          ? null
          : Math.round(subScores.title_match * 10) / 10,
      section_completeness:
        Math.round(subScores.section_completeness * 10) / 10,
      date_consistency:
        subScores.date_consistency === null
          ? null
          : Math.round(subScores.date_consistency * 10) / 10,
    },
    matched_keywords: inPostingOrder(matched, jobKeywords),
    missing_keywords: inPostingOrder(missing, jobKeywords).slice(0, 10),
    injectable_keywords: inPostingOrder(injectable, jobKeywords).slice(0, 10),
    recommendations: generateRecommendations(
      subScores,
      jobKeywords.role?.trim() ?? "",
      missing,
      injectable,
    ),
  };
}
