import { NextRequest, NextResponse } from "next/server";
import { deleteJob, getJob } from "@/lib/db";

type Params = { params: Promise<{ id: string }> };

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const job = getJob(id);
  if (!job) {
    return NextResponse.json({ error: "Job not found" }, { status: 404 });
  }
  return NextResponse.json({ data: job });
}

export async function DELETE(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  if (!deleteJob(id)) {
    return NextResponse.json({ error: "Job not found" }, { status: 404 });
  }
  return NextResponse.json({ data: { deleted: true } });
}
