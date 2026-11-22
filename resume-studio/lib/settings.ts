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

export class SettingsError extends Error {}

/**
 * A base URL as it is stored: trimmed, without a trailing slash, and absent when it is the
 * provider's own default. Another provider's default endpoint is refused — that is how a key
 * meant for one provider would end up with another.
 */
export function normalizeBaseUrl(provider: Provider, raw: string | undefined): string | undefined {
  let value = raw?.trim();
  while (value?.endsWith("/")) value = value.slice(0, -1);
  if (!value) return undefined;
  let url: URL;
  try {
    url = new URL(value);
  } catch {
    throw new SettingsError("Base URL is not a valid URL.");
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    throw new SettingsError("Base URL must start with http:// or https://.");
  }
  if (value === providerDefaultBaseUrl(provider)) return undefined;
  const owner = PROVIDERS.find((p) => p !== provider && providerDefaultBaseUrl(p) === value);
  if (owner) {
    throw new SettingsError(`That is the ${owner} endpoint — choose ${owner} as the provider instead.`);
  }
  return value;
}

function storedEndpoint(stored: StoredLLMSettings): string | undefined {
  return stored.baseUrl ?? providerDefaultBaseUrl(stored.provider);
}

/** Where a request for this provider and base-URL override actually goes. */
export function effectiveBaseUrl(provider: Provider, override: string | undefined): string | undefined {
  return normalizeBaseUrl(provider, override) ?? providerDefaultBaseUrl(provider);
}

/**
 * Effective settings: DB values, overridden by env vars when set.
 * A key from LLM_API_KEY is paired only with the env provider and base URL (or their
 * defaults), never with ones saved in the UI, so the UI cannot redirect it.
 */
export function getLLMSettings(): LLMSettings {
  const stored = getSetting<StoredLLMSettings>("llm");
  const env = process.env;
  const model = env.LLM_MODEL ?? stored?.model ?? "";
  if (env.LLM_API_KEY) {
    const provider = (env.LLM_PROVIDER as Provider | undefined) ?? "openai";
    return {
      provider,
      model,
      baseUrl: env.LLM_API_BASE ?? providerDefaultBaseUrl(provider),
      apiKey: env.LLM_API_KEY,
    };
  }
  const provider = (env.LLM_PROVIDER as Provider | undefined) ?? stored?.provider ?? "openai";
  const baseUrl = env.LLM_API_BASE ?? stored?.baseUrl ?? providerDefaultBaseUrl(provider);
  // The saved key belongs to the provider and endpoint it was saved with.
  const keyTargetIntact =
    !!stored && provider === stored.provider && baseUrl === storedEndpoint(stored);
  const apiKey =
    keyTargetIntact && stored?.apiKeyEnc ? (decryptSecret(stored.apiKeyEnc) ?? undefined) : undefined;
  return { provider, model, baseUrl, apiKey };
}

/**
 * Saves the settings. Without a new key the saved one is kept only while the provider and
 * base URL stay the same; otherwise it is dropped (returns keyDropped) rather than sent to
 * the new endpoint. Throws SettingsError for a bad base URL.
 */
export function saveLLMSettings(input: {
  provider: Provider;
  model: string;
  baseUrl?: string;
  apiKey?: string | null; // null/undefined/"" = keep existing key
}): { keyDropped: boolean } {
  const stored = getSetting<StoredLLMSettings>("llm");
  const baseUrl = normalizeBaseUrl(input.provider, input.baseUrl);
  let apiKeyEnc = stored?.apiKeyEnc;
  let keyDropped = false;
  if (input.apiKey) {
    apiKeyEnc = encryptSecret(input.apiKey);
  } else if (
    apiKeyEnc &&
    (stored?.provider !== input.provider ||
      storedEndpoint(stored) !== (baseUrl ?? providerDefaultBaseUrl(input.provider)))
  ) {
    apiKeyEnc = undefined;
    keyDropped = true;
  }
  setSetting("llm", {
    provider: input.provider,
    model: input.model,
    baseUrl,
    apiKeyEnc,
  } satisfies StoredLLMSettings);
  return { keyDropped };
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
  const stored = getSetting<StoredLLMSettings>("llm");
  const fromEnv = {
    provider: Boolean(process.env.LLM_PROVIDER),
    model: Boolean(process.env.LLM_MODEL),
    apiKey: Boolean(process.env.LLM_API_KEY),
    baseUrl: Boolean(process.env.LLM_API_BASE),
  };
  return {
    provider: s.provider,
    model: s.model,
    // only an explicit override; the provider default is shown separately as a hint
    baseUrl: process.env.LLM_API_BASE ?? (process.env.LLM_API_KEY ? "" : stored?.baseUrl ?? ""),
    defaultBaseUrl: providerDefaultBaseUrl(s.provider) ?? "",
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
