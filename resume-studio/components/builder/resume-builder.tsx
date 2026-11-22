"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  ArrowLeft,
  Download,
  Loader2,
  Minus,
  Plus,
  RotateCcw,
} from "lucide-react";
import type { ResumeData, TemplateSettings } from "@/lib/schema";
import { paperSizePx, templateSettingsSchema } from "@/lib/schema";
import { ResumeDocument } from "@/components/resume/resume-document";
import {
  CustomSectionsEditor,
  EducationEditor,
  ExperienceEditor,
  PersonalInfoEditor,
  ProjectsEditor,
  SectionCard,
  StringListEditor,
  TextAreaField,
} from "./editors";

type SaveState = "saved" | "saving" | "dirty" | "error";

const ACCENT_SWATCHES = ["#1d4ed8", "#0f766e", "#9333ea", "#b91c1c", "#525252"];

export function ResumeBuilder({
  resumeId,
  initialData,
  initialSettings,
  initialTitle,
  processingStatus,
  processingError,
}: {
  resumeId: string;
  initialData: ResumeData;
  initialSettings: TemplateSettings;
  initialTitle: string;
  processingStatus: string;
  processingError: string | null;
}) {
  const [data, setData] = useState<ResumeData>(initialData);
  const [settings, setSettings] = useState<TemplateSettings>(initialSettings);
  const [title, setTitle] = useState(initialTitle);
  const [saveState, setSaveState] = useState<SaveState>("saved");
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [pdfBusy, setPdfBusy] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [zoomMultiplier, setZoomMultiplier] = useState(1);

  const latest = useRef({ data, settings, title });
  latest.current = { data, settings, title };
  const skipFirstSave = useRef(true);

  useEffect(() => {
    if (skipFirstSave.current) {
      skipFirstSave.current = false;
      return;
    }
    setSaveState("dirty");
    const timer = setTimeout(async () => {
      setSaveState("saving");
      try {
        const response = await fetch(`/api/v1/resumes/${resumeId}`, {
          method: "PATCH",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            processed_data: latest.current.data,
            template_settings: latest.current.settings,
            title: latest.current.title || null,
          }),
        });
        if (!response.ok) throw new Error(await response.text());
        setSaveState("saved");
        setSavedAt(new Date().toLocaleTimeString());
      } catch {
        setSaveState("error");
      }
    }, 800);
    return () => clearTimeout(timer);
  }, [data, settings, title, resumeId]);

  const setSetting = useCallback(
    (patch: Partial<TemplateSettings>) =>
      setSettings((s) => templateSettingsSchema.parse({ ...s, ...patch })),
    [],
  );

  const downloadPdf = async () => {
    setPdfBusy(true);
    setPdfError(null);
    try {
      const response = await fetch(`/api/v1/resumes/${resumeId}/pdf`);
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.error ?? `PDF failed (HTTP ${response.status})`);
      }
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `${(title || "resume").replace(/[^\w\s-]/g, "").trim().replace(/\s+/g, "-").toLowerCase() || "resume"}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (error) {
      setPdfError(error instanceof Error ? error.message : "PDF export failed");
    } finally {
      setPdfBusy(false);
    }
  };

  return (
    <div className="flex h-screen flex-col">
      <header className="flex h-14 shrink-0 items-center gap-3 border-b border-[var(--border)] bg-[var(--surface)] px-4">
        <Link
          href="/"
          className="rounded p-1.5 text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--foreground)]"
          title="Back"
        >
          <ArrowLeft size={18} />
        </Link>
        <input
          className="w-64 rounded-md border border-transparent bg-transparent px-2 py-1 text-sm font-medium outline-none transition-colors hover:border-[var(--border)] focus:border-[var(--border)]"
          value={title}
          placeholder="Untitled resume"
          onChange={(e) => setTitle(e.target.value)}
        />
        <SaveBadge state={saveState} savedAt={savedAt} />
        <div className="flex-1" />
        {processingStatus === "error" && processingError ? (
          <span className="flex items-center gap-1.5 rounded-md border border-amber-500/30 bg-amber-500/10 px-2.5 py-1 text-xs text-amber-300" title={processingError}>
            <AlertTriangle size={13} />
            Last processing failed
          </span>
        ) : null}
        <button
          onClick={downloadPdf}
          disabled={pdfBusy}
          className="flex items-center gap-2 rounded-md bg-[var(--accent)] px-3.5 py-1.5 text-sm font-medium text-white transition-colors hover:bg-[var(--accent-hover)] disabled:opacity-60"
        >
          {pdfBusy ? <Loader2 size={15} className="animate-spin" /> : <Download size={15} />}
          Download PDF
        </button>
      </header>

      {pdfError ? (
        <div className="border-b border-red-500/30 bg-red-500/10 px-4 py-2 text-sm text-red-300">
          {pdfError}
        </div>
      ) : null}

      <div className="flex min-h-0 flex-1">
        <div className="pane-scroll w-[46%] min-w-[420px] space-y-4 overflow-y-auto border-r border-[var(--border)] p-4">
          <SectionCard title="Personal info">
            <PersonalInfoEditor
              value={data.personalInfo}
              onChange={(v) => setData((d) => ({ ...d, personalInfo: v }))}
            />
          </SectionCard>

          <SectionCard title="Summary">
            <TextAreaField
              label=""
              rows={4}
              value={data.summary}
              placeholder="Two or three sentences positioning you for the role…"
              onChange={(v) => setData((d) => ({ ...d, summary: v }))}
            />
          </SectionCard>

          <SectionCard title="Experience">
            <ExperienceEditor
              value={data.workExperience}
              onChange={(v) => setData((d) => ({ ...d, workExperience: v }))}
            />
          </SectionCard>

          <SectionCard title="Projects">
            <ProjectsEditor
              value={data.personalProjects}
              onChange={(v) => setData((d) => ({ ...d, personalProjects: v }))}
            />
          </SectionCard>

          <SectionCard title="Education">
            <EducationEditor
              value={data.education}
              onChange={(v) => setData((d) => ({ ...d, education: v }))}
            />
          </SectionCard>

          <SectionCard title="Skills">
            <StringListEditor
              label=""
              items={data.skills}
              onChange={(v) => setData((d) => ({ ...d, skills: v }))}
              placeholder="Go, Kubernetes, PostgreSQL…"
            />
          </SectionCard>

          <SectionCard title="Certifications">
            <StringListEditor
              label=""
              items={data.certifications}
              onChange={(v) => setData((d) => ({ ...d, certifications: v }))}
            />
          </SectionCard>

          <SectionCard title="Languages">
            <StringListEditor
              label=""
              items={data.languages}
              onChange={(v) => setData((d) => ({ ...d, languages: v }))}
              placeholder="English (fluent), Russian (native)…"
            />
          </SectionCard>

          <SectionCard title="Awards">
            <StringListEditor
              label=""
              items={data.awards}
              onChange={(v) => setData((d) => ({ ...d, awards: v }))}
            />
          </SectionCard>

          <SectionCard title="Custom sections">
            <CustomSectionsEditor
              value={data.customSections}
              onChange={(v) => setData((d) => ({ ...d, customSections: v }))}
            />
          </SectionCard>

          <div className="pb-8 text-center text-xs text-[var(--muted)]">
            Everything is saved to your local database.
          </div>
        </div>

        <PreviewPane
          data={data}
          settings={settings}
          setSetting={setSetting}
          zoomMultiplier={zoomMultiplier}
          setZoomMultiplier={setZoomMultiplier}
        />
      </div>
    </div>
  );
}

function SaveBadge({ state, savedAt }: { state: SaveState; savedAt: string | null }) {
  const map: Record<SaveState, { text: string; cls: string }> = {
    saved: { text: savedAt ? `Saved ${savedAt}` : "Saved", cls: "text-emerald-400" },
    saving: { text: "Saving…", cls: "text-[var(--muted)]" },
    dirty: { text: "Unsaved changes", cls: "text-amber-400" },
    error: { text: "Save failed", cls: "text-red-400" },
  };
  const { text, cls } = map[state];
  return <span className={`text-xs ${cls}`}>{text}</span>;
}

function PreviewPane({
  data,
  settings,
  setSetting,
  zoomMultiplier,
  setZoomMultiplier,
}: {
  data: ResumeData;
  settings: TemplateSettings;
  setSetting: (patch: Partial<TemplateSettings>) => void;
  zoomMultiplier: number;
  setZoomMultiplier: (v: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const docRef = useRef<HTMLDivElement>(null);
  const [docHeight, setDocHeight] = useState(1123);
  const [fitZoom, setFitZoom] = useState(0.6);

  const paperWidth = paperSizePx(settings.paper).width;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const update = () => {
      const available = container.clientWidth - 48;
      setFitZoom(Math.min(1, Math.max(0.25, available / paperWidth)));
    };
    update();
    const ro = new ResizeObserver(update);
    ro.observe(container);
    return () => ro.disconnect();
  }, [paperWidth]);

  useEffect(() => {
    const doc = docRef.current;
    if (!doc) return;
    const update = () => setDocHeight(doc.offsetHeight);
    update();
    const ro = new ResizeObserver(update);
    ro.observe(doc);
    return () => ro.disconnect();
  }, []);

  const zoom = fitZoom * zoomMultiplier;

  const segmented = (
    label: string,
    options: { value: string; label: string }[],
    value: string,
    onChange: (v: string) => void,
  ) => (
    <div className="flex items-center gap-2">
      <span className="text-xs text-[var(--muted)]">{label}</span>
      <div className="flex rounded-md border border-[var(--border)] p-0.5">
        {options.map((opt) => (
          <button
            key={opt.value}
            type="button"
            onClick={() => onChange(opt.value)}
            className={`rounded px-2 py-0.5 text-xs transition-colors ${
              value === opt.value
                ? "bg-[var(--accent)] text-white"
                : "text-[var(--muted)] hover:text-[var(--foreground)]"
            }`}
          >
            {opt.label}
          </button>
        ))}
      </div>
    </div>
  );

  return (
    <div className="flex min-w-0 flex-1 flex-col bg-[#0c0c0f]">
      <div className="flex h-14 shrink-0 flex-wrap items-center gap-x-5 gap-y-2 border-b border-[var(--border)] px-4">
        {segmented(
          "Template",
          [
            { value: "classic", label: "Classic" },
            { value: "modern", label: "Modern" },
          ],
          settings.template,
          (v) => setSetting({ template: v as TemplateSettings["template"] }),
        )}
        {segmented(
          "Paper",
          [
            { value: "a4", label: "A4" },
            { value: "letter", label: "Letter" },
          ],
          settings.paper,
          (v) => setSetting({ paper: v as TemplateSettings["paper"] }),
        )}
        {segmented(
          "Margins",
          [
            { value: "narrow", label: "S" },
            { value: "normal", label: "M" },
            { value: "wide", label: "L" },
          ],
          settings.margins,
          (v) => setSetting({ margins: v as TemplateSettings["margins"] }),
        )}
        <div className="flex items-center gap-2">
          <span className="text-xs text-[var(--muted)]">Zoom</span>
          <button
            type="button"
            className="rounded border border-[var(--border)] p-1 text-[var(--muted)] hover:text-[var(--foreground)]"
            onClick={() => setZoomMultiplier(Math.max(0.5, zoomMultiplier - 0.1))}
          >
            <Minus size={12} />
          </button>
          <span className="w-10 text-center text-xs text-[var(--muted)]">
            {Math.round(zoom * 100)}%
          </span>
          <button
            type="button"
            className="rounded border border-[var(--border)] p-1 text-[var(--muted)] hover:text-[var(--foreground)]"
            onClick={() => setZoomMultiplier(Math.min(2, zoomMultiplier + 0.1))}
          >
            <Plus size={12} />
          </button>
          <button
            type="button"
            className="rounded border border-[var(--border)] p-1 text-[var(--muted)] hover:text-[var(--foreground)]"
            onClick={() => setZoomMultiplier(1)}
            title="Reset zoom"
          >
            <RotateCcw size={12} />
          </button>
        </div>
        {settings.template === "modern" ? (
          <div className="flex items-center gap-1.5">
            {ACCENT_SWATCHES.map((color) => (
              <button
                key={color}
                type="button"
                onClick={() => setSetting({ accent: color })}
                className={`h-4 w-4 rounded-full border-2 transition-transform hover:scale-110 ${
                  settings.accent === color ? "border-white" : "border-transparent"
                }`}
                style={{ background: color }}
                title={color}
              />
            ))}
          </div>
        ) : null}
      </div>

      <div ref={containerRef} className="pane-scroll flex-1 overflow-auto p-6">
        <div
          style={{
            width: paperWidth * zoom,
            height: docHeight * zoom,
            margin: "0 auto",
            position: "relative",
          }}
        >
          <div
            ref={docRef}
            style={{
              transform: `scale(${zoom})`,
              transformOrigin: "top left",
              position: "absolute",
              top: 0,
              left: 0,
              boxShadow: "0 4px 24px rgba(0,0,0,0.5)",
            }}
          >
            <ResumeDocument data={data} settings={settings} />
          </div>
        </div>
      </div>
    </div>
  );
}
