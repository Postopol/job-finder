import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { deleteResume, getResume, updateResume } from "@/lib/db";
import { normalizeResumeData, templateSettingsSchema } from "@/lib/schema";

type Params = { params: Promise<{ id: string }> };

export async function GET(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const resume = getResume(id);
  if (!resume) {
    return NextResponse.json({ error: "Resume not found" }, { status: 404 });
  }
  return NextResponse.json({ data: resume });
}

const patchSchema = z.object({
  title: z.string().trim().min(1).max(200).nullable().optional(),
  processed_data: z.unknown().optional(),
  template_settings: z.unknown().optional(),
});

export async function PATCH(request: NextRequest, { params }: Params) {
  const { id } = await params;
  const existing = getResume(id);
  if (!existing) {
    return NextResponse.json({ error: "Resume not found" }, { status: 404 });
  }

  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const parsed = patchSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "Invalid request" },
      { status: 400 },
    );
  }
  const { title, processed_data, template_settings } = parsed.data;

  let normalizedData: ReturnType<typeof normalizeResumeData> | undefined;
  if (processed_data !== undefined) {
    try {
      normalizedData = normalizeResumeData(processed_data);
    } catch {
      return NextResponse.json(
        { error: "processed_data is not a valid resume" },
        { status: 400 },
      );
    }
  }

  let settings: z.infer<typeof templateSettingsSchema> | undefined;
  if (template_settings !== undefined) {
    const result = templateSettingsSchema.safeParse(template_settings);
    if (!result.success) {
      return NextResponse.json(
        { error: "template_settings is invalid" },
        { status: 400 },
      );
    }
    settings = result.data;
  }

  const resume = updateResume(id, {
    ...(title !== undefined ? { title } : {}),
    ...(normalizedData !== undefined
      ? { processed_data: normalizedData, content: JSON.stringify(normalizedData), content_type: "json" }
      : {}),
    ...(settings !== undefined ? { template_settings: settings } : {}),
    ...(normalizedData !== undefined && existing.processing_status !== "ready"
      ? { processing_status: "ready", processing_error: null }
      : {}),
  });
  return NextResponse.json({ data: resume });
}

export async function DELETE(_request: NextRequest, { params }: Params) {
  const { id } = await params;
  const deleted = deleteResume(id);
  if (!deleted) {
    return NextResponse.json({ error: "Resume not found" }, { status: 404 });
  }
  return NextResponse.json({ data: { deleted: true } });
}
