"use client";

import { useState } from "react";
import Link from "next/link";
import { Loader2, RefreshCw, SettingsIcon } from "lucide-react";

export function BuilderNotReady({
  status,
  error,
  resumeId,
}: {
  status: string;
  error: string | null;
  resumeId: string;
}) {
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);

  const retry = async () => {
    setBusy(true);
    setMessage(null);
    try {
      const response = await fetch(`/api/v1/resumes/${resumeId}/retry-processing`, {
        method: "POST",
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Retry failed");
      window.location.reload();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : "Retry failed");
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md rounded-xl border border-[var(--border)] bg-[var(--surface)] p-8 text-center">
        <h1 className="text-lg font-semibold">
          {status === "needs_llm"
            ? "AI parsing is not configured"
            : status === "error"
              ? "Processing failed"
              : "Processing…"}
        </h1>
        <p className="mt-2 text-sm text-[var(--muted)]">
          {status === "needs_llm"
            ? "This resume was uploaded, but its text has not been parsed into an editable structure yet. Configure an AI provider, then retry."
            : (error ?? "The resume has no structured data yet.")}
        </p>
        <div className="mt-6 flex justify-center gap-3">
          <Link
            href="/settings"
            className="flex items-center gap-2 rounded-md border border-[var(--border-strong)] px-4 py-2 text-sm font-medium transition-colors hover:bg-[var(--surface-2)]"
          >
            <SettingsIcon size={15} />
            Open Settings
          </Link>
          {status !== "processing" ? (
            <button
              onClick={retry}
              disabled={busy}
              className="flex items-center gap-2 rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-60"
            >
              {busy ? <Loader2 size={15} className="animate-spin" /> : <RefreshCw size={15} />}
              Retry processing
            </button>
          ) : null}
        </div>
        {message ? (
          <p className="mt-4 text-sm text-red-400">{message}</p>
        ) : null}
      </div>
    </div>
  );
}
