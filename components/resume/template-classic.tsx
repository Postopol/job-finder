import type { ResumeData } from "@/lib/schema";
import type { TemplateProps } from "./resume-document";

/**
 * Classic — single column, serif headings, traditional engineering resume.
 * All styling is inline/atomic so the exact same markup prints to PDF.
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
          <div
            key={i}
            style={{ display: "flex", gap: "6pt", margin: "1pt 0" }}
          >
            <span style={{ flexShrink: 0, lineHeight: 1.42 }}>•</span>
            <span style={{ flex: 1 }}>{line}</span>
          </div>
        );
      })}
    </div>
  );
}

function SectionHeading({ children }: { children: React.ReactNode }) {
  return (
    <h2
      style={{
        fontSize: "0.95em",
        letterSpacing: "0.12em",
        textTransform: "uppercase",
        fontWeight: 700,
        margin: "0 0 5pt 0",
        paddingBottom: "2pt",
        borderBottom: "1pt solid #3f3f46",
      }}
    >
      {children}
    </h2>
  );
}

function EntryHeader({
  left,
  right,
  sub,
}: {
  left: React.ReactNode;
  right?: string;
  sub?: string | null;
}) {
  return (
    <div style={{ breakInside: "avoid" }}>
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: "12pt",
          alignItems: "baseline",
        }}
      >
        <span style={{ fontWeight: 700 }}>{left}</span>
        {right ? (
          <span style={{ fontSize: "0.92em", color: "#3f3f46", whiteSpace: "nowrap" }}>
            {right}
          </span>
        ) : null}
      </div>
      {sub ? (
        <div style={{ fontSize: "0.95em", color: "#52525b" }}>{sub}</div>
      ) : null}
    </div>
  );
}

export function ClassicTemplate({
  data,
  visible,
}: TemplateProps & {
  visible: (key: string) => boolean;
}) {
  const p = data.personalInfo;
  const contacts = [p.email, p.phone, p.location, p.website, p.linkedin, p.github]
    .filter((c): c is string => Boolean(c && c.trim()));

  return (
    <div style={{ fontFamily: "Georgia, 'Times New Roman', serif" }}>
      {/* Header */}
      <header style={{ textAlign: "center", marginBottom: "10pt" }}>
        <h1
          style={{
            fontSize: "2em",
            fontWeight: 700,
            letterSpacing: "0.02em",
            margin: 0,
          }}
        >
          {p.name || "Your Name"}
        </h1>
        {p.title ? (
          <div
            style={{
              fontSize: "1.05em",
              marginTop: "2pt",
              textTransform: "uppercase",
              letterSpacing: "0.18em",
              color: "#3f3f46",
            }}
          >
            {p.title}
          </div>
        ) : null}
        {contacts.length ? (
          <div style={{ marginTop: "4pt", fontSize: "0.9em", color: "#3f3f46" }}>
            {contacts.join("  ·  ")}
          </div>
        ) : null}
      </header>

      {visible("summary") && data.summary ? (
        <section style={{ marginBottom: "8pt" }}>
          <SectionHeading>Summary</SectionHeading>
          <p style={{ margin: 0, textAlign: "justify" }}>{data.summary}</p>
        </section>
      ) : null}

      {visible("workExperience") && data.workExperience.length ? (
        <section style={{ marginBottom: "8pt" }}>
          <SectionHeading>Experience</SectionHeading>
          {data.workExperience.map((job, i) => (
            <div
              key={i}
              style={{ marginBottom: i === data.workExperience.length - 1 ? 0 : "7pt", breakInside: "avoid" }}
            >
              <EntryHeader
                left={job.title || "Role"}
                right={job.years}
                sub={[job.company, job.location].filter(Boolean).join(" — ")}
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
        <section style={{ marginBottom: "8pt" }}>
          <SectionHeading>Projects</SectionHeading>
          {data.personalProjects.map((project, i) => (
            <div
              key={i}
              style={{ marginBottom: i === data.personalProjects.length - 1 ? 0 : "7pt", breakInside: "avoid" }}
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
        <section style={{ marginBottom: "8pt" }}>
          <SectionHeading>Education</SectionHeading>
          {data.education.map((edu, i) => (
            <div key={i} style={{ marginBottom: i === data.education.length - 1 ? 0 : "6pt" }}>
              <EntryHeader
                left={edu.degree || "Degree"}
                right={edu.years}
                sub={edu.institution}
              />
              {edu.description ? (
                <p style={{ margin: "1pt 0 0", color: "#3f3f46" }}>{edu.description}</p>
              ) : null}
            </div>
          ))}
        </section>
      ) : null}

      {visible("skills") && data.skills.length ? (
        <section style={{ marginBottom: "8pt" }}>
          <SectionHeading>Skills</SectionHeading>
          <div>{data.skills.join("  ·  ")}</div>
        </section>
      ) : null}

      {visible("certifications") && data.certifications.length ? (
        <section style={{ marginBottom: "8pt" }}>
          <SectionHeading>Certifications</SectionHeading>
          <div>{data.certifications.join("  ·  ")}</div>
        </section>
      ) : null}

      {visible("languages") && data.languages.length ? (
        <section style={{ marginBottom: "8pt" }}>
          <SectionHeading>Languages</SectionHeading>
          <div>{data.languages.join("  ·  ")}</div>
        </section>
      ) : null}

      {visible("awards") && data.awards.length ? (
        <section style={{ marginBottom: "8pt" }}>
          <SectionHeading>Awards</SectionHeading>
          <div>{data.awards.join("  ·  ")}</div>
        </section>
      ) : null}

      {data.customSections
        .filter((s) => visible(`custom:${s.key}`) && s.title)
        .map((section) => (
          <section key={section.key} style={{ marginBottom: "8pt" }}>
            <SectionHeading>{section.title}</SectionHeading>
            {section.sectionType === "text" ? (
              <p style={{ margin: 0 }}>{section.text}</p>
            ) : section.sectionType === "stringList" ? (
              <div>{section.strings.join("  ·  ")}</div>
            ) : (
              section.items.map((item, i) => (
                <div key={i} style={{ marginBottom: "6pt", breakInside: "avoid" }}>
                  <EntryHeader
                    left={item.title}
                    right={item.years}
                    sub={item.subtitle}
                  />
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
