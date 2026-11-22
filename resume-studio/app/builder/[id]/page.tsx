import { notFound } from "next/navigation";
import { getResume } from "@/lib/db";
import { DEFAULT_TEMPLATE_SETTINGS } from "@/lib/schema";
import { ResumeBuilder } from "@/components/builder/resume-builder";
import { BuilderNotReady } from "@/components/builder/builder-not-ready";

export const dynamic = "force-dynamic";

export default async function BuilderPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  const { id } = await params;
  const resume = getResume(id);
  if (!resume) notFound();

  if (!resume.processed_data) {
    return (
      <BuilderNotReady
        status={resume.processing_status}
        error={resume.processing_error}
        resumeId={resume.resume_id}
      />
    );
  }

  return (
    <ResumeBuilder
      resumeId={resume.resume_id}
      initialData={resume.processed_data}
      initialSettings={resume.template_settings ?? DEFAULT_TEMPLATE_SETTINGS}
      initialTitle={resume.title ?? resume.filename ?? ""}
      processingStatus={resume.processing_status}
      processingError={resume.processing_error}
    />
  );
}
