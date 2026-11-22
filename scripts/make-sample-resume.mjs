// Generates data/sample-resume.pdf via headless Chromium so the upload
// pipeline can be tested end-to-end with a realistic text-based PDF.
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { chromium } from "playwright-core";

function findExecutable() {
  const cacheDir = path.join(os.homedir(), ".cache", "ms-playwright");
  if (!fs.existsSync(cacheDir)) return undefined;
  const candidates = fs
    .readdirSync(cacheDir)
    .filter((d) => /^chromium(_headless_shell)?-\d+$/.test(d))
    .sort((a, b) => Number(b.split("-").pop()) - Number(a.split("-").pop()))
    .flatMap((d) => [
      path.join(cacheDir, d, "chrome-headless-shell-linux64", "chrome-headless-shell"),
      path.join(cacheDir, d, "chrome-linux64", "chrome"),
      path.join(cacheDir, d, "chrome-linux", "chrome"),
    ])
    .filter((p) => fs.existsSync(p));
  return candidates[0];
}

const html = `<!doctype html>
<html><head><meta charset="utf-8"><style>
  body { font-family: Georgia, serif; font-size: 11pt; color: #111; margin: 0; padding: 48px; line-height: 1.45; }
  h1 { font-size: 22pt; margin: 0; text-align: center; }
  .title { text-align: center; text-transform: uppercase; letter-spacing: 3px; color: #444; margin-top: 4px; }
  .contact { text-align: center; color: #444; font-size: 9.5pt; margin-top: 6px; }
  h2 { font-size: 11pt; text-transform: uppercase; letter-spacing: 1.5px; border-bottom: 1px solid #333; padding-bottom: 3px; margin: 18pt 0 8pt; }
  .job-title { font-weight: bold; }
  .job-line { display: flex; justify-content: space-between; }
  .muted { color: #555; }
  ul { margin-top: 4px; padding-left: 18px; }
  li { margin-bottom: 2px; }
</style></head><body>
<h1>John Doe</h1>
<div class="title">Senior Backend Engineer</div>
<div class="contact">john.doe@example.com &middot; +1-555-0100 &middot; San Francisco, CA &middot; github.com/johndoe &middot; johndoe.dev</div>

<h2>Summary</h2>
<p>Backend engineer with 8 years of experience building distributed systems in Go and Python. Led migration of 30 services to Kubernetes and cut p99 latency 40% on a high-traffic billing API.</p>

<h2>Experience</h2>
<div class="job-line"><span class="job-title">Senior Backend Engineer, Tech Corp</span><span>Jan 2020 - Present</span></div>
<div class="muted">San Francisco, CA</div>
<ul>
  <li>Moved 30 services from VMs to Kubernetes; on-call lead for the platform</li>
  <li>Rewrote the billing API in Go; p99 latency down 40%</li>
  <li>Set up CI/CD for 12 services with GitHub Actions</li>
</ul>
<div class="job-line" style="margin-top:10px"><span class="job-title">Backend Engineer, Startup LLC</span><span>Jun 2017 - Dec 2019</span></div>
<div class="muted">Remote</div>
<ul>
  <li>Built the event pipeline on Kafka processing 2M events/day</li>
  <li>Introduced Redis caching, cutting DB load by 60%</li>
</ul>

<h2>Education</h2>
<div class="job-line"><span class="job-title">B.S. Computer Science, University of California, Berkeley</span><span>2013 - 2017</span></div>
<div class="muted">Graduated with honors</div>

<h2>Skills</h2>
<p>Go, Python, Kubernetes, Docker, PostgreSQL, Redis, gRPC, Kafka, Terraform, GitHub Actions, AWS, Prometheus</p>

<h2>Certifications</h2>
<p>AWS Solutions Architect</p>

<h2>Languages</h2>
<p>English (Native), Spanish (Conversational)</p>
</body></html>`;

const executablePath = findExecutable();
const browser = await chromium.launch({
  ...(executablePath ? { executablePath } : {}),
  headless: true,
  args: ["--no-sandbox"],
});
const page = await browser.newPage();
await page.setContent(html, { waitUntil: "networkidle" });
const outDir = path.join(process.cwd(), "data");
fs.mkdirSync(outDir, { recursive: true });
const outPath = path.join(outDir, "sample-resume.pdf");
await page.pdf({ path: outPath, format: "A4", printBackground: true });
await browser.close();
console.log(`Wrote ${outPath}`);
