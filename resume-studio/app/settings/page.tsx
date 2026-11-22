"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { ArrowLeft, CheckCircle2, Loader2, XCircle } from "lucide-react";

interface SettingsData {
  provider: string;
  model: string;
  baseUrl: string;
  hasApiKey: boolean;
  apiKeyFromEnv: boolean;
  providerFromEnv: boolean;
  modelFromEnv: boolean;
  baseUrlFromEnv: boolean;
  configured: boolean;
}

const PROVIDER_INFO: Record<string, { label: string; modelHint: string; keyLabel: string; needsKey: boolean; baseUrlHint?: string }> = {
  openai: { label: "OpenAI", modelHint: "gpt-4.1 / gpt-4o-mini", keyLabel: "sk-…", needsKey: true },
  anthropic: { label: "Anthropic", modelHint: "claude-sonnet-4-5", keyLabel: "sk-ant-…", needsKey: true },
  gemini: { label: "Google Gemini", modelHint: "gemini-2.5-pro", keyLabel: "AIza…", needsKey: true },
  deepseek: { label: "DeepSeek", modelHint: "deepseek-chat", keyLabel: "sk-…", needsKey: true },
  openrouter: { label: "OpenRouter", modelHint: "anthropic/claude-sonnet-4", keyLabel: "sk-or-…", needsKey: true },
  groq: { label: "Groq", modelHint: "llama-3.3-70b-versatile", keyLabel: "gsk_…", needsKey: true },
  ollama: { label: "Ollama (local)", modelHint: "llama3.1 / qwen2.5", keyLabel: "not needed", needsKey: false, baseUrlHint: "http://localhost:11434/v1" },
  custom: { label: "Custom (OpenAI-compatible)", modelHint: "any model id", keyLabel: "API key", needsKey: false, baseUrlHint: "https://your-endpoint/v1" },
};

export default function SettingsPage() {
  const [data, setData] = useState<SettingsData | null>(null);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [baseUrl, setBaseUrl] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; error?: string } | null>(null);
  const [message, setMessage] = useState<{ kind: "ok" | "err"; text: string } | null>(null);

  useEffect(() => {
    fetch("/api/v1/settings")
      .then((r) => r.json())
      .then((body) => {
        const d: SettingsData = body.data;
        setData(d);
        setProvider(d.provider);
        setModel(d.model);
        setBaseUrl(d.baseUrl);
      });
  }, []);

  const save = async () => {
    setSaving(true);
    setMessage(null);
    try {
      const response = await fetch("/api/v1/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          model,
          baseUrl: baseUrl || undefined,
          apiKey: apiKey || undefined,
        }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.error ?? "Save failed");
      setData(body.data);
      setApiKey("");
      setMessage({ kind: "ok", text: "Settings saved." });
    } catch (e) {
      setMessage({ kind: "err", text: e instanceof Error ? e.message : "Save failed" });
    } finally {
      setSaving(false);
    }
  };

  const test = useCallback(async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const response = await fetch("/api/v1/settings/test", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          provider,
          model,
          baseUrl: baseUrl || undefined,
          ...(apiKey ? { apiKey } : {}),
        }),
      });
      setTestResult(await response.json());
    } catch {
      setTestResult({ ok: false, error: "Request failed" });
    } finally {
      setTesting(false);
    }
  }, [provider, model, baseUrl, apiKey]);

  if (!data) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <Loader2 size={24} className="animate-spin text-[var(--muted)]" />
      </div>
    );
  }

  const info = PROVIDER_INFO[provider] ?? PROVIDER_INFO.custom;
  const inputCls =
    "w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-3 py-2 text-sm outline-none transition-colors focus:border-[var(--accent)] placeholder:text-[var(--muted)]";

  return (
    <main className="mx-auto min-h-screen w-full max-w-xl px-6 py-10">
      <header className="mb-8 flex items-center gap-3">
        <Link
          href="/"
          className="rounded p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface)] hover:text-[var(--foreground)]"
        >
          <ArrowLeft size={18} />
        </Link>
        <h1 className="text-xl font-semibold tracking-tight">AI Settings</h1>
        <span
          className={`ml-auto flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs ${
            data.configured
              ? "border-emerald-500/30 text-emerald-400"
              : "border-amber-500/30 text-amber-400"
          }`}
        >
          <span className={`h-1.5 w-1.5 rounded-full ${data.configured ? "bg-emerald-400" : "bg-amber-400"}`} />
          {data.configured ? "Configured" : "Not configured"}
        </span>
      </header>

      <div className="space-y-5 rounded-xl border border-[var(--border)] bg-[var(--surface)] p-6">
        <label className="block">
          <span className="mb-1.5 block text-xs font-medium text-[var(--muted)]">Provider</span>
          <select className={inputCls} value={provider} onChange={(e) => setProvider(e.target.value)}>
            {Object.entries(PROVIDER_INFO).map(([value, p]) => (
              <option key={value} value={value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>

        <label className="block">
          <span className="mb-1.5 block text-xs font-medium text-[var(--muted)]">Model</span>
          <input
            className={inputCls}
            value={model}
            placeholder={info.modelHint}
            onChange={(e) => setModel(e.target.value)}
          />
          {data.modelFromEnv ? (
            <span className="mt-1 block text-xs text-amber-400">Overridden by LLM_MODEL env var</span>
          ) : null}
        </label>

        {provider === "ollama" || provider === "custom" || baseUrl ? (
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-[var(--muted)]">
              Base URL {provider === "custom" ? "(required)" : "(optional override)"}
            </span>
            <input
              className={inputCls}
              value={baseUrl}
              placeholder={info.baseUrlHint ?? "https://api.provider.com/v1"}
              onChange={(e) => setBaseUrl(e.target.value)}
            />
          </label>
        ) : null}

        {info.needsKey || provider === "custom" ? (
          <label className="block">
            <span className="mb-1.5 block text-xs font-medium text-[var(--muted)]">API key</span>
            <input
              className={inputCls}
              type="password"
              value={apiKey}
              placeholder={
                data.apiKeyFromEnv
                  ? "Set via LLM_API_KEY env"
                  : data.hasApiKey
                    ? "•••••••• (saved — leave blank to keep)"
                    : info.keyLabel
              }
              onChange={(e) => setApiKey(e.target.value)}
              autoComplete="off"
            />
            <span className="mt-1 block text-xs text-[var(--muted)]">
              Stored encrypted in your local database. Never sent anywhere except the provider.
            </span>
          </label>
        ) : null}

        {provider === "ollama" ? (
          <p className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3 text-xs text-[var(--muted)]">
            Fully local: run <code className="text-[var(--foreground)]">ollama serve</code>, pull a model
            (<code className="text-[var(--foreground)]">ollama pull llama3.1</code>) and set the model id above.
            Your resume never leaves this machine.
          </p>
        ) : null}

        <div className="flex items-center gap-3 pt-2">
          <button
            onClick={save}
            disabled={saving || !model.trim()}
            className="rounded-md bg-[var(--accent)] px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-50"
          >
            {saving ? "Saving…" : "Save settings"}
          </button>
          <button
            onClick={test}
            disabled={testing || !model.trim()}
            className="rounded-md border border-[var(--border-strong)] px-4 py-2 text-sm font-medium transition-colors hover:bg-[var(--surface-2)] disabled:opacity-50"
          >
            {testing ? "Testing…" : "Test connection"}
          </button>
          {testResult ? (
            testResult.ok ? (
              <span className="flex items-center gap-1.5 text-xs text-emerald-400">
                <CheckCircle2 size={14} /> Connection OK
              </span>
            ) : (
              <span className="flex items-center gap-1.5 text-xs text-red-400" title={testResult.error}>
                <XCircle size={14} />
                <span className="max-w-[220px] truncate">{testResult.error}</span>
              </span>
            )
          ) : null}
        </div>

        {message ? (
          <p className={`text-sm ${message.kind === "ok" ? "text-emerald-400" : "text-red-400"}`}>
            {message.text}
          </p>
        ) : null}
      </div>
    </main>
  );
}
