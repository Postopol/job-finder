import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { testLLMConnection } from "@/lib/llm";
import { PROVIDERS, SettingsError, effectiveBaseUrl, getLLMSettings, type Provider } from "@/lib/settings";

const bodySchema = z.object({
  provider: z.string().optional(),
  model: z.string().optional(),
  baseUrl: z.string().optional(),
  apiKey: z.string().optional(),
});

export async function POST(request: NextRequest) {
  let override: z.infer<typeof bodySchema> | undefined;
  try {
    const body = await request.json();
    const parsed = bodySchema.safeParse(body ?? {});
    override = parsed.success ? parsed.data : undefined;
  } catch {
    override = undefined;
  }

  const current = getLLMSettings();
  const requested = override?.provider ?? current.provider;
  if (!(PROVIDERS as readonly string[]).includes(requested)) {
    return NextResponse.json({ ok: false, error: "Unknown provider." }, { status: 400 });
  }
  const provider = requested as Provider;
  let baseUrl: string | undefined;
  try {
    // no override: the saved endpoint when the provider is unchanged, else that provider's default
    baseUrl = override?.baseUrl
      ? effectiveBaseUrl(provider, override.baseUrl)
      : provider === current.provider
        ? current.baseUrl
        : effectiveBaseUrl(provider, undefined);
  } catch (e) {
    if (e instanceof SettingsError) {
      return NextResponse.json({ ok: false, error: e.message }, { status: 400 });
    }
    throw e;
  }
  // The stored key goes only where it was saved for: a test against another provider or
  // endpoint must bring its own key, otherwise the key could be sent to any URL.
  const sameTarget = provider === current.provider && baseUrl === current.baseUrl;
  if (override && !override.apiKey && !sameTarget && current.apiKey) {
    return NextResponse.json(
      {
        ok: false,
        error: "Enter the API key to test a different provider or base URL — the saved key is only sent to the endpoint it was saved for.",
      },
      { status: 400 },
    );
  }
  const settings = override
    ? {
        provider,
        model: override.model ?? current.model,
        baseUrl,
        apiKey: override.apiKey ?? (sameTarget ? current.apiKey : undefined),
      }
    : current;

  if (!settings.model) {
    return NextResponse.json(
      { ok: false, error: "No model configured." },
      { status: 400 },
    );
  }
  const result = await testLLMConnection(settings);
  return NextResponse.json(result);
}
