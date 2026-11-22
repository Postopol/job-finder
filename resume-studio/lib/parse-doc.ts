import mammoth from "mammoth";
import { extractText, getDocumentProxy } from "unpdf";

/**
 * Document → text extraction with the original's hard limits:
 * bounded size, page cap, and a clear refusal for scanned PDFs.
 */

export class DocumentValidationError extends Error {
  status: number;
  constructor(message: string, status = 422) {
    super(message);
    this.status = status;
  }
}

const MAX_FILE_BYTES = 10 * 1024 * 1024; // 10 MB
const MAX_PDF_PAGES = 30;
const MAX_TEXT_CHARS = 1_000_000;

export function validateUpload(filename: string, size: number): void {
  const ext = filename.toLowerCase().split(".").pop();
  if (ext !== "pdf" && ext !== "docx") {
    throw new DocumentValidationError(
      "Only PDF and DOCX files are supported.",
      400,
    );
  }
  if (size > MAX_FILE_BYTES) {
    throw new DocumentValidationError("File is larger than 10 MB.", 413);
  }
}

export async function extractDocumentText(
  buffer: Buffer,
  filename: string,
): Promise<string> {
  const ext = filename.toLowerCase().split(".").pop();

  let text: string;
  if (ext === "pdf") {
    try {
      const pdf = await getDocumentProxy(new Uint8Array(buffer));
      if (pdf.numPages > MAX_PDF_PAGES) {
        throw new DocumentValidationError(
          `PDF has more than ${MAX_PDF_PAGES} pages.`,
          413,
        );
      }
      const result = await extractText(pdf, { mergePages: true });
      text = result.text;
    } catch (error) {
      if (error instanceof DocumentValidationError) throw error;
      const message = error instanceof Error ? error.message : "";
      if (/password|encrypt/i.test(message)) {
        throw new DocumentValidationError(
          "Password-protected PDFs are not supported.",
        );
      }
      throw new DocumentValidationError(
        "Could not read the PDF. It may be corrupted.",
      );
    }
  } else {
    try {
      const result = await mammoth.extractRawText({ buffer });
      text = result.value;
    } catch {
      throw new DocumentValidationError(
        "Could not read the DOCX. It may be corrupted.",
      );
    }
  }

  // Collapse runaway blank lines, trim each line's trailing spaces.
  text = text
    .split("\n")
    .map((line) => line.replace(/[ \t]+$/g, ""))
    .join("\n")
    .replace(/\n{3,}/g, "\n\n")
    .trim();

  if (!text) {
    throw new DocumentValidationError(
      "Could not extract text. The document may be scanned or image-based. Run OCR first.",
    );
  }
  if (text.length > MAX_TEXT_CHARS) {
    throw new DocumentValidationError("Document text exceeds 1 MB.", 413);
  }
  return text;
}
