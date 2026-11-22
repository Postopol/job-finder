import type { ResumeData } from "@/lib/schema";
import type { TemplateProps } from "./resume-document";

/**
 * Modern — sans-serif, accent-colored headings, chip-style skill lists.
 */

function Bullets({
  description,
  descriptionStyles,
}: {
  description: string[];
  descriptionStyles: ResumeData["workExperience"][number]["descriptionStyles"];
}) {
  if (!description.length) return null;
  return (
    <div style={{ marginTop: "1.5pt" }}>
      {description.map((line, i) => {
        const style = descriptionStyles[i] ?? "bullet";
        if (!line.trim()) return null;
        return style === "plain" ? (
          <p key={i} style={{ margin: "1pt 0" }}>
            {line}
          </p>
        ) : (
          <div key={i} style={{ display: "flex", gap: "6pt", margin: "1pt 0" }}>
            <span style={{ flexShrink: 0, color: "var(--tpl-accent)" }}>–</span>
            <span style={{ flex: 1 }}>{line}</span>
          </div>
        );
      })}
    </div>
  );
}

export function ModernTemplate({
  data,
  settings,
  visible,
}: TemplateProps & { visible: (key: string) => boolean }) {
  const accent = settings.accent;
  const p = data.personalInfo;
  const contacts = [p.email, p.phone, p.location, p.website, p.linkedin, p.github]
    .filter((c): c is string => Boolean(c && c.trim()));

  const SectionHeading = ({ children }: { children: React.ReactNode }) => (
    <h2
      style={{
        fontSize: "0.85em",
        letterSpacing: "0.16em",
        textTransform: "uppercase",
        fontWeight: 700,
        color: accent,
        margin: "0 0 5pt 0",
      }}
    >
      {children}
      <span
        style={{
          display: "block",
          height: "1.5pt",
          background: `linear-gradient(to right, ${accent} 0 24pt, #e4e4e7 24pt)`,
          marginTop: "2pt",
          borderRadius: "1pt",
        }}
      />
    </h2>
  );

  const EntryHeader = ({
    left,
    right,
    sub,
  }: {
    left: React.ReactNode;
    right?: string;
    sub?: string | null;
  }) => (
    <div style={{ breakInside: "avoid" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: "12pt",
          alignItems: "baseline",
        }}
      >
        <span style={{ fontWeight: 650 }}>{left}</span>
        {right ? (
          <span
            style={{
              fontSize: "0.88em",
              color: "#71717a",
              whiteSpace: "nowrap",
              background: "#f4f4f5",
              padding: "0.5pt 5pt",
              borderRadius: "3pt",
            }}
          >
            {right}
          </span>
        ) : null}
      </div>
      {sub ? (
        <div style={{ fontSize: "0.95em", color: "#52525b", fontWeight: 500 }}>
          {sub}
        </div>
      ) : null}
    </div>
  );

  const Chips = ({ items }: { items: string[] }) => (
    <div style={{ display: "flex", flexWrap: "wrap", gap: "4pt" }}>
      {items.map((item, i) => (
        <span
          key={i}
          style={{
            border: `0.75pt solid ${accent}55`,
            color: "#27272a",
            background: "#fafafa",
            padding: "1pt 6pt",
            borderRadius: "999pt",
            fontSize: "0.88em",
          }}
        >
          {item}
        </span>
      ))}
    </div>
  );

  return (
    <div
      style={{
        fontFamily:
          "ui-sans-serif, system-ui, -apple-system, 'Segoe UI', Roboto, Arial, sans-serif",
        ["--tpl-accent" as string]: accent,
      }}
    >
      {/* Header */}
      <header
        style={{
          marginBottom: "12pt",
          paddingBottom: "8pt",
          borderBottom: `2pt solid ${accent}`,
        }}
      >
        <h1 style={{ fontSize: "2.1em", fontWeight: 800, margin: 0, letterSpacing: "-0.01em" }}>
          {p.name || "Your Name"}
        </h1>
        {p.title ? (
          <div style={{ color: accent, fontWeight: 600, marginTop: "1pt", fontSize: "1.05em" }}>
            {p.title}
          </div>
        ) : null}
        {contacts.length ? (
          <div style={{ marginTop: "4pt", fontSize: "0.88em", color: "#52525b" }}>
            {contacts.join("   |   ")}
          </div>
        ) : null}
      </header>

      {visible("summary") && data.summary ? (
        <section style={{ marginBottom: "9pt" }}>
          <SectionHeading>Summary</SectionHeading>
          <p style={{ margin: 0 }}>{data.summary}</p>
        </section>
      ) : null}

      {visible("workExperience") && data.workExperience.length ? (
        <section style={{ marginBottom: "9pt" }}>
          <SectionHeading>Experience</SectionHeading>
          {data.workExperience.map((job, i) => (
            <div
              key={i}
              style={{
                marginBottom: i === data.workExperience.length - 1 ? 0 : "7pt",
                breakInside: "avoid",
              }}
            >
              <EntryHeader
                left={job.title || "Role"}
                right={job.years}
                sub={[job.company, job.location].filter(Boolean).join(" · ")}
              />
              <Bullets
                description={job.description}
                descriptionStyles={job.descriptionStyles}
              />
            </div>
          ))}
        </section>
      ) : null}

      {visible("personalProjects") && data.personalProjects.length ? (
        <section style={{ marginBottom: "9pt" }}>
          <SectionHeading>Projects</SectionHeading>
          {data.personalProjects.map((project, i) => (
            <div
              key={i}
              style={{
                marginBottom: i === data.personalProjects.length - 1 ? 0 : "7pt",
                breakInside: "avoid",
              }}
            >
              <EntryHeader
                left={project.name || "Project"}
                right={project.years}
                sub={project.role}
              />
              <Bullets
                description={project.description}
                descriptionStyles={project.descriptionStyles}
              />
            </div>
          ))}
        </section>
      ) : null}

      {visible("education") && data.education.length ? (
        <section style={{ marginBottom: "9pt" }}>
          <SectionHeading>Education</SectionHeading>
          {data.education.map((edu, i) => (
            <div key={i} style={{ marginBottom: i === data.education.length - 1 ? 0 : "5pt" }}>
              <EntryHeader left={edu.degree || "Degree"} right={edu.years} sub={edu.institution} />
              {edu.description ? (
                <p style={{ margin: "1pt 0 0", color: "#52525b" }}>{edu.description}</p>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}

      {visible("skills") && data.skills.length ? (
        <section style={{ marginBottom: "9pt" }}>
          <SectionHeading>Skills</SectionHeading>
          <Chips items={data.skills} />
        </section>
      ) : null}

      {visible("certifications") && data.certifications.length ? (
        <section style={{ marginBottom: "9pt" }}>
          <SectionHeading>Certifications</SectionHeading>
          <Chips items={data.certifications} />
        </section>
      ) : null}

      {visible("languages") && data.languages.length ? (
        <section style={{ marginBottom: "9pt" }}>
          <SectionHeading>Languages</SectionHeading>
          <Chips items={data.languages} />
        </section>
      ) : null}

      {visible("awards") && data.awards.length ? (
        <section style={{ marginBottom: "9pt" }}>
          <SectionHeading>Awards</SectionHeading>
          <Chips items={data.awards} />
        </section>
      ) : null}

      {data.customSections
        .filter((s) => visible(`custom:${s.key}`) && s.title)
        .map((section) => (
          <section key={section.key} style={{ marginBottom: "9pt" }}>
            <SectionHeading>{section.title}</SectionHeading>
            {section.sectionType === "text" ? (
              <p style={{ margin: 0 }}>{section.text}</p>
            ) : section.sectionType === "stringList" ? (
              <Chips items={section.strings} />
            ) : (
              section.items.map((item, i) => (
                <div key={i} style={{ marginBottom: "5pt", breakInside: "avoid" }}>
                  <EntryHeader left={item.title} right={item.years} sub={item.subtitle} />
                  <Bullets
                    description={item.description}
                    descriptionStyles={item.descriptionStyles}
                  />
                </div>
              ))
            )}
          </section>
        ))}
    </div>
  );
}
