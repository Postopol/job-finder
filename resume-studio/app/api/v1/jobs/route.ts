import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { createJob, listJobs } from "@/lib/db";
import { extractJobDetails, MAX_JOB_CHARACTERS } from "@/lib/tailor/keywords";

export async function GET() {
  return NextResponse.json({ data: listJobs() });
}

const postSchema = z.object({
  job_description: z
    .string()
    .trim()
    .min(50, "Job description is too short.")
    .max(MAX_JOB_CHARACTERS, "Job description is too long."),
});

export async function POST(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const parsed = postSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "Invalid request" },
      { status: 400 },
    );
  }

  // Instant heuristic metadata (0 LLM calls); keywords are extracted and
  // cached lazily on the first match/ATS request.
  const details = extractJobDetails(parsed.data.job_description);
  const job = createJob({
    content: parsed.data.job_description,
    company: details.company || null,
    role: details.role || null,
  });
  return NextResponse.json({ data: job }, { status: 201 });
}
