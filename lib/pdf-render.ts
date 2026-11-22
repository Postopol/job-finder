import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { chromium, type Browser } from "playwright-core";
import type { TemplateSettings } from "./schema";
import { issuePrintToken } from "./print-token";

/**
 * PDF export — the original's trick, kept intact: a pooled headless
 * Chromium prints the frontend's own /print route, so preview and PDF are
 * pixel-identical and there is exactly one template codebase.
 *
 * Browsers are looked up in this order:
 *   1. PLAYWRIGHT_CHROMIUM_PATH env
 *   2. playwright's own registry for this version
 *   3. any ~/.cache/ms-playwright/chromium* build found on the machine
 */

const PAGE_TIMEOUT_MS = 30_000;
const MAX_CONCURRENT_RENDERS = 2;

let browserPromise: Promise<Browser> | null = null;

function findExecutable(): string | undefined {
  if (process.env.PLAYWRIGHT_CHROMIUM_PATH) {
    return process.env.PLAYWRIGHT_CHROMIUM_PATH;
  }
  const cacheDir = path.join(os.homedir(), ".cache", "ms-playwright");
  if (!fs.existsSync(cacheDir)) return undefined;
  const candidates = fs
    .readdirSync(cacheDir)
    .filter((d) => /^chromium(_headless_shell)?-\d+$/.test(d))
    .sort((a, b) => Number(b.split("-").pop()) - Number(a.split("-").pop()))
    .flatMap((d) => {
      const headlessShell = path.join(
        cacheDir,
        d,
        "chrome-headless-shell-linux64",
        "chrome-headless-shell",
      );
      const chromeLinux64 = path.join(cacheDir, d, "chrome-linux64", "chrome");
      const chromeLinux = path.join(cacheDir, d, "chrome-linux", "chrome");
      return [headlessShell, chromeLinux64, chromeLinux];
    })
    .filter((p) => fs.existsSync(p));
  return candidates[0];
}

async function getBrowser(): Promise<Browser> {
  if (!browserPromise) {
    browserPromise = (async () => {
      const executablePath = findExecutable();
      return chromium.launch({
        ...(executablePath ? { executablePath } : {}),
        headless: true,
        args: ["--no-sandbox", "--disable-dev-shm-usage"],
      });
    })().catch((error) => {
      browserPromise = null;
      throw error;
    });
  }
  return browserPromise;
}

export async function closeBrowser(): Promise<void> {
  if (browserPromise) {
    const promise = browserPromise;
    browserPromise = null;
    await promise.then((b) => b.close()).catch(() => undefined);
  }
}

// ---------------------------------------------------------------------------
// Rendering, with a small concurrency gate

let activeRenders = 0;
const waitQueue: (() => void)[] = [];

async function acquireSlot(): Promise<void> {
  if (activeRenders < MAX_CONCURRENT_RENDERS) {
    activeRenders++;
    return;
  }
  await new Promise<void>((resolve) => waitQueue.push(resolve));
  activeRenders++;
}

function releaseSlot(): void {
  activeRenders--;
  const next = waitQueue.shift();
  if (next) next();
}

export class PDFRenderError extends Error {}

export async function renderResumePdf(options: {
  origin: string;
  resumeId: string;
  settings: TemplateSettings;
}): Promise<Buffer> {
  const { origin, resumeId, settings } = options;
  const token = issuePrintToken(resumeId);
  const url = `${origin}/print/resumes/${resumeId}?token=${token}`;

  await acquireSlot();
  try {
    const browser = await getBrowser();
    const context = await browser.newContext();
    try {
      const page = await context.newPage();
      page.setDefaultTimeout(PAGE_TIMEOUT_MS);
      const response = await page.goto(url, { waitUntil: "networkidle" });
      if (!response || !response.ok()) {
        throw new PDFRenderError(
          `Print page failed to load (HTTP ${response?.status() ?? "?"}).`,
        );
      }
      const printError = await page.$("[data-print-error]");
      if (printError) {
        const message =
          (await printError.getAttribute("data-print-error")) ?? "unknown";
        throw new PDFRenderError(`Print page reported: ${message}`);
      }
      // Margins are owned by the template itself (same padding renders in
      // the live preview), so the PDF prints edge-to-edge with one source
      // of truth for geometry.
      return Buffer.from(
        await page.pdf({
          format: settings.paper === "letter" ? "Letter" : "A4",
          printBackground: true,
          margin: { top: "0in", bottom: "0in", left: "0in", right: "0in" },
        }),
      );
    } finally {
      await context.close().catch(() => undefined);
    }
  } finally {
    releaseSlot();
  }
}
