"use client";

import type { AtsScore } from "@/lib/ats";

/** Overall + sub-scores + keyword chips + recommendations. */

const SUB_SCORE_META: {
  key: keyof AtsScore["sub_scores"];
  label: string;
  weight: string;
}[] = [
  { key: "keyword_match", label: "Keyword match", weight: "40%" },
  { key: "skills_coverage", label: "Skills coverage", weight: "20%" },
  { key: "title_match", label: "Title match", weight: "15%" },
  { key: "section_completeness", label: "Section completeness", weight: "15%" },
  { key: "date_consistency", label: "Date consistency", weight: "10%" },
];

function scoreColor(score: number): string {
  if (score >= 70) return "text-emerald-400";
  if (score >= 40) return "text-amber-400";
  return "text-red-400";
}

function barColor(score: number): string {
  if (score >= 70) return "bg-emerald-400";
  if (score >= 40) return "bg-amber-400";
  return "bg-red-400";
}

export function AtsScoreCard({ ats }: { ats: AtsScore }) {
  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center gap-8 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
        <div className="flex flex-col items-center">
          <span className={`text-5xl font-semibold tabular-nums ${scoreColor(ats.overall_score)}`}>
            {ats.overall_score.toFixed(0)}
          </span>
          <span className="mt-1 text-xs uppercase tracking-wide text-[var(--muted)]">
            ATS score
          </span>
        </div>
        <div className="min-w-64 flex-1 space-y-2.5">
          {SUB_SCORE_META.map(({ key, label, weight }) => {
            const value = ats.sub_scores[key];
            return (
              <div key={key} className="flex items-center gap-3 text-sm">
                <span className="w-44 shrink-0 text-[var(--muted)]">
                  {label}
                  <span className="ml-1.5 text-[10px] opacity-60">{weight}</span>
                </span>
                <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-[var(--surface-2)]">
                  {value !== null ? (
                    <div
                      className={`h-full rounded-full ${barColor(value)}`}
                      style={{ width: `${Math.min(100, value)}%` }}
                    />
                  ) : null}
                </div>
                <span
                  className={`w-10 shrink-0 text-right tabular-nums ${
                    value === null ? "text-[var(--muted)]" : scoreColor(value)
                  }`}
                >
                  {value === null ? "—" : value.toFixed(0)}
                </span>
              </div>
            );
          })}
        </div>
      </div>

      <KeywordGroup
        label="Matched"
        keywords={ats.matched_keywords}
        className="border-emerald-500/25 bg-emerald-500/10 text-emerald-300"
      />
      <KeywordGroup
        label="Missing"
        keywords={ats.missing_keywords}
        className="border-red-500/25 bg-red-500/10 text-red-300"
      />
      {ats.injectable_keywords.length ? (
        <KeywordGroup
          label="In your master, not in this version"
          keywords={ats.injectable_keywords}
          className="border-amber-500/25 bg-amber-500/10 text-amber-300"
        />
      ) : null}

      <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
        <h3 className="mb-3 text-sm font-semibold">Recommendations</h3>
        <ul className="space-y-2">
          {ats.recommendations.map((tip, i) => (
            <li key={i} className="flex gap-2.5 text-sm text-[var(--muted)]">
              <span className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--accent)]" />
              {tip}
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

function KeywordGroup({
  label,
  keywords,
  className,
}: {
  label: string;
  keywords: string[];
  className: string;
}) {
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
        {label} ({keywords.length})
      </h3>
      {keywords.length === 0 ? (
        <p className="text-sm text-[var(--muted)]">None</p>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {keywords.map((kw) => (
            <span
              key={kw}
              className={`rounded-full border px-2.5 py-0.5 text-xs ${className}`}
            >
              {kw}
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
