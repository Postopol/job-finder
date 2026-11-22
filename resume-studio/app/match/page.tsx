"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, Briefcase, Loader2, Search, Trash2 } from "lucide-react";
import type { ResumeData } from "@/lib/schema";
import type { AtsScore } from "@/lib/ats";
import { AtsScoreCard } from "@/components/match/ats-score-card";
import { HighlightedResume } from "@/components/match/highlighted-resume";

interface ResumeListItem {
  resume_id: string;
  title: string | null;
  is_master: boolean;
  is_default_master: boolean;
  processing_status: string;
}

interface JobListItem {
  job_id: string;
  company: string | null;
  role: string | null;
  snippet: string;
  created_at: string;
}

interface MatchResult {
  resume_id: string;
  job_id: string;
  role: string;
  company: string;
  ats: AtsScore;
}

const MIN_JD_CHARS = 50;

export default function MatchPage() {
  const [resumes, setResumes] = useState<ResumeListItem[] | null>(null);
  const [jobs, setJobs] = useState<JobListItem[]>([]);
  const [resumeId, setResumeId] = useState<string>("");
  const [jdText, setJdText] = useState("");
  const [selectedJobId, setSelectedJobId] = useState<string | null>(null);
  const [analyzing, setAnalyzing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<MatchResult | null>(null);
  const [resumeData, setResumeData] = useState<ResumeData | null>(null);
  const [busyJobId, setBusyJobId] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [resumesRes, jobsRes] = await Promise.all([
      fetch("/api/v1/resumes"),
      fetch("/api/v1/jobs"),
    ]);
    const resumeList = ((await resumesRes.json()).data ?? []) as ResumeListItem[];
    setResumes(resumeList);
    setJobs(((await jobsRes.json()).data ?? []) as JobListItem[]);
    setResumeId((current) => {
      if (current) return current;
      const ready = resumeList.filter((r) => r.processing_status === "ready");
      return (
        ready.find((r) => r.is_default_master)?.resume_id ??
        ready[0]?.resume_id ??
        ""
      );
    });
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const pickJob = async (job: JobListItem) => {
    setBusyJobId(job.job_id);
    setError(null);
    try {
      const response = await fetch(`/api/v1/jobs/${job.job_id}`);
      if (!response.ok) throw new Error("Failed to load job");
      const body = await response.json();
      setJdText(body.data.content as string);
      setSelectedJobId(job.job_id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load job");
    } finally {
      setBusyJobId(null);
    }
  };

  const deleteJob = async (job: JobListItem) => {
    if (!window.confirm("Delete this job description?")) return;
    setBusyJobId(job.job_id);
    try {
      await fetch(`/api/v1/jobs/${job.job_id}`, { method: "DELETE" });
      if (selectedJobId === job.job_id) {
        setSelectedJobId(null);
        setJdText("");
      }
      await load();
    } finally {
      setBusyJobId(null);
    }
  };

  const analyze = async () => {
    if (!resumeId || jdText.trim().length < MIN_JD_CHARS) return;
    setAnalyzing(true);
    setError(null);
    setResult(null);
    try {
      let jobId = selectedJobId;
      if (!jobId) {
        const createRes = await fetch("/api/v1/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ job_description: jdText.trim() }),
        });
        const createBody = await createRes.json();
        if (!createRes.ok) {
          throw new Error(createBody.error ?? "Failed to save job description");
        }
        jobId = createBody.data.job_id as string;
        setSelectedJobId(jobId);
      }

      const [atsRes, resumeRes] = await Promise.all([
        fetch(`/api/v1/ats?resumeId=${resumeId}&jobId=${jobId}`),
        fetch(`/api/v1/resumes/${resumeId}`),
      ]);
      const atsBody = await atsRes.json();
      if (!atsRes.ok) {
        throw new Error(atsBody.error ?? "Analysis failed");
      }
      setResult(atsBody.data as MatchResult);
      setResumeData(
        ((await resumeRes.json()).data?.processed_data as ResumeData) ?? null,
      );
      await load();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  };

  const readyResumes = (resumes ?? []).filter(
    (r) => r.processing_status === "ready",
  );
  const canAnalyze =
    Boolean(resumeId) && jdText.trim().length >= MIN_JD_CHARS && !analyzing;

  return (
    <main className="mx-auto min-h-screen w-full max-w-6xl px-6 py-10">
      <header className="mb-8 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <Link
            href="/"
            className="rounded-md p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
          >
            <ArrowLeft size={18} />
          </Link>
          <Briefcase size={20} className="text-[var(--accent-hover)]" />
          <h1 className="text-xl font-semibold tracking-tight">JD Match</h1>
        </div>
      </header>

      <div className="grid gap-8 lg:grid-cols-[minmax(0,5fr)_minmax(0,4fr)]">
        {/* Left: input */}
        <section className="space-y-5">
          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
              Resume
            </label>
            {resumes === null ? (
              <div className="flex justify-center py-4 text-[var(--muted)]">
                <Loader2 size={18} className="animate-spin" />
              </div>
            ) : readyResumes.length === 0 ? (
              <p className="rounded-md border border-amber-500/30 bg-amber-500/10 px-3 py-2 text-sm text-amber-300">
                No parsed resumes yet. Upload your master resume first.
              </p>
            ) : (
              <select
                value={resumeId}
                onChange={(e) => setResumeId(e.target.value)}
                className="w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm outline-none focus:border-[var(--accent)]"
              >
                {readyResumes.map((r) => (
                  <option key={r.resume_id} value={r.resume_id}>
                    {r.title ?? "Untitled"}
                    {r.is_default_master ? " (default master)" : ""}
                  </option>
                ))}
              </select>
            )}
          </div>

          <div>
            <label className="mb-1.5 block text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
              Job description
            </label>
            <textarea
              className="pane-scroll h-64 w-full resize-y rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3 text-sm outline-none focus:border-[var(--accent)]"
              placeholder="Paste the job description here…"
              value={jdText}
              onChange={(e) => {
                setJdText(e.target.value);
                setSelectedJobId(null);
              }}
            />
            <div className="mt-3 flex items-center justify-between">
              <span className="text-xs text-[var(--muted)]">
                {jdText.trim().length < MIN_JD_CHARS
                  ? `At least ${MIN_JD_CHARS} characters`
                  : `${jdText.trim().length.toLocaleString()} characters`}
              </span>
              <button
                onClick={analyze}
                disabled={!canAnalyze}
                className="flex items-center gap-2 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50"
              >
                {analyzing ? (
                  <Loader2 size={15} className="animate-spin" />
                ) : (
                  <Search size={15} />
                )}
                {analyzing ? "Analyzing…" : "Analyze"}
              </button>
            </div>
            {error ? (
              <p className="mt-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
                {error}
              </p>
            ) : null}
          </div>

          {jobs.length ? (
            <div>
              <h2 className="mb-2 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
                Saved jobs
              </h2>
              <ul className="space-y-1.5">
                {jobs.map((job) => (
                  <li
                    key={job.job_id}
                    className={`group flex items-center gap-3 rounded-lg border px-3 py-2 text-sm transition-colors ${
                      selectedJobId === job.job_id
                        ? "border-[var(--accent)] bg-[var(--accent)]/5"
                        : "border-[var(--border)] bg-[var(--surface)] hover:border-[var(--border-strong)]"
                    }`}
                  >
                    <button
                      onClick={() => pickJob(job)}
                      className="min-w-0 flex-1 text-left"
                    >
                      <span className="block truncate font-medium">
                        {job.role || "Untitled role"}
                        {job.company ? (
                          <span className="text-[var(--muted)]"> — {job.company}</span>
                        ) : null}
                      </span>
                      <span className="block truncate text-xs text-[var(--muted)]">
                        {job.snippet}
                      </span>
                    </button>
                    {busyJobId === job.job_id ? (
                      <Loader2 size={14} className="animate-spin text-[var(--muted)]" />
                    ) : (
                      <button
                        onClick={() => deleteJob(job)}
                        className="rounded p-1 text-[var(--muted)] opacity-0 transition-opacity hover:text-red-400 group-hover:opacity-100"
                        title="Delete job"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </li>
                ))}
              </ul>
            </div>
          ) : null}
        </section>

        {/* Right: results */}
        <section className="space-y-6">
          {result ? (
            <>
              <div>
                <h2 className="text-sm font-medium">
                  {result.role || "Match analysis"}
                </h2>
                {result.company ? (
                  <p className="text-xs text-[var(--muted)]">{result.company}</p>
                ) : null}
              </div>
              <AtsScoreCard ats={result.ats} />
              {resumeData ? (
                <div className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-5">
                  <h3 className="mb-4 text-xs font-semibold uppercase tracking-wide text-[var(--muted)]">
                    Your resume — matched keywords highlighted
                  </h3>
                  <HighlightedResume
                    resume={resumeData}
                    matchedKeywords={result.ats.matched_keywords}
                  />
                </div>
              ) : null}
            </>
          ) : (
            <div className="flex h-full min-h-64 flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-[var(--border-strong)] p-8 text-center text-[var(--muted)]">
              {analyzing ? (
                <>
                  <Loader2 size={24} className="animate-spin" />
                  <p className="text-sm">
                    Extracting JD keywords and scoring…
                  </p>
                </>
              ) : (
                <>
                  <Search size={24} />
                  <p className="max-w-64 text-sm">
                    Pick a resume, paste a job description and hit Analyze to
                    see the ATS score and keyword match.
                  </p>
                </>
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}
