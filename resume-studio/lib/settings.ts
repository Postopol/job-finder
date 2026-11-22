import { getSetting, setSetting } from "./db";
import { decryptSecret, encryptSecret } from "./crypto";

/**
 * LLM provider settings — stored in the DB (API key encrypted at rest),
 * with env vars as explicit overrides, exactly like the original:
 *   LLM_PROVIDER, LLM_MODEL, LLM_API_KEY, LLM_API_BASE
 */

export const PROVIDERS = [
  "openai",
  "anthropic",
  "gemini",
  "deepseek",
  "openrouter",
  "groq",
  "ollama",
  "custom",
] as const;
export type Provider = (typeof PROVIDERS)[number];

export interface LLMSettings {
  provider: Provider;
  model: string;
  baseUrl?: string;
  apiKey?: string; // plaintext, only in memory / env
}

interface StoredLLMSettings {
  provider: Provider;
  model: string;
  baseUrl?: string;
  apiKeyEnc?: string;
}

const PROVIDER_DEFAULT_BASE_URLS: Record<Provider, string | undefined> = {
  openai: undefined, // SDK default
  anthropic: undefined,
  gemini: undefined,
  deepseek: "https://api.deepseek.com/v1",
  openrouter: "https://openrouter.ai/api/v1",
  groq: "https://api.groq.com/openai/v1",
  ollama: "http://localhost:11434/v1",
  custom: undefined, // required from user
};

export function providerNeedsApiKey(provider: Provider): boolean {
  return provider !== "ollama";
}

export function providerDefaultBaseUrl(provider: Provider): string | undefined {
  return PROVIDER_DEFAULT_BASE_URLS[provider];
}

/** Effective settings: DB values, overridden by env vars when set. */
export function getLLMSettings(): LLMSettings {
  const stored = getSetting<StoredLLMSettings>("llm");
  const provider = (process.env.LLM_PROVIDER as Provider | undefined) ?? stored?.provider ?? "openai";
  const model = process.env.LLM_MODEL ?? stored?.model ?? "";
  const baseUrl =
    process.env.LLM_API_BASE ??
    stored?.baseUrl ??
    providerDefaultBaseUrl(provider);
  const apiKey =
    process.env.LLM_API_KEY ??
    (stored?.apiKeyEnc ? decryptSecret(stored.apiKeyEnc) : undefined) ??
    undefined;
  return { provider, model, baseUrl, apiKey };
}

export function saveLLMSettings(input: {
  provider: Provider;
  model: string;
  baseUrl?: string;
  apiKey?: string | null; // null/undefined/"" = keep existing key
}): void {
  const stored = getSetting<StoredLLMSettings>("llm");
  let apiKeyEnc = stored?.apiKeyEnc;
  if (input.apiKey === null || input.apiKey === "") {
    // explicit clear not supported via this path; keep existing
  } else if (input.apiKey !== undefined) {
    apiKeyEnc = input.apiKey ? encryptSecret(input.apiKey) : undefined;
  }
  setSetting("llm", {
    provider: input.provider,
    model: input.model,
    baseUrl: input.baseUrl || undefined,
    apiKeyEnc,
  } satisfies StoredLLMSettings);
}

export function clearLLMApiKey(): void {
  const stored = getSetting<StoredLLMSettings>("llm");
  if (stored) {
    setSetting("llm", { ...stored, apiKeyEnc: undefined });
  }
}

/** Settings with the secret redacted, for the settings UI. */
export function getRedactedLLMSettings() {
  const s = getLLMSettings();
  const fromEnv = {
    provider: Boolean(process.env.LLM_PROVIDER),
    model: Boolean(process.env.LLM_MODEL),
    apiKey: Boolean(process.env.LLM_API_KEY),
    baseUrl: Boolean(process.env.LLM_API_BASE),
  };
  return {
    provider: s.provider,
    model: s.model,
    baseUrl: s.baseUrl ?? "",
    hasApiKey: Boolean(s.apiKey),
    apiKeyFromEnv: fromEnv.apiKey,
    providerFromEnv: fromEnv.provider,
    modelFromEnv: fromEnv.model,
    baseUrlFromEnv: fromEnv.baseUrl,
    configured: isLLMConfigured(),
  };
}

export function isLLMConfigured(): boolean {
  const s = getLLMSettings();
  if (!s.model) return false;
  if (providerNeedsApiKey(s.provider) && !s.apiKey) return false;
  if (s.provider === "custom" && !s.baseUrl) return false;
  return true;
}
