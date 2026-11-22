"use client";

import { useState } from "react";
import type {
  BulletStyle,
  CustomSection,
  Education,
  Experience,
  PersonalInfo,
  Project,
  ResumeData,
} from "@/lib/schema";
import {
  ChevronDown,
  ChevronUp,
  Plus,
  Trash2,
  X,
} from "lucide-react";

const inputCls =
  "w-full rounded-md border border-[var(--border)] bg-[var(--surface-2)] px-2.5 py-1.5 text-sm outline-none transition-colors focus:border-[var(--accent)] placeholder:text-[var(--muted)]";
const btnIconCls =
  "rounded p-1 text-[var(--muted)] transition-colors hover:bg-[var(--surface-2)] hover:text-[var(--foreground)] disabled:opacity-30 disabled:hover:bg-transparent";

export function Field({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--muted)]">
        {label}
      </span>
      <input
        className={inputCls}
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function TextAreaField({
  label,
  value,
  onChange,
  rows = 3,
  placeholder,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  rows?: number;
  placeholder?: string;
}) {
  return (
    <label className="block">
      <span className="mb-1 block text-xs font-medium text-[var(--muted)]">
        {label}
      </span>
      <textarea
        className={`${inputCls} resize-y`}
        rows={rows}
        value={value}
        placeholder={placeholder}
        onChange={(e) => onChange(e.target.value)}
      />
    </label>
  );
}

export function SectionCard({
  title,
  children,
  actions,
}: {
  title: string;
  children: React.ReactNode;
  actions?: React.ReactNode;
}) {
  return (
    <section className="rounded-lg border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-sm font-semibold tracking-wide text-[var(--foreground)]">
          {title}
        </h2>
        {actions}
      </div>
      <div className="space-y-3">{children}</div>
    </section>
  );
}

function EntryCard({
  label,
  onMoveUp,
  onMoveDown,
  onRemove,
  canMoveUp,
  canMoveDown,
  children,
}: {
  label: string;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onRemove: () => void;
  canMoveUp: boolean;
  canMoveDown: boolean;
  children: React.ReactNode;
}) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-3">
      <div className="mb-2 flex items-center justify-between">
        <span className="text-xs font-medium text-[var(--muted)]">{label}</span>
        <div className="flex gap-0.5">
          <button className={btnIconCls} onClick={onMoveUp} disabled={!canMoveUp} title="Move up" type="button">
            <ChevronUp size={14} />
          </button>
          <button className={btnIconCls} onClick={onMoveDown} disabled={!canMoveDown} title="Move down" type="button">
            <ChevronDown size={14} />
          </button>
          <button className={btnIconCls} onClick={onRemove} title="Remove" type="button">
            <Trash2 size={14} />
          </button>
        </div>
      </div>
      <div className="space-y-2.5">{children}</div>
    </div>
  );
}

export function AddButton({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-center justify-center gap-1.5 rounded-md border border-dashed border-[var(--border-strong)] px-3 py-2 text-xs font-medium text-[var(--muted)] transition-colors hover:border-[var(--accent)] hover:text-[var(--accent)]"
    >
      <Plus size={14} />
      {label}
    </button>
  );
}

export function BulletListEditor({
  description,
  descriptionStyles,
  onChange,
}: {
  description: string[];
  descriptionStyles: BulletStyle[];
  onChange: (description: string[], descriptionStyles: BulletStyle[]) => void;
}) {
  const update = (i: number, value: string) => {
    onChange(
      description.map((d, j) => (j === i ? value : d)),
      descriptionStyles,
    );
  };
  const toggleStyle = (i: number) => {
    onChange(
      description,
      descriptionStyles.map((s, j) =>
        j === i ? (s === "bullet" ? "plain" : "bullet") : s,
      ),
    );
  };
  const remove = (i: number) => {
    onChange(
      description.filter((_, j) => j !== i),
      descriptionStyles.filter((_, j) => j !== i),
    );
  };
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= description.length) return;
    const d = [...description];
    const s = [...descriptionStyles];
    [d[i], d[j]] = [d[j], d[i]];
    [s[i], s[j]] = [s[j], s[i]];
    onChange(d, s);
  };
  const add = () => onChange([...description, ""], [...descriptionStyles, "bullet"]);

  return (
    <div className="space-y-1.5">
      {description.map((line, i) => (
        <div key={i} className="flex items-start gap-1.5">
          <button
            type="button"
            onClick={() => toggleStyle(i)}
            title={descriptionStyles[i] === "bullet" ? "Bullet (click for plain)" : "Plain (click for bullet)"}
            className={`mt-1.5 h-6 w-6 shrink-0 rounded text-[11px] font-bold transition-colors ${
              descriptionStyles[i] === "plain"
                ? "bg-[var(--surface)] text-[var(--muted)] border border-[var(--border-strong)]"
                : "bg-[var(--accent)]/15 text-[var(--accent-hover)] border border-transparent"
            }`}
          >
            {descriptionStyles[i] === "bullet" ? "•" : "¶"}
          </button>
          <textarea
            className={`${inputCls} min-h-[38px] resize-y py-1.5 text-[13px] leading-snug`}
            rows={line.length > 90 ? 2 : 1}
            value={line}
            placeholder="Accomplishment…"
            onChange={(e) => update(i, e.target.value)}
          />
          <div className="flex shrink-0 flex-col">
            <button className={btnIconCls} onClick={() => move(i, -1)} disabled={i === 0} title="Up" type="button">
              <ChevronUp size={12} />
            </button>
            <button
              className={btnIconCls}
              onClick={() => move(i, 1)}
              disabled={i === description.length - 1}
              title="Down"
              type="button"
            >
              <ChevronDown size={12} />
            </button>
            <button className={btnIconCls} onClick={() => remove(i)} title="Remove" type="button">
              <X size={12} />
            </button>
          </div>
        </div>
      ))}
      <button
        type="button"
        onClick={add}
        className="flex items-center gap-1 text-xs text-[var(--muted)] transition-colors hover:text-[var(--accent)]"
      >
        <Plus size={12} /> Add bullet
      </button>
    </div>
  );
}

export function StringListEditor({
  label,
  items,
  onChange,
  placeholder = "Type and press Enter…",
}: {
  label: string;
  items: string[];
  onChange: (items: string[]) => void;
  placeholder?: string;
}) {
  const [draft, setDraft] = useState("");
  const add = (raw: string) => {
    const value = raw.trim();
    if (!value) return;
    for (const part of value.split(/[,;]/)) {
      const v = part.trim();
      if (v && !items.some((i) => i.toLowerCase() === v.toLowerCase())) {
        items = [...items, v];
      }
    }
    onChange(items);
    setDraft("");
  };
  return (
    <div>
      <span className="mb-1 block text-xs font-medium text-[var(--muted)]">{label}</span>
      <div className="flex flex-wrap gap-1.5 rounded-md border border-[var(--border)] bg-[var(--surface-2)] p-2">
        {items.map((item, i) => (
          <span
            key={i}
            className="inline-flex items-center gap-1 rounded-full border border-[var(--border-strong)] bg-[var(--surface)] px-2 py-0.5 text-xs"
          >
            {item}
            <button
              type="button"
              onClick={() => onChange(items.filter((_, j) => j !== i))}
              className="text-[var(--muted)] transition-colors hover:text-red-400"
            >
              <X size={11} />
            </button>
          </span>
        ))}
        <input
          className="min-w-[140px] flex-1 bg-transparent px-1 py-0.5 text-xs outline-none placeholder:text-[var(--muted)]"
          value={draft}
          placeholder={items.length ? "" : placeholder}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === ",") {
              e.preventDefault();
              add(draft);
            }
          }}
          onBlur={() => add(draft)}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Section editors

export function PersonalInfoEditor({
  value,
  onChange,
}: {
  value: PersonalInfo;
  onChange: (value: PersonalInfo) => void;
}) {
  const set = (patch: Partial<PersonalInfo>) => onChange({ ...value, ...patch });
  return (
    <div className="grid grid-cols-2 gap-2.5">
      <Field label="Full name" value={value.name} onChange={(v) => set({ name: v })} />
      <Field label="Title" value={value.title} onChange={(v) => set({ title: v })} placeholder="Senior Backend Engineer" />
      <Field label="Email" value={value.email} onChange={(v) => set({ email: v })} type="email" />
      <Field label="Phone" value={value.phone} onChange={(v) => set({ phone: v })} />
      <Field label="Location" value={value.location} onChange={(v) => set({ location: v })} />
      <Field label="Website" value={value.website ?? ""} onChange={(v) => set({ website: v || null })} />
      <Field label="LinkedIn" value={value.linkedin ?? ""} onChange={(v) => set({ linkedin: v || null })} />
      <Field label="GitHub" value={value.github ?? ""} onChange={(v) => set({ github: v || null })} />
    </div>
  );
}

export function ExperienceEditor({
  value,
  onChange,
}: {
  value: Experience[];
  onChange: (value: Experience[]) => void;
}) {
  const set = (i: number, patch: Partial<Experience>) =>
    onChange(value.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= value.length) return;
    const copy = [...value];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    onChange(copy);
  };
  return (
    <div className="space-y-3">
      {value.map((entry, i) => (
        <EntryCard
          key={i}
          label={entry.title || entry.company || `Experience ${i + 1}`}
          canMoveUp={i > 0}
          canMoveDown={i < value.length - 1}
          onMoveUp={() => move(i, -1)}
          onMoveDown={() => move(i, 1)}
          onRemove={() => onChange(value.filter((_, j) => j !== i))}
        >
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Role" value={entry.title} onChange={(v) => set(i, { title: v })} />
            <Field label="Company" value={entry.company} onChange={(v) => set(i, { company: v })} />
            <Field label="Dates" value={entry.years} onChange={(v) => set(i, { years: v })} placeholder="Jan 2020 - Present" />
            <Field label="Location" value={entry.location ?? ""} onChange={(v) => set(i, { location: v || null })} />
          </div>
          <BulletListEditor
            description={entry.description}
            descriptionStyles={entry.descriptionStyles}
            onChange={(d, s) => set(i, { description: d, descriptionStyles: s })}
          />
        </EntryCard>
      ))}
      <AddButton
        label="Add experience"
        onClick={() =>
          onChange([
            ...value,
            { title: "", company: "", location: null, years: "", description: [], descriptionStyles: [] },
          ])
        }
      />
    </div>
  );
}

export function EducationEditor({
  value,
  onChange,
}: {
  value: Education[];
  onChange: (value: Education[]) => void;
}) {
  const set = (i: number, patch: Partial<Education>) =>
    onChange(value.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= value.length) return;
    const copy = [...value];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    onChange(copy);
  };
  return (
    <div className="space-y-3">
      {value.map((entry, i) => (
        <EntryCard
          key={i}
          label={entry.institution || `Education ${i + 1}`}
          canMoveUp={i > 0}
          canMoveDown={i < value.length - 1}
          onMoveUp={() => move(i, -1)}
          onMoveDown={() => move(i, 1)}
          onRemove={() => onChange(value.filter((_, j) => j !== i))}
        >
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Institution" value={entry.institution} onChange={(v) => set(i, { institution: v })} />
            <Field label="Degree" value={entry.degree} onChange={(v) => set(i, { degree: v })} />
            <Field label="Years" value={entry.years} onChange={(v) => set(i, { years: v })} placeholder="2014 - 2018" />
          </div>
          <TextAreaField
            label="Details"
            rows={2}
            value={entry.description ?? ""}
            onChange={(v) => set(i, { description: v || null })}
          />
        </EntryCard>
      ))}
      <AddButton
        label="Add education"
        onClick={() => onChange([...value, { institution: "", degree: "", years: "", description: null }])}
      />
    </div>
  );
}

export function ProjectsEditor({
  value,
  onChange,
}: {
  value: Project[];
  onChange: (value: Project[]) => void;
}) {
  const set = (i: number, patch: Partial<Project>) =>
    onChange(value.map((e, j) => (j === i ? { ...e, ...patch } : e)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= value.length) return;
    const copy = [...value];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    onChange(copy);
  };
  return (
    <div className="space-y-3">
      {value.map((entry, i) => (
        <EntryCard
          key={i}
          label={entry.name || `Project ${i + 1}`}
          canMoveUp={i > 0}
          canMoveDown={i < value.length - 1}
          onMoveUp={() => move(i, -1)}
          onMoveDown={() => move(i, 1)}
          onRemove={() => onChange(value.filter((_, j) => j !== i))}
        >
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Name" value={entry.name} onChange={(v) => set(i, { name: v })} />
            <Field label="Role" value={entry.role} onChange={(v) => set(i, { role: v })} />
            <Field label="Years" value={entry.years} onChange={(v) => set(i, { years: v })} />
          </div>
          <BulletListEditor
            description={entry.description}
            descriptionStyles={entry.descriptionStyles}
            onChange={(d, s) => set(i, { description: d, descriptionStyles: s })}
          />
        </EntryCard>
      ))}
      <AddButton
        label="Add project"
        onClick={() => onChange([...value, { name: "", role: "", years: "", description: [], descriptionStyles: [] }])}
      />
    </div>
  );
}

export function CustomSectionsEditor({
  value,
  onChange,
}: {
  value: CustomSection[];
  onChange: (value: CustomSection[]) => void;
}) {
  const set = (i: number, patch: Partial<CustomSection>) =>
    onChange(value.map((s, j) => (j === i ? { ...s, ...patch } : s)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= value.length) return;
    const copy = [...value];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    onChange(copy);
  };
  return (
    <div className="space-y-3">
      {value.map((section, i) => (
        <EntryCard
          key={i}
          label={section.title || `Section ${i + 1}`}
          canMoveUp={i > 0}
          canMoveDown={i < value.length - 1}
          onMoveUp={() => move(i, -1)}
          onMoveDown={() => move(i, 1)}
          onRemove={() => onChange(value.filter((_, j) => j !== i))}
        >
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Title" value={section.title} onChange={(v) => set(i, { title: v, key: v ? slugify(v) : section.key })} />
            <label className="block">
              <span className="mb-1 block text-xs font-medium text-[var(--muted)]">Type</span>
              <select
                className={inputCls}
                value={section.sectionType}
                onChange={(e) => set(i, { sectionType: e.target.value as CustomSection["sectionType"] })}
              >
                <option value="itemList">Item list</option>
                <option value="text">Text</option>
                <option value="stringList">String list</option>
              </select>
            </label>
          </div>
          {section.sectionType === "text" && (
            <TextAreaField label="Text" rows={3} value={section.text} onChange={(v) => set(i, { text: v })} />
          )}
          {section.sectionType === "stringList" && (
            <StringListEditor label="Items" items={section.strings} onChange={(v) => set(i, { strings: v })} />
          )}
          {section.sectionType === "itemList" && (
            <CustomItemsEditor
              section={section}
              onChange={(items) => set(i, { items })}
            />
          )}
        </EntryCard>
      ))}
      <AddButton
        label="Add custom section"
        onClick={() =>
          onChange([
            ...value,
            {
              key: `section_${value.length + 1}`,
              title: "",
              sectionType: "itemList",
              text: "",
              items: [],
              strings: [],
            },
          ])
        }
      />
    </div>
  );
}

function CustomItemsEditor({
  section,
  onChange,
}: {
  section: CustomSection;
  onChange: (items: CustomSection["items"]) => void;
}) {
  const set = (i: number, patch: Partial<CustomSection["items"][number]>) =>
    onChange(section.items.map((item, j) => (j === i ? { ...item, ...patch } : item)));
  const move = (i: number, dir: -1 | 1) => {
    const j = i + dir;
    if (j < 0 || j >= section.items.length) return;
    const copy = [...section.items];
    [copy[i], copy[j]] = [copy[j], copy[i]];
    onChange(copy);
  };
  return (
    <div className="space-y-2.5">
      {section.items.map((item, i) => (
        <EntryCard
          key={i}
          label={item.title || `Item ${i + 1}`}
          canMoveUp={i > 0}
          canMoveDown={i < section.items.length - 1}
          onMoveUp={() => move(i, -1)}
          onMoveDown={() => move(i, 1)}
          onRemove={() => onChange(section.items.filter((_, j) => j !== i))}
        >
          <div className="grid grid-cols-2 gap-2.5">
            <Field label="Title" value={item.title} onChange={(v) => set(i, { title: v })} />
            <Field label="Subtitle" value={item.subtitle} onChange={(v) => set(i, { subtitle: v })} />
            <Field label="Years" value={item.years} onChange={(v) => set(i, { years: v })} />
          </div>
          <BulletListEditor
            description={item.description}
            descriptionStyles={item.descriptionStyles}
            onChange={(d, s) => set(i, { description: d, descriptionStyles: s })}
          />
        </EntryCard>
      ))}
      <AddButton
        label="Add item"
        onClick={() =>
          onChange([...section.items, { title: "", subtitle: "", years: "", description: [], descriptionStyles: [] }])
        }
      />
    </div>
  );
}

function slugify(text: string): string {
  return text
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .slice(0, 40);
}

export type { ResumeData };
