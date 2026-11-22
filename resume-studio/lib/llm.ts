import { generateObject, type FlexibleSchema } from "ai";
import { createOpenAI } from "@ai-sdk/openai";
import { createAnthropic } from "@ai-sdk/anthropic";
import { createGoogleGenerativeAI } from "@ai-sdk/google";
import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import type { LanguageModel } from "ai";
import { z } from "zod";
import {
  getLLMSettings,
  type LLMSettings,
  providerNeedsApiKey,
} from "./settings";

/**
 * Multi-provider LLM chokepoint — the equivalent of the original's llm.py.
 * Every AI call in the app goes through generateStructured() so retries,
 * timeouts and validation stay uniform across providers.
 */

const DEFAULT_TIMEOUT_MS = Number(process.env.LLM_TIMEOUT_MS) || 180_000;

export class LLMNotConfiguredError extends Error {
  constructor() {
    super("LLM is not configured. Add a provider in Settings first.");
    this.name = "LLMNotConfiguredError";
  }
}

export function resolveModel(settings?: LLMSettings): LanguageModel {
  const s = settings ?? getLLMSettings();
  if (!s.model) throw new LLMNotConfiguredError();
  if (providerNeedsApiKey(s.provider) && !s.apiKey) {
    throw new LLMNotConfiguredError();
  }

  switch (s.provider) {
    case "openai": {
      const openai = createOpenAI({
        apiKey: s.apiKey,
        ...(s.baseUrl ? { baseURL: s.baseUrl } : {}),
      });
      return openai(s.model);
    }
    case "anthropic": {
      const anthropic = createAnthropic({
        apiKey: s.apiKey,
        ...(s.baseUrl ? { baseURL: s.baseUrl } : {}),
      });
      return anthropic(s.model);
    }
    case "gemini": {
      const google = createGoogleGenerativeAI({
        apiKey: s.apiKey,
        ...(s.baseUrl ? { baseURL: s.baseUrl } : {}),
      });
      return google(s.model);
    }
    case "deepseek":
    case "openrouter":
    case "groq":
    case "ollama":
    case "custom": {
      if (!s.baseUrl) throw new LLMNotConfiguredError();
      const provider = createOpenAICompatible({
        name: s.provider,
        baseURL: s.baseUrl,
        apiKey: s.apiKey ?? "not-needed",
      });
      return provider(s.model);
    }
  }
}

export interface GenerateStructuredOptions<SCHEMA extends z.ZodObject> {
  system: string;
  prompt: string;
  schema: SCHEMA;
  maxOutputTokens?: number;
  timeoutMs?: number;
}

export async function generateStructured<SCHEMA extends z.ZodObject>(
  options: GenerateStructuredOptions<SCHEMA>,
): Promise<z.infer<SCHEMA>> {
  const model = resolveModel();
  const { object } = await generateObject({
    model,
    schema: options.schema as FlexibleSchema<z.infer<SCHEMA>>,
    system: options.system,
    prompt: options.prompt,
    maxOutputTokens: options.maxOutputTokens,
    abortSignal: AbortSignal.timeout(options.timeoutMs ?? DEFAULT_TIMEOUT_MS),
  });
  // The SDK's RESULT type is a deferred conditional for open generics; the
  // runtime value is schema-validated, so the cast is safe and contained.
  return object as z.infer<SCHEMA>;
}

/** Tiny round-trip used by "Test connection" in Settings. */
export async function testLLMConnection(
  settings?: LLMSettings,
): Promise<{ ok: true } | { ok: false; error: string }> {
  try {
    const model = resolveModel(settings);
    const { object } = await generateObject({
      model,
      schema: pingSchema,
      system: "You are a connection test. Reply with the JSON asked.",
      prompt: 'Return {"ok": true}.',
      abortSignal: AbortSignal.timeout(20_000),
    });
    return object.ok
      ? { ok: true }
      : { ok: false, error: "Model replied unexpectedly." };
  } catch (error) {
    const message =
      error instanceof Error ? error.message : "Unknown connection error";
    return { ok: false, error: message };
  }
}

const pingSchema = z.object({ ok: z.boolean() });
