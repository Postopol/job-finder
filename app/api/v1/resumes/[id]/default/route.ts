import { NextRequest, NextResponse } from "next/server";
import { getResume, setDefaultMaster } from "@/lib/db";

export async function POST(
  _request: NextRequest,
  { params }: { params: Promise<{ id: string }> },
) {
  const { id } = await params;
  const resume = getResume(id);
  if (!resume) {
    return NextResponse.json({ error: "Resume not found" }, { status: 404 });
  }
  if (!resume.is_master) {
    return NextResponse.json(
      { error: "Only master resumes can be the default." },
      { status: 400 },
    );
  }
  const updated = setDefaultMaster(id);
  return NextResponse.json({ data: updated });
}
