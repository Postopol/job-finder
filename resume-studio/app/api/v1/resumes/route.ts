import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { listResumes } from "@/lib/db";
import { createBlankResume, createResumeFromText } from "@/lib/process";

export async function GET() {
  return NextResponse.json({ data: listResumes() });
}

const postSchema = z.union([
  z.object({ text: z.string().trim().min(30, "Resume text is too short.") }),
  z.object({ blank: z.literal(true) }),
]);

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
  const resume =
    "text" in parsed.data
      ? await createResumeFromText(parsed.data.text, "pasted-resume.txt")
      : createBlankResume();
  return NextResponse.json({ data: resume }, { status: 201 });
}
