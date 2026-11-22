import { createResume, getResume, updateResume, type ResumeRow } from "./db";
import { isLLMConfigured } from "./settings";
import { parseResumeWithLLM } from "./parse-resume";
import { emptyResumeData } from "./schema";

/**
 * Shared ingestion pipeline: create (or re-run) a resume row and drive it to
 * a terminal status: ready | needs_llm | error.
 */

function deriveTitle(resume: ResumeRow, data: { personalInfo: { name: string; title: string } }): string | null {
  const { name, title } = data.personalInfo;
  if (name && title) return `${name} — ${title}`;
  if (name) return name;
  return resume.filename ?? resume.title ?? null;
}

export async function createResumeFromText(
  text: string,
  filename?: string | null,
): Promise<ResumeRow> {
  const resume = createResume({
    content: text,
    content_type: "md",
    filename: filename ?? null,
    original_markdown: text,
    processing_status: "processing",
  });
  return runProcessing(resume.resume_id);
}

export function createBlankResume(): ResumeRow {
  const data = emptyResumeData();
  return createResume({
    content: JSON.stringify(data),
    content_type: "json",
    filename: null,
    original_markdown: null,
    processed_data: data,
    processing_status: "ready",
    title: "Blank resume",
  });
}

export async function runProcessing(resumeId: string): Promise<ResumeRow> {
  const resume = getResume(resumeId);
  if (!resume) throw new Error("Resume not found");
  const markdown = resume.original_markdown ?? resume.content;

  if (!isLLMConfigured()) {
    return (
      updateResume(resumeId, { processing_status: "needs_llm" }) ?? resume
    );
  }
  try {
    const data = await parseResumeWithLLM(markdown);
    return (
      updateResume(resumeId, {
        processed_data: data,
        processing_status: "ready",
        processing_error: null,
        title: deriveTitle(resume, data),
      }) ?? resume
    );
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Unknown processing error";
    return (
      updateResume(resumeId, {
        processing_status: "error",
        processing_error: message,
      }) ?? resume
    );
  }
}
