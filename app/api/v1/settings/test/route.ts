import { NextRequest, NextResponse } from "next/server";
import { z } from "zod";
import { testLLMConnection } from "@/lib/llm";
import { getLLMSettings } from "@/lib/settings";

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
  const settings = override
    ? {
        provider: (override.provider as typeof current.provider) ?? current.provider,
        model: override.model ?? current.model,
        baseUrl: override.baseUrl ?? current.baseUrl,
        apiKey: override.apiKey ?? current.apiKey,
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
