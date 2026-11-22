// A mock OpenAI-compatible server for end-to-end testing without a real
// API key: POST /v1/chat/completions answers with a fixed, valid parsed
// resume, extracted JD keywords, or {"ok":true} for connection tests.
import http from "node:http";

const PORT = Number(process.env.MOCK_LLM_PORT || 8787);

const SAMPLE_JOB_KEYWORDS = {
  company: "Tech Corp",
  role: "Senior Backend Engineer",
  required_skills: ["Go", "Kubernetes", "PostgreSQL", "Distributed systems"],
  preferred_skills: ["Kafka", "Terraform", "AWS"],
  experience_requirements: ["5+ years"],
  education_requirements: ["Bachelor's in CS"],
  key_responsibilities: ["Lead the platform team"],
  keywords: ["microservices", "observability", "CI/CD"],
  experience_years: 5,
  seniority_level: "senior",
};


const SAMPLE_RESUME = {
  personalInfo: {
    name: "John Doe",
    title: "Senior Backend Engineer",
    email: "john.doe@example.com",
    phone: "+1-555-0100",
    location: "San Francisco, CA",
    website: "https://johndoe.dev",
    linkedin: "linkedin.com/in/johndoe",
    github: "github.com/johndoe",
  },
  summary:
    "Backend engineer with 8 years of experience building distributed systems in Go and Python. Led migration of 30 services to Kubernetes and cut p99 latency 40% on a high-traffic billing API.",
  workExperience: [
    {
      title: "Senior Backend Engineer",
      company: "Tech Corp",
      location: "San Francisco, CA",
      years: "Jan 2020 - Present",
      description: [
        "Moved 30 services from VMs to Kubernetes; on-call lead for the platform",
        "Rewrote the billing API in Go; p99 latency down 40%",
        "Set up CI/CD for 12 services with GitHub Actions",
      ],
      descriptionStyles: ["bullet", "bullet", "bullet"],
    },
    {
      title: "Backend Engineer",
      company: "Startup LLC",
      location: "Remote",
      years: "Jun 2017 - Dec 2019",
      description: [
        "Built the event pipeline on Kafka processing 2M events/day",
        "Introduced Redis caching, cutting DB load by 60%",
      ],
      descriptionStyles: ["bullet", "bullet"],
    },
  ],
  education: [
    {
      institution: "University of California, Berkeley",
      degree: "B.S. Computer Science",
      years: "2013 - 2017",
      description: "Graduated with honors",
    },
  ],
  personalProjects: [
    {
      name: "Open Source Tool",
      role: "Creator & Maintainer",
      years: "Mar 2021 - Present",
      description: ["Built a CLI tool with 1000+ GitHub stars"],
      descriptionStyles: ["bullet"],
    },
  ],
  skills: ["Go", "Python", "Kubernetes", "Docker", "PostgreSQL", "Redis", "gRPC", "Kafka"],
  certifications: ["AWS Solutions Architect"],
  languages: ["English (Native)", "Spanish (Conversational)"],
  awards: [],
  customSections: [],
};

function completion(content) {
  return {
    id: "chatcmpl-mock",
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: "mock-resume-model",
    choices: [
      {
        index: 0,
        message: { role: "assistant", content },
        finish_reason: "stop",
      },
    ],
    usage: { prompt_tokens: 100, completion_tokens: 500, total_tokens: 600 },
  };
}

const server = http.createServer((req, res) => {
  const send = (status, body) => {
    res.writeHead(status, { "Content-Type": "application/json" });
    res.end(JSON.stringify(body));
  };

  if (req.method === "GET" && req.url === "/v1/models") {
    return send(200, {
      object: "list",
      data: [{ id: "mock-resume-model", object: "model" }],
    });
  }

  if (req.method === "POST" && req.url === "/v1/chat/completions") {
    let raw = "";
    req.on("data", (chunk) => (raw += chunk));
    req.on("end", () => {
      let body = {};
      try {
        body = JSON.parse(raw);
      } catch {}
      const prompt = JSON.stringify(body.messages ?? []);
      const isPing = /connection test|\{"ok"\s*:\s*true\}/i.test(prompt);
      const isKeywords = /job description analyzer/i.test(prompt);
      const payload = isPing
        ? '{"ok": true}'
        : isKeywords
          ? JSON.stringify(SAMPLE_JOB_KEYWORDS)
          : JSON.stringify(SAMPLE_RESUME);

      // Tool-mode requests get a tool call answer.
      if (Array.isArray(body.tools) && body.tools.length > 0) {
        return send(200, {
          id: "chatcmpl-mock",
          object: "chat.completion",
          created: Math.floor(Date.now() / 1000),
          model: body.model ?? "mock-resume-model",
          choices: [
            {
              index: 0,
              message: {
                role: "assistant",
                content: null,
                tool_calls: [
                  {
                    id: "call_mock",
                    type: "function",
                    function: {
                      name: body.tools[0].function?.name ?? "generate",
                      arguments: payload,
                    },
                  },
                ],
              },
              finish_reason: "tool_calls",
            },
          ],
          usage: { prompt_tokens: 100, completion_tokens: 500, total_tokens: 600 },
        });
      }

      return send(200, completion(payload));
    });
    return;
  }

  send(404, { error: { message: `No route: ${req.method} ${req.url}` } });
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`Mock LLM listening on http://127.0.0.1:${PORT}/v1`);
});
