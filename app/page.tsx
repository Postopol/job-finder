"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Crosshair,
  FileText,
  Loader2,
  Plus,
  RefreshCw,
  SettingsIcon,
  Star,
  Trash2,
  Upload,
} from "lucide-react";

interface ResumeListItem {
  resume_id: string;
  title: string | null;
  filename: string | null;
  is_master: boolean;
  is_default_master: boolean;
  parent_id: string | null;
  processing_status: string;
  updated_at: string;
}

interface Health {
  status: string;
  llm: { configured: boolean; provider: string; model: string };
}

export default function Home() {
  const [resumes, setResumes] = useState<ResumeListItem[] | null>(null);
  const [health, setHealth] = useState<Health | null>(null);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [pasteOpen, setPasteOpen] = useState(false);
  const [pasteText, setPasteText] = useState("");
  const [busyId, setBusyId] = useState<string | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    const [resumesRes, healthRes] = await Promise.all([
      fetch("/api/v1/resumes"),
      fetch("/api/v1/health"),
    ]);
    setResumes((await resumesRes.json()).data ?? []);
    setHealth(await healthRes.json());
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const uploadFile = async (file: File) => {
    setUploading(true);
    setUploadError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      const response = await fetch("/api/v1/resumes/upload", {
        method: "POST",
        body: form,
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Upload failed");
      window.location.href = `/builder/${body.data.resume_id}`;
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Upload failed");
      setUploading(false);
    }
  };

  const createFromText = async (text: string) => {
    setUploading(true);
    setUploadError(null);
    try {
      const response = await fetch("/api/v1/resumes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Failed to create resume");
      window.location.href = `/builder/${body.data.resume_id}`;
    } catch (e) {
      setUploadError(e instanceof Error ? e.message : "Failed to create resume");
      setUploading(false);
    }
  };

  const createBlank = async () => {
    setUploading(true);
    try {
      const response = await fetch("/api/v1/resumes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ blank: true }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Failed");
      window.location.href = `/builder/${body.data.resume_id}`;
    } catch {
      setUploading(false);
    }
  };

  const action = async (resume: ResumeListItem, kind: "delete" | "default" | "retry") => {
    setBusyId(resume.resume_id);
    try {
      if (kind === "delete") {
        if (!window.confirm(`Delete “${resume.title ?? "this resume"}”? This cannot be undone.`)) return;
        await fetch(`/api/v1/resumes/${resume.resume_id}`, { method: "DELETE" });
      } else if (kind === "default") {
        await fetch(`/api/v1/resumes/${resume.resume_id}/default`, { method: "POST" });
      } else {
        await fetch(`/api/v1/resumes/${resume.resume_id}/retry-processing`, { method: "POST" });
      }
      await load();
    } finally {
      setBusyId(null);
    }
  };

  return (
    <main className="mx-auto min-h-screen w-full max-w-4xl px-6 py-10">
      <header className="mb-10 flex items-center justify-between">
        <div className="flex items-center gap-2.5">
          <FileText size={22} className="text-[var(--accent-hover)]" />
          <h1 className="text-xl font-semibold tracking-tight">Resume Studio</h1>
        </div>
        <div className="flex items-center gap-2">
          <Link
            href="/match"
            className="flex items-center gap-2 rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--foreground)]"
          >
            <Crosshair size={15} />
            JD Match
          </Link>
          <Link
            href="/settings"
            className="flex items-center gap-2 rounded-md border border-[var(--border)] px-3 py-1.5 text-sm text-[var(--muted)] transition-colors hover:border-[var(--border-strong)] hover:text-[var(--foreground)]"
          >
            <SettingsIcon size={15} />
            Settings
            <span
              className={`h-2 w-2 rounded-full ${health?.llm.configured ? "bg-emerald-400" : "bg-amber-400"}`}
              title={health?.llm.configured ? `${health.llm.provider}: ${health.llm.model}` : "AI not configured"}
            />
          </Link>
        </div>
      </header>

      <section className="mb-10">
        <div
          className={`rounded-xl border-2 border-dashed p-10 text-center transition-colors ${
            dragOver
              ? "border-[var(--accent)] bg-[var(--accent)]/5"
              : "border-[var(--border-strong)]"
          }`}
          onDragOver={(e) => {
            e.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault();
            setDragOver(false);
            const file = e.dataTransfer.files?.[0];
            if (file) uploadFile(file);
          }}
        >
          {uploading ? (
            <div className="flex flex-col items-center gap-3 text-[var(--muted)]">
              <Loader2 size={28} className="animate-spin" />
              <p className="text-sm">
                {health?.llm.configured
                  ? "Extracting text and parsing with AI… this can take up to a minute."
                  : "Uploading… (AI is not configured — parsing will wait)"}
              </p>
            </div>
          ) : (
            <>
              <Upload size={28} className="mx-auto mb-3 text-[var(--muted)]" />
              <p className="text-sm font-medium">Drop your master resume here</p>
              <p className="mt-1 text-xs text-[var(--muted)]">PDF or DOCX, up to 10 MB</p>
              <div className="mt-5 flex items-center justify-center gap-3">
                <button
                  onClick={() => fileInputRef.current?.click()}
                  className="rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-hover)]"
                >
                  Choose file
                </button>
                <button
                  onClick={() => setPasteOpen((v) => !v)}
                  className="rounded-md border border-[var(--border-strong)] px-4 py-2 text-sm font-medium text-[var(--muted)] transition-colors hover:text-[var(--foreground)]"
                >
                  Paste text
                </button>
                <button
                  onClick={createBlank}
                  className="flex items-center gap-1.5 rounded-md px-3 py-2 text-sm text-[var(--muted)] transition-colors hover:text-[var(--foreground)]"
                >
                  <Plus size={15} />
                  Blank
                </button>
              </div>
            </>
          )}
          <input
            ref={fileInputRef}
            type="file"
            accept=".pdf,.docx"
            className="hidden"
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) uploadFile(file);
              e.target.value = "";
            }}
          />
        </div>

        {pasteOpen ? (
          <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-4">
            <textarea
              className="pane-scroll h-40 w-full resize-none rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3 text-sm outline-none focus:border-[var(--accent)]"
              placeholder="Paste your resume text or markdown here…"
              value={pasteText}
              onChange={(e) => setPasteText(e.target.value)}
            />
            <div className="mt-3 flex justify-end gap-2">
              <button
                onClick={() => setPasteOpen(false)}
                className="rounded-md px-4 py-1.5 text-sm text-[var(--muted)] hover:text-[var(--foreground)]"
              >
                Cancel
              </button>
              <button
                onClick={() => createFromText(pasteText)}
                disabled={pasteText.trim().length < 30 || uploading}
                className="rounded-md bg-[var(--accent)] px-4 py-1.5 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50"
              >
                Parse with AI
              </button>
            </div>
          </div>
        ) : null}

        {uploadError ? (
          <p className="mt-3 rounded-md border border-red-500/30 bg-red-500/10 px-3 py-2 text-sm text-red-300">
            {uploadError}
          </p>
        ) : null}
      </section>

      <section>
        <h2 className="mb-4 text-sm font-semibold tracking-wide text-[var(--muted)]">
          YOUR RESUMES
        </h2>
        {resumes === null ? (
          <div className="flex justify-center py-10 text-[var(--muted)]">
            <Loader2 size={22} className="animate-spin" />
          </div>
        ) : resumes.length === 0 ? (
          <p className="rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8 text-center text-sm text-[var(--muted)]">
            No resumes yet. Upload your master resume above — everything is stored locally.
          </p>
        ) : (
          <ul className="space-y-2.5">
            {resumes.map((resume) => (
              <li
                key={resume.resume_id}
                className="group flex items-center gap-4 rounded-lg border border-[var(--border)] bg-[var(--surface)] px-4 py-3 transition-colors hover:border-[var(--border-strong)]"
              >
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <Link
                      href={`/builder/${resume.resume_id}`}
                      className="truncate text-sm font-medium hover:text-[var(--accent-hover)]"
                    >
                      {resume.title ?? resume.filename ?? "Untitled"}
                    </Link>
                    {resume.is_default_master ? (
                      <span className="shrink-0 rounded-full border border-[var(--border-strong)] px-2 py-0.5 text-[10px] uppercase tracking-wide text-[var(--muted)]">
                        Default master
                      </span>
                    ) : null}
                  </div>
                  <div className="mt-0.5 flex items-center gap-2 text-xs text-[var(--muted)]">
                    <StatusBadge status={resume.processing_status} />
                    <span>{new Date(resume.updated_at).toLocaleString()}</span>
                  </div>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  {busyId === resume.resume_id ? (
                    <Loader2 size={15} className="animate-spin text-[var(--muted)]" />
                  ) : (
                    <>
                      {(resume.processing_status === "needs_llm" || resume.processing_status === "error") && (
                        <button
                          onClick={() => action(resume, "retry")}
                          className="rounded p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
                          title="Retry AI parsing"
                        >
                          <RefreshCw size={15} />
                        </button>
                      )}
                      {resume.is_master && !resume.is_default_master && (
                        <button
                          onClick={() => action(resume, "default")}
                          className="rounded p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-amber-300"
                          title="Make default master"
                        >
                          <Star size={15} />
                        </button>
                      )}
                      <button
                        onClick={() => action(resume, "delete")}
                        className="rounded p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-red-400"
                        title="Delete"
                      >
                        <Trash2 size={15} />
                      </button>
                    </>
                  )}
                </div>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  );
}

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, { label: string; cls: string }> = {
    ready: { label: "Ready", cls: "text-emerald-400" },
    needs_llm: { label: "Needs AI setup", cls: "text-amber-400" },
    processing: { label: "Processing", cls: "text-sky-400" },
    pending: { label: "Pending", cls: "text-sky-400" },
    error: { label: "Error", cls: "text-red-400" },
  };
  const { label, cls } = map[status] ?? { label: status, cls: "text-[var(--muted)]" };
  return <span className={`font-medium ${cls}`}>{label}</span>;
}
