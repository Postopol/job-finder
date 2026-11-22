"use client";

import { useMemo } from "react";
import type { ResumeData } from "@/lib/schema";
import { sectionVisible } from "@/lib/schema";

/**
 * Plain-text resume view with matched JD keywords highlighted — the port
 * of the original's highlighted-resume-view. Only visible sections render,
 * because that is all an ATS would parse.
 */

// Same boundary semantics as lib/text-match.ts, kept client-side so the
// highlight matches the scoring exactly: word chars bound Latin terms,
// CJK chars bound themselves.
const CJK =
  "[ᄀ-ᇿ぀-ヿ㄰-㆏ㇰ-ㇿ㐀-鿿ꥠ-꥿가-퟿豈-﫿ｦ-ￜ\\u{1b000}-\\u{1b16f}\\u{20000}-\\u{3ffff}]";

function buildHighlightRegex(keywords: string[]): RegExp | null {
  const terms = keywords
    .map((k) => k.trim().toLowerCase())
    .filter(Boolean)
    // Longest first so "Node.js" wins over "Node"
    .sort((a, b) => b.length - a.length)
    .map((k) => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
  if (!terms.length) return null;
  return new RegExp(
    `(?:(?<!\\w)|(?<=${CJK}))(?:${terms.join("|")})(?:(?!\\w)|(?=${CJK}))`,
    "giu",
  );
}

function Highlight({ text, regex }: { text: string; regex: RegExp | null }) {
  if (!regex) return <>{text}</>;
  const parts: (string | { match: string })[] = [];
  let last = 0;
  for (const m of text.matchAll(regex)) {
    const index = m.index ?? 0;
    if (index > last) parts.push(text.slice(last, index));
    parts.push({ match: m[0] });
    last = index + m[0].length;
  }
  if (last < text.length) parts.push(text.slice(last));
  return (
    <>
      {parts.map((part, i) =>
        typeof part === "string" ? (
          part
        ) : (
          <mark
            key={i}
            className="rounded-sm bg-emerald-500/25 px-0.5 text-emerald-200"
          >
            {part.match}
          </mark>
        ),
      )}
    </>
  );
}

interface Block {
  heading: string;
  /** Entries; within an entry the first line is emphasized, the rest are bullets. */
  entries: string[][];
}

export function HighlightedResume({
  resume,
  matchedKeywords,
}: {
  resume: ResumeData;
  matchedKeywords: string[];
}) {
  const regex = useMemo(
    () => buildHighlightRegex(matchedKeywords),
    [matchedKeywords],
  );

  const blocks: Block[] = [];
  const push = (heading: string, entries: string[][]) => {
    if (entries.some((lines) => lines.some((l) => l.trim()))) {
      blocks.push({ heading, entries });
    }
  };

  if (sectionVisible(resume, "summary") && resume.summary.trim()) {
    push("Summary", [[resume.summary]]);
  }
  if (sectionVisible(resume, "workExperience") && resume.workExperience.length) {
    push(
      "Experience",
      resume.workExperience.map((e) => [
        [e.title, e.company, e.years].filter(Boolean).join(" · "),
        ...e.description,
      ]),
    );
  }
  if (
    sectionVisible(resume, "personalProjects") &&
    resume.personalProjects.length
  ) {
    push(
      "Projects",
      resume.personalProjects.map((p) => [
        [p.name, p.role, p.years].filter(Boolean).join(" · "),
        ...p.description,
      ]),
    );
  }
  if (sectionVisible(resume, "education") && resume.education.length) {
    push(
      "Education",
      resume.education.map((e) => [
        [e.degree, e.institution, e.years, e.description ?? ""]
          .filter(Boolean)
          .join(" · "),
      ]),
    );
  }
  if (sectionVisible(resume, "skills") && resume.skills.length) {
    push("Skills", [[resume.skills.join(", ")]]);
  }
  const simpleLists: [keyof ResumeData, string][] = [
    ["certifications", "Certifications"],
    ["languages", "Languages"],
    ["awards", "Awards"],
  ];
  for (const [key, label] of simpleLists) {
    const items = resume[key] as string[];
    if (items.length && sectionVisible(resume, key)) {
      push(label, [[items.join(", ")]]);
    }
  }
  for (const section of resume.customSections) {
    if (!sectionVisible(resume, section.key)) continue;
    if (section.sectionType === "text" && section.text.trim()) {
      push(section.title || section.key, [[section.text]]);
    } else if (section.sectionType === "stringList" && section.strings.length) {
      push(section.title || section.key, [[section.strings.join(", ")]]);
    } else if (section.sectionType === "itemList" && section.items.length) {
      push(
        section.title || section.key,
        section.items.map((item) => [
          [item.title, item.subtitle, item.years].filter(Boolean).join(" · "),
          ...item.description,
        ]),
      );
    }
  }

  return (
    <div className="space-y-5 text-sm leading-relaxed">
      <div>
        <h2 className="text-base font-semibold">
          <Highlight text={resume.personalInfo.name} regex={regex} />
        </h2>
        <p className="text-[var(--muted)]">
          <Highlight
            text={[resume.personalInfo.title, resume.personalInfo.location]
              .filter(Boolean)
              .join(" · ")}
            regex={regex}
          />
        </p>
      </div>
      {blocks.map((block, i) => (
        <div key={i}>
          <h3 className="mb-1.5 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
            {block.heading}
          </h3>
          <div className="space-y-2.5">
            {block.entries.map((lines, j) => (
              <div key={j} className="space-y-1">
                {lines.map((line, k) =>
                  k === 0 && lines.length > 1 ? (
                    <p key={k} className="font-medium">
                      <Highlight text={line} regex={regex} />
                    </p>
                  ) : (
                    <p key={k} className="pl-3 text-[var(--muted)]">
                      <Highlight text={line} regex={regex} />
                    </p>
                  ),
                )}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
