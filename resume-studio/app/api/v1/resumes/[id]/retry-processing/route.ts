import { NextRequest, NextResponse } from "next/server";
import { getResume } from "@/lib/db";
import { isLLMConfigured } from "@/lib/settings";
import { runProcessing } from "@/lib/process";

export async function POST(_request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const resume = getResume(id);
  if (!resume) {
    return NextResponse.json({ error: "Resume not found" }, { status: 404 });
  }
  if (!resume.original_markdown && !resume.content) {
    return NextResponse.json(
      { error: "This resume has no source text to re-process." },
      { status: 400 },
    );
  }
  if (!isLLMConfigured()) {
    return NextResponse.json(
      { error: "Configure an AI provider in Settings first." },
      { status: 400 },
    );
  }
  const updated = await runProcessing(id);
  return NextResponse.json({ data: updated });
}
