import type { ResumeData, TemplateSettings } from "@/lib/schema";
import { marginPx, sectionVisible } from "@/lib/schema";
import { ClassicTemplate } from "./template-classic";
import { ModernTemplate } from "./template-modern";

/**
 * The single template entry point, shared by the builder's live preview and
 * the /print route that Chromium turns into a PDF — one codebase, one
 * geometry, pixel-identical output.
 */

export interface TemplateProps {
  data: ResumeData;
  settings: TemplateSettings;
}

export function ResumeDocument({ data, settings }: TemplateProps) {
  const isLetter = settings.paper === "letter";
  const width = isLetter ? "8.5in" : "210mm";
  const minHeight = isLetter ? "11in" : "297mm";
  const padding = marginPx(settings.margins);

  const props: TemplateProps = { data, settings };
  const visible = (key: string) => sectionVisible(data, key);

  return (
    <div
      style={{
        width,
        minHeight,
        padding: `${padding}px`,
        boxSizing: "border-box",
        background: "#ffffff",
        color: "#18181b",
        fontSize: `${(10.5 * settings.fontScale).toFixed(2)}pt`,
        lineHeight: 1.42,
      }}
    >
      {settings.template === "modern" ? (
        <ModernTemplate {...props} visible={visible} />
      ) : (
        <ClassicTemplate {...props} visible={visible} />
      )}
    </div>
  );
}
