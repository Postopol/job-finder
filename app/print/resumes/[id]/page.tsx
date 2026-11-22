import { getResume } from "@/lib/db";
import { DEFAULT_TEMPLATE_SETTINGS } from "@/lib/schema";
import { verifyPrintToken } from "@/lib/print-token";
import { ResumeDocument } from "@/components/resume/resume-document";

export const metadata = {
  title: "Resume print",
};

export const dynamic = "force-dynamic";

function PrintError({ message }: { message: string }) {
  return (
    <div
      data-print-error={message}
      style={{
        fontFamily: "system-ui, sans-serif",
        padding: 48,
        color: "#7f1d1d",
        background: "#fef2f2",
      }}
    >
      <h1 style={{ fontSize: 20, margin: 0 }}>Print failed</h1>
      <p style={{ margin: "8px 0 0" }}>{message}</p>
    </div>
  );
}

export default async function PrintResumePage({
  params,
  searchParams,
}: {
  params: Promise<{ id: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const { id } = await params;
  const sp = await searchParams;
  const token = typeof sp.token === "string" ? sp.token : "";

  if (!token || !verifyPrintToken(token, id)) {
    return <PrintError message="Invalid or expired print token." />;
  }

  const resume = getResume(id);
  if (!resume) {
    return <PrintError message="Resume not found." />;
  }
  if (!resume.processed_data) {
    return <PrintError message="Resume has no structured data yet." />;
  }

  const settings = resume.template_settings ?? DEFAULT_TEMPLATE_SETTINGS;
  const pageSize = settings.paper === "letter" ? "Letter" : "A4";

  return (
    <>
      <style>{`@page { size: ${pageSize}; margin: 0; } body { margin: 0; background: #fff; }`}</style>
      <ResumeDocument data={resume.processed_data} settings={settings} />
    </>
  );
}
