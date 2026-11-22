import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import {
  PROVIDERS,
  SettingsError,
  clearLLMApiKey,
  getRedactedLLMSettings,
  saveLLMSettings,
} from "@/lib/settings";

export async function GET() {
  return NextResponse.json({ data: getRedactedLLMSettings() });
}

const putSchema = z.object({
  provider: z.enum(PROVIDERS),
  model: z.string().trim().min(1, "Model is required"),
  baseUrl: z.string().trim().optional(),
  apiKey: z.string().optional(),
  clearApiKey: z.boolean().optional(),
});

export async function PUT(request: NextRequest) {
  let body: unknown;
  try {
    body = await request.json();
  } catch {
    return NextResponse.json({ error: "Invalid JSON body" }, { status: 400 });
  }
  const parsed = putSchema.safeParse(body);
  if (!parsed.success) {
    return NextResponse.json(
      { error: parsed.error.issues[0]?.message ?? "Invalid settings" },
      { status: 400 },
    );
  }
  const { provider, model, baseUrl, apiKey, clearApiKey } = parsed.data;
  if (clearApiKey) clearLLMApiKey();
  let keyDropped = false;
  try {
    ({ keyDropped } = saveLLMSettings({
      provider,
      model,
      baseUrl: baseUrl || undefined,
      apiKey: apiKey || undefined,
    }));
  } catch (e) {
    if (e instanceof SettingsError) {
      return NextResponse.json({ error: e.message }, { status: 400 });
    }
    throw e;
  }
  return NextResponse.json({ data: getRedactedLLMSettings(), keyDropped });
}
