// Approved copy and behavior contracts for the Global Payroll AI Concierge,
// per docs/Zoiko_Payroll_AI_Chatbot_Engineering_Wireframe_v1.0.docx
// (ZP-PUB-AI-UX-001). The mock-up governs labels; the spec governs behavior.
// Anything that is "truth" (country readiness, counts, CTA destinations)
// comes from the server or deploy-time config — never from this file.

export const COPY = {
  title: "Global Payroll AI Concierge",
  subtitle: "Answers. Guidance. Global expertise.",
  welcomeTitle: "Welcome to Zoiko Payroll!",
  welcomeSubtitle: "Your intelligent guide to global payroll.",
  welcomeBody:
    "Explore payroll solutions, tax compliance, payslips, supported countries, integrations, and pricing. Choose a topic below or ask a question about Zoiko Payroll.",
  placeholder: "Ask a question about Zoiko Payroll…",
  publicNotice:
    "General information only. For help with your payroll account, sign in securely. Do not enter employee, payment, tax ID or other sensitive data.",
  statusAvailable: "AI assistant available",
  statusDegraded: "Limited availability",
  statusUnavailable: "Temporarily unavailable",
  statusChecking: "Checking availability…",
  insufficientEvidence: "I can't confirm that from current Zoiko Payroll information.",
  sessionExpired: "This session has expired. Start a new conversation.",
  rateLimited: "You're sending messages quickly. Please wait a moment and try again.",
  connectivity: "We couldn't reach the assistant. Check your connection and try again.",
  sensitiveWarning:
    "This looks like it may include sensitive data (such as a bank, tax ID or identity number). Please remove it — this assistant can't use personal or payroll details here.",
};

// Six exact topic cards (wireframe §04). `tone` picks the icon tint.
// Prompt `mode`: "send" submits the exact text; "prefill" puts it in the
// composer for the visitor to finish (used where a country is required).
// `actions` are follow-up CTAs shown with the answer.
export const TOPICS = [
  {
    id: "TOP-01",
    title: "Global Payroll",
    description: "Multi-country payroll for growing businesses",
    icon: "globe",
    tone: "blue",
    prompts: [
      { label: "Where is Zoiko Payroll available?", actions: ["checkCountry"] },
      { label: "How does multi-country payroll work?" },
      { label: "Can I manage several countries?" },
    ],
  },
  {
    id: "TOP-02",
    title: "Payroll & Payslips",
    description: "Employee pay, deductions and reports",
    icon: "payslip",
    tone: "green",
    prompts: [
      { label: "How do payslips work?" },
      { label: "What payroll reports are available?" },
      { label: "How do I access my own payslip?", actions: ["signIn"] },
    ],
  },
  {
    id: "TOP-03",
    title: "Taxes & Compliance",
    description: "Local tax rules, filings and regulations",
    icon: "taxes",
    tone: "purple",
    requiresCountry: true,
    prompts: [
      { label: "What payroll taxes apply in [country]?", mode: "prefill", prefill: "What payroll taxes apply in " },
      { label: "What tax features are available?" },
    ],
  },
  {
    id: "TOP-04",
    title: "Features & Integrations",
    description: "Platform features and integrations",
    icon: "features",
    tone: "orange",
    prompts: [
      { label: "Which accounting systems integrate?", actions: ["talkToSales"] },
      { label: "What are payroll approval workflows?" },
    ],
  },
  {
    id: "TOP-05",
    title: "Pricing & Demos",
    description: "Plans, trials and book a demo",
    icon: "pricing",
    tone: "rose",
    prompts: [
      { label: "What are your pricing plans?", actions: ["bookDemo", "talkToSales"] },
      { label: "How do I book a demo?", actions: ["bookDemo"] },
    ],
  },
  {
    id: "TOP-06",
    title: "Security & Privacy",
    description: "Data protection, compliance and trust",
    icon: "security",
    tone: "sky",
    prompts: [
      { label: "How does Zoiko Payroll protect payroll data?", actions: ["privacy"] },
      { label: "What security practices does Zoiko Payroll follow?" },
    ],
  },
];

// Six exact popular-question chips (wireframe §06).
export const POPULAR_QUESTIONS = [
  { id: "Q-01", label: "Which countries do you currently support?", actions: ["checkCountry"] },
  { id: "Q-02", label: "How do I generate a payslip?", actions: ["signIn"] },
  { id: "Q-03", label: "How does Zoiko Payroll handle taxes?", actions: ["checkCountry"] },
  { id: "Q-04", label: "Can you integrate with my accounting software?", actions: ["talkToSales"] },
  { id: "Q-05", label: "What are your pricing plans?", actions: ["bookDemo", "talkToSales"] },
  { id: "Q-06", label: "How do I book a demo?", actions: ["bookDemo"] },
];

export const DEFAULT_LOCALES = [{ code: "en", label: "English" }];

// Server default is 500 (backend public_service.MAX_MESSAGE_LENGTH); the
// config endpoint may raise it toward the spec's 1000 default.
export const DEFAULT_MAX_MESSAGE_LENGTH = 500;
export const REQUEST_TIMEOUT_MS = 25000;

// Deploy-time destinations. Every CTA without a real destination is hidden
// (wireframe §07: "never a dead control"). The server config, once
// deployed, overrides these via `links`.
const env = import.meta.env;
export const DEFAULT_LINKS = {
  signIn: env.VITE_ASSIST_SIGN_IN_URL || "/login",
  bookDemo: env.VITE_ASSIST_DEMO_URL || "",
  talkToSales: env.VITE_ASSIST_SALES_URL || "",
  contactSupport: env.VITE_ASSIST_SUPPORT_URL || "",
  faq: env.VITE_ASSIST_FAQ_URL || "",
  countryCoverage: env.VITE_ASSIST_COUNTRY_COVERAGE_URL || "",
  privacy: env.VITE_ASSIST_PRIVACY_URL || "",
};

const EXTRA_ALLOWED_HOSTS = (env.VITE_ASSIST_ALLOWED_LINK_HOSTS || "")
  .split(",")
  .map((h) => h.trim().toLowerCase())
  .filter(Boolean);

export function mergeConfig(serverConfig) {
  const links = { ...DEFAULT_LINKS };
  for (const [key, value] of Object.entries(serverConfig?.links || {})) {
    if (typeof value === "string" && value) links[key] = value;
  }
  const max = Number(serverConfig?.max_message_length);
  return {
    links,
    locales: Array.isArray(serverConfig?.locales) && serverConfig.locales.length ? serverConfig.locales : DEFAULT_LOCALES,
    maxMessageLength: Number.isFinite(max) && max > 0 ? max : DEFAULT_MAX_MESSAGE_LENGTH,
    liveSupportAvailable: serverConfig?.live_support_available === true,
    roadmapNote: typeof serverConfig?.roadmap_note === "string" ? serverConfig.roadmap_note : "",
  };
}

// Outbound links must be same-origin paths or https on an allowlisted host
// (wireframe §10 / A17). Hosts of configured CTA links are implicitly allowed.
export function isSafeLink(url, links = DEFAULT_LINKS) {
  if (!url || typeof url !== "string") return false;
  if (url.startsWith("/") && !url.startsWith("//")) return true;
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return false;
  }
  if (parsed.protocol !== "https:") return false;
  const host = parsed.hostname.toLowerCase();
  if (typeof window !== "undefined" && host === window.location.hostname) return true;
  const configuredHosts = Object.values(links)
    .map((l) => {
      try {
        return new URL(l).hostname.toLowerCase();
      } catch {
        return null;
      }
    })
    .filter(Boolean);
  return [...EXTRA_ALLOWED_HOSTS, ...configuredHosts].includes(host);
}

export function isExternalLink(url) {
  return /^https:\/\//i.test(url || "") && !(typeof window !== "undefined" && url.startsWith(window.location.origin));
}

// Client-side pre-submit screen for the public assistant (wireframe §08 /
// §12). Mirrors the backend guardrail patterns plus common card and
// national-ID shapes. Server-side classification still applies.
const SENSITIVE_PATTERNS = [
  /\b\d{9,}\b/,
  /\b\d{3}-\d{2}-\d{4}\b/,
  /\b(?:\d[ -]?){13,19}\b/,
  /\b[A-Za-z]{2}\d{2}[A-Za-z0-9]{10,30}\b/,
  /\b(?:routing|account|acct|iban|swift|sort\s*code|bsb)\s*(?:number|no\.?|#)?\s*[:-]?\s*[\d-]{4,}/i,
  /\b(?:password|passcode|pin)\s*[:=]\s*\S+/i,
  /\b[A-Z]{5}\d{4}[A-Z]\b/,
  /\b[A-CEGHJ-PR-TW-Z]{2}\d{6}[A-D]\b/i,
];

export function containsSensitiveData(text) {
  return SENSITIVE_PATTERNS.some((pattern) => pattern.test(text || ""));
}

// Intents the public backend answers from the knowledge base; anything
// else was redirected to sign-in (see backend public_service.py).
export const PUBLIC_ANSWER_INTENTS = new Set(["kb.answer", "explain.field", "chat.greeting", "chat.acknowledgment"]);

export function matchesCountry(country, query) {
  const q = query.trim().toLowerCase();
  if (!q) return true;
  if ((country.code || "").toLowerCase() === q) return true;
  if ((country.name || "").toLowerCase().includes(q)) return true;
  return (country.aliases || []).some((a) => String(a).toLowerCase().includes(q));
}

export function liveCountFromFeed(feed) {
  if (!feed) return null;
  if (Number.isFinite(feed.live_count)) return feed.live_count;
  const codes = new Set((feed.countries || []).filter((c) => c.launch_status === "live").map((c) => c.code));
  return codes.size;
}

export const CAPABILITY_LABELS = {
  payroll_engine: "Payroll processing",
  taxes: "Tax calculation",
  filings: "Statutory filings",
  payments: "Employee payments",
  payslips: "Payslips",
};
