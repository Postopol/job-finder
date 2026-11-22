import { NextRequest, NextResponse } from "next/server";
import { getJob, getResume } from "@/lib/db";
import { computeAtsScore, type AtsScore } from "@/lib/ats";
import {
  ensureJobKeywords,
  type JobKeywords,
} from "@/lib/tailor/keywords";

/**
 * Deterministic ATS score for a resume against a job's keywords.
 * Keywords are extracted (LLM) and cached on the job row on first use; the
 * score itself is pure code and never touches the LLM.
 */

export async function GET(request: NextRequest) {
  const resumeId = request.nextUrl.searchParams.get("resumeId");
  const jobId = request.nextUrl.searchParams.get("jobId");
  if (!resumeId || !jobId) {
    return NextResponse.json(
      { error: "resumeId and jobId are required" },
      { status: 400 },
    );
  }

  const resume = getResume(resumeId);
  if (!resume) {
    return NextResponse.json({ error: "Resume not found" }, { status: 404 });
  }
  if (!resume.processed_data) {
    return NextResponse.json(
      { error: "Resume is not parsed yet" },
      { status: 409 },
    );
  }

  const job = getJob(jobId);
  if (!job) {
    return NextResponse.json({ error: "Job not found" }, { status: 404 });
  }

  let keywords: JobKeywords;
  try {
    keywords = await ensureJobKeywords(job);
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Keyword extraction failed";
    return NextResponse.json({ error: message }, { status: 502 });
  }

  const ats: AtsScore = computeAtsScore(resume.processed_data, keywords);
  return NextResponse.json({
    data: {
      resume_id: resume.resume_id,
      job_id: job.job_id,
      role: keywords.role || job.role || "",
      company: keywords.company || job.company || "",
      keywords,
      ats,
    },
  });
}
