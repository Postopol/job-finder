import { NextRequest, NextResponse } from "next/server";
import {
  DocumentValidationError,
  extractDocumentText,
  validateUpload,
} from "@/lib/parse-doc";
import { createResumeFromText } from "@/lib/process";

export async function POST(request: NextRequest) {
  let form: FormData;
  try {
    form = await request.formData();
  } catch {
    return NextResponse.json(
      { error: "Expected multipart/form-data with a 'file' field." },
      { status: 400 },
    );
  }
  const file = form.get("file");
  if (!(file instanceof File)) {
    return NextResponse.json({ error: "No file provided." }, { status: 400 });
  }

  try {
    validateUpload(file.name, file.size);
    const buffer = Buffer.from(await file.arrayBuffer());
    const text = await extractDocumentText(buffer, file.name);
    const resume = await createResumeFromText(text, file.name);
    return NextResponse.json({ data: resume }, { status: 201 });
  } catch (error) {
    if (error instanceof DocumentValidationError) {
      return NextResponse.json({ error: error.message }, { status: error.status });
    }
    const message =
      error instanceof Error ? error.message : "Upload failed unexpectedly.";
    console.error("Upload failed:", error);
    return NextResponse.json({ error: message }, { status: 500 });
  }
}
