import { NextResponse } from "next/server";
import { isLLMConfigured, getLLMSettings } from "@/lib/settings";

export async function GET() {
  const settings = getLLMSettings();
  return NextResponse.json({
    status: "ok",
    llm: {
      configured: isLLMConfigured(),
      provider: settings.provider,
      model: settings.model,
    },
  });
}
