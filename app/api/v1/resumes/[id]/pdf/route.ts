import { NextRequest, NextResponse } from "next/server";
import { getResume } from "@/lib/db";
import { DEFAULT_TEMPLATE_SETTINGS } from "@/lib/schema";
import { PDFRenderError, renderResumePdf } from "@/lib/pdf-render";

export async function GET(request: NextRequest, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const resume = getResume(id);
  if (!resume) {
    return NextResponse.json({ error: "Resume not found" }, { status: 404 });
  }
  if (!resume.processed_data) {
    return NextResponse.json(
      { error: "This resume has no structured data to render yet." },
      { status: 409 },
    );
  }

  const settings = resume.template_settings ?? DEFAULT_TEMPLATE_SETTINGS;
  try {
    const pdf = await renderResumePdf({
      origin: request.nextUrl.origin,
      resumeId: id,
      settings,
    });
    const filename = `${(resume.title ?? resume.filename ?? "resume")
      .replace(/[^\w\s-]/g, "")
      .trim()
      .replace(/\s+/g, "-")
      .toLowerCase() || "resume"}.pdf`;
    return new NextResponse(new Uint8Array(pdf), {
      headers: {
        "Content-Type": "application/pdf",
        "Content-Disposition": `attachment; filename="${filename}"`,
        "Cache-Control": "no-store",
      },
    });
  } catch (error) {
    const message =
      error instanceof PDFRenderError
        ? error.message
        : "PDF rendering failed. Is Chromium installed? Run: npx playwright install chromium";
    console.error("PDF render failed:", error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
