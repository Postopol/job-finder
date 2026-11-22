import { z } from "zod";

/**
 * The canonical ResumeData interchange schema.
 * Mirrors the original Resume-Matcher contract (see ARCHITECTURE.md §2):
 * every field has a default so partially-shaped LLM output and old rows
 * still validate. `descriptionStyles` must stay index-aligned with
 * `description` — enforced by normalizeResumeData().
 */

export const bulletStyleSchema = z.enum(["bullet", "plain"]);
export type BulletStyle = z.infer<typeof bulletStyleSchema>;

export const personalInfoSchema = z.object({
  name: z.string().default(""),
  title: z.string().default(""),
  email: z.string().default(""),
  phone: z.string().default(""),
  location: z.string().default(""),
  website: z.string().nullable().default(null),
  linkedin: z.string().nullable().default(null),
  github: z.string().nullable().default(null),
});
export type PersonalInfo = z.infer<typeof personalInfoSchema>;

export const experienceSchema = z.object({
  title: z.string().default(""),
  company: z.string().default(""),
  location: z.string().nullable().default(null),
  years: z.string().default(""),
  description: z.array(z.string()).default([]),
  descriptionStyles: z.array(bulletStyleSchema).default([]),
});
export type Experience = z.infer<typeof experienceSchema>;

export const educationSchema = z.object({
  institution: z.string().default(""),
  degree: z.string().default(""),
  years: z.string().default(""),
  description: z.string().nullable().default(null),
});
export type Education = z.infer<typeof educationSchema>;

export const projectSchema = z.object({
  name: z.string().default(""),
  role: z.string().default(""),
  years: z.string().default(""),
  description: z.array(z.string()).default([]),
  descriptionStyles: z.array(bulletStyleSchema).default([]),
});
export type Project = z.infer<typeof projectSchema>;

export const customItemSchema = z.object({
  title: z.string().default(""),
  subtitle: z.string().default(""),
  years: z.string().default(""),
  description: z.array(z.string()).default([]),
  descriptionStyles: z.array(bulletStyleSchema).default([]),
});
export type CustomItem = z.infer<typeof customItemSchema>;

export const customSectionTypeSchema = z.enum(["text", "itemList", "stringList"]);

export const customSectionSchema = z.object({
  key: z.string().default(""),
  title: z.string().default(""),
  sectionType: customSectionTypeSchema.default("itemList"),
  text: z.string().default(""),
  items: z.array(customItemSchema).default([]),
  strings: z.array(z.string()).default([]),
});
export type CustomSection = z.infer<typeof customSectionSchema>;

export const sectionMetaSchema = z.object({
  key: z.string(),
  isVisible: z.boolean().default(true),
});

export const resumeDataSchema = z.object({
  personalInfo: personalInfoSchema.prefault({}),
  summary: z.string().default(""),
  workExperience: z.array(experienceSchema).default([]),
  education: z.array(educationSchema).default([]),
  personalProjects: z.array(projectSchema).default([]),
  skills: z.array(z.string()).default([]),
  certifications: z.array(z.string()).default([]),
  languages: z.array(z.string()).default([]),
  awards: z.array(z.string()).default([]),
  customSections: z.array(customSectionSchema).default([]),
  sectionMeta: z.array(sectionMetaSchema).default([]),
});
export type ResumeData = z.infer<typeof resumeDataSchema>;

// The schema the LLM is asked to produce (sectionMeta is harness-owned).
export const resumeLLMOutputSchema = resumeDataSchema.omit({ sectionMeta: true });

// ---------------------------------------------------------------------------
// Template settings

export const templateSettingsSchema = z.object({
  template: z.enum(["classic", "modern"]).default("classic"),
  paper: z.enum(["a4", "letter"]).default("a4"),
  margins: z.enum(["narrow", "normal", "wide"]).default("normal"),
  fontScale: z.number().min(0.8).max(1.2).default(1),
  accent: z
    .string()
    .regex(/^#[0-9a-fA-F]{6}$/)
    .default("#1d4ed8"),
});
export type TemplateSettings = z.infer<typeof templateSettingsSchema>;

export const DEFAULT_TEMPLATE_SETTINGS: TemplateSettings =
  templateSettingsSchema.parse({});

// ---------------------------------------------------------------------------
// Normalization / helpers

/** Pad or truncate `styles` so it is index-aligned with `description`. */
function alignStyles(
  description: string[],
  styles: BulletStyle[],
): BulletStyle[] {
  const out = description.map((_, i) => styles[i] ?? "bullet");
  return out;
}

/** Enforce every structural invariant the rendering and tailoring code relies on. */
export function normalizeResumeData(raw: unknown): ResumeData {
  const data = resumeDataSchema.parse(raw ?? {});
  data.workExperience = data.workExperience.map((e) => ({
    ...e,
    description: e.description.filter((d) => d !== null && d !== undefined),
    descriptionStyles: alignStyles(e.description, e.descriptionStyles),
  }));
  data.personalProjects = data.personalProjects.map((p) => ({
    ...p,
    description: p.description.filter((d) => d !== null && d !== undefined),
    descriptionStyles: alignStyles(p.description, p.descriptionStyles),
  }));
  data.customSections = data.customSections.map((s) => {
    if (s.sectionType !== "itemList") return s;
    return {
      ...s,
      items: s.items.map((item) => ({
        ...item,
        description: item.description.filter(
          (d) => d !== null && d !== undefined,
        ),
        descriptionStyles: alignStyles(item.description, item.descriptionStyles),
      })),
    };
  });
  data.skills = [...new Set(data.skills.map((s) => s.trim()).filter(Boolean))];
  return data;
}

export function emptyResumeData(): ResumeData {
  return resumeDataSchema.parse({});
}

/** Section keys in canonical order, used for rendering and visibility. */
export const SECTION_ORDER = [
  "summary",
  "workExperience",
  "personalProjects",
  "education",
  "skills",
  "certifications",
  "languages",
  "awards",
  ...([] as string[]), // custom section keys appended dynamically
] as const;

export function sectionVisible(
  data: ResumeData,
  key: string,
): boolean {
  const meta = data.sectionMeta.find((m) => m.key === key);
  return meta ? meta.isVisible : true;
}

export function paperSizePx(paper: "a4" | "letter"): { width: number } {
  // CSS pixels at 96dpi
  return paper === "letter" ? { width: 816 } : { width: 794 };
}

export function marginPx(margins: TemplateSettings["margins"]): number {
  switch (margins) {
    case "narrow":
      return 36;
    case "wide":
      return 68;
    default:
      return 50;
  }
}
