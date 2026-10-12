import { forwardRef, useEffect, useId, useMemo, useRef, useState } from "react";
import {
  ArrowLeft,
  ArrowRight,
  CalendarDays,
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Clock,
  ExternalLink,
  FileText,
  Globe,
  Headphones,
  Landmark,
  LayoutGrid,
  Loader2,
  Lock,
  LogIn,
  Minus,
  RotateCcw,
  Search,
  Send,
  Settings,
  ShieldCheck,
  Sparkles,
  Square,
  Tag,
  TriangleAlert,
  Users,
  X,
} from "lucide-react";
import { CAPABILITY_LABELS, COPY, isExternalLink, isSafeLink, liveCountFromFeed, matchesCountry } from "./content";

// Shared building blocks for the Global Payroll AI Concierge panel, used by
// both the public (login page) widget and the signed-in AssistLauncher.
// Zones follow wireframe §03: A header → B welcome → C topics → D country
// check → E popular questions → F CTAs → G composer.

export const FOCUS_RING =
  "outline-none focus-visible:ring-2 focus-visible:ring-focus-ring focus-visible:ring-offset-2 focus-visible:ring-offset-surface";

// Mobile ≤767px: full-screen drawer with safe-area insets. Tablet/desktop:
// floating panel, 480px (≤90vw), max-height min(780px, 90dvh) (§09).
export const PANEL_CLASS =
  "fixed inset-0 z-[9998] flex flex-col overflow-hidden bg-surface pt-[env(safe-area-inset-top)] pb-[env(safe-area-inset-bottom)] md:inset-auto md:bottom-24 md:right-5 md:h-[min(780px,calc(100dvh-7.5rem))] md:w-[min(520px,92vw)] md:rounded-[20px] md:border md:border-border md:pt-0 md:pb-0 md:shadow-[0_24px_64px_rgba(8,43,69,0.22)]";

const TOPIC_ICONS = {
  globe: Globe,
  payslip: FileText,
  taxes: Landmark,
  features: Settings,
  pricing: Tag,
  security: ShieldCheck,
};

const TONES = {
  blue: "bg-primary/10 text-primary",
  green: "bg-emerald-500/10 text-emerald-600 dark:text-emerald-400",
  purple: "bg-violet-500/10 text-violet-600 dark:text-violet-400",
  orange: "bg-orange-500/10 text-orange-600 dark:text-orange-400",
  rose: "bg-rose-500/10 text-rose-600 dark:text-rose-400",
  sky: "bg-blue-500/10 text-blue-600 dark:text-blue-400",
};

function useDebouncedValue(value, delay) {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const id = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(id);
  }, [value, delay]);
  return debounced;
}

function useDismiss(open, onDismiss, refs) {
  useEffect(() => {
    if (!open) return undefined;
    function onPointer(e) {
      if (refs.every((r) => !r.current || !r.current.contains(e.target))) onDismiss();
    }
    document.addEventListener("mousedown", onPointer);
    return () => document.removeEventListener("mousedown", onPointer);
  }, [open, onDismiss, refs]);
}

export function formatVerifiedDate(iso) {
  if (!iso) return "";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return "";
  return new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", year: "numeric" }).format(date);
}

// ── Launcher ─────────────────────────────────────────────────────────────

export const ConciergeLauncher = forwardRef(function ConciergeLauncher({ open, onToggle, iconSrc, label }, ref) {
  return (
    <>
      <style>{`
        @keyframes conciergeGlow {
          0%, 100% { opacity: 0.55; transform: scale(1); }
          50% { opacity: 0.9; transform: scale(1.12); }
        }
        .concierge-glow { animation: conciergeGlow 2.8s ease-in-out infinite; }
        @media (prefers-reduced-motion: reduce) {
          .concierge-glow { animation: none; }
        }
      `}</style>
      <div className={`fixed bottom-6 right-6 z-[9997] h-14 w-14 ${open ? "max-md:hidden" : ""}`}>
        <div
          aria-hidden="true"
          className={`concierge-glow pointer-events-none absolute inset-0 rounded-2xl bg-primary blur-xl transition-opacity duration-300 ${
            open ? "opacity-80" : "opacity-55"
          }`}
        />
        <button
          ref={ref}
          type="button"
          onClick={onToggle}
          aria-label={label}
          aria-expanded={open}
          className={`relative flex h-14 w-14 items-center justify-center overflow-hidden rounded-2xl bg-[radial-gradient(circle_at_32%_26%,var(--color-primary-hover)_0%,var(--color-primary)_55%,var(--color-primary-active)_100%)] shadow-[inset_0_1px_1px_rgba(255,255,255,0.35),inset_0_-8px_14px_-6px_rgba(0,0,0,0.4),0_16px_30px_-8px_rgba(0,0,0,0.45)] transition-all duration-200 hover:-translate-y-[3px] hover:scale-[1.04] active:translate-y-0 active:scale-100 motion-reduce:transition-none motion-reduce:hover:translate-y-0 motion-reduce:hover:scale-100 ${FOCUS_RING} ${
            open ? "text-white" : ""
          }`}
        >
          {open ? <X size={22} /> : <img src={iconSrc} alt="" className="h-full w-full object-cover" />}
        </button>
      </div>
    </>
  );
});

// ── Zone A: header ───────────────────────────────────────────────────────

export function StatusIndicator({ status }) {
  const map = {
    available: { dot: "bg-success", label: COPY.statusAvailable },
    degraded: { dot: "bg-warning", label: COPY.statusDegraded },
    unavailable: { dot: "bg-foreground-disabled", label: COPY.statusUnavailable },
    checking: { dot: "bg-foreground-disabled animate-pulse motion-reduce:animate-none", label: COPY.statusChecking },
  };
  const current = map[status] || map.checking;
  return (
    <p className="flex items-center gap-1.5 text-[12px] text-foreground-secondary" role="status">
      <span aria-hidden="true" className={`h-2 w-2 shrink-0 rounded-full ${current.dot}`} />
      {current.label}
    </p>
  );
}

export function LanguageMenu({ locales, value, onChange }) {
  const [open, setOpen] = useState(false);
  const buttonRef = useRef(null);
  const menuRef = useRef(null);
  const refs = useMemo(() => [buttonRef, menuRef], []);
  useDismiss(open, () => setOpen(false), refs);
  const current = locales.find((l) => l.code === value) || locales[0];

  useEffect(() => {
    if (open) menuRef.current?.querySelector("[aria-checked='true'], button")?.focus();
  }, [open]);

  return (
    <div className="relative">
      <button
        ref={buttonRef}
        type="button"
        aria-haspopup="menu"
        aria-expanded={open}
        aria-label={`Language: ${current?.label || "English"}`}
        onClick={() => setOpen((v) => !v)}
        className={`inline-flex h-9 items-center gap-1 rounded-full border border-border bg-surface px-2.5 text-[13px] font-semibold text-foreground transition hover:border-primary hover:text-primary ${FOCUS_RING}`}
      >
        <Globe size={16} aria-hidden="true" />
        <span>{(current?.code || "en").toUpperCase()}</span>
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open ? (
        <div
          ref={menuRef}
          role="menu"
          aria-label="Language"
          onKeyDown={(e) => {
            if (e.key === "Escape") {
              e.stopPropagation();
              setOpen(false);
              buttonRef.current?.focus();
            }
          }}
          className="absolute right-0 top-10 z-30 min-w-[150px] rounded-[12px] border border-border bg-surface p-1 shadow-[0_12px_32px_rgba(8,43,69,0.16)]"
        >
          {locales.map((l) => (
            <button
              key={l.code}
              type="button"
              role="menuitemradio"
              aria-checked={l.code === current?.code}
              lang={l.code}
              onClick={() => {
                onChange?.(l.code);
                setOpen(false);
                buttonRef.current?.focus();
              }}
              className={`flex w-full items-center justify-between gap-3 rounded-[8px] px-3 py-2 text-left text-[13px] text-foreground transition hover:bg-surface-muted ${FOCUS_RING}`}
            >
              {l.label}
              {l.code === current?.code ? <Check size={14} className="text-primary" aria-hidden="true" /> : null}
            </button>
          ))}
        </div>
      ) : null}
    </div>
  );
}

export function HeaderIconButton({ label, onClick, children, pressed }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={label}
      aria-label={label}
      aria-pressed={pressed}
      className={`inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-[10px] bg-surface-muted text-foreground transition hover:bg-primary/10 hover:text-primary ${
        pressed ? "bg-primary/10 text-primary" : ""
      } ${FOCUS_RING}`}
    >
      {children}
    </button>
  );
}

export function ConciergeHeader({
  logoSrc,
  headingId,
  headingRef,
  status,
  locales,
  locale,
  onLocaleChange,
  onMinimize,
  onClose,
  extraActions = null,
}) {
  return (
    <div className="flex items-start gap-2.5 border-b border-border bg-surface px-4 py-3 md:px-5">
      <img src={logoSrc} alt="Zoiko Payroll" className="mt-0.5 h-7 w-auto shrink-0 max-sm:hidden" />
      <div aria-hidden="true" className="h-10 w-px shrink-0 self-center max-sm:hidden bg-border" />
      <div className="min-w-0 flex-1">
        <h2
          id={headingId}
          ref={headingRef}
          tabIndex={-1}
          className="text-[15px] font-bold leading-tight text-foreground outline-none"
        >
          {COPY.title}
        </h2>
        <p className="mt-0.5 truncate text-[12px] text-foreground-secondary max-sm:hidden">{COPY.subtitle}</p>
        <div className="mt-0.5">
          <StatusIndicator status={status} />
        </div>
      </div>
      <div className="flex shrink-0 items-center gap-1">
        {locales?.length ? <LanguageMenu locales={locales} value={locale} onChange={onLocaleChange} /> : null}
        {extraActions}
        <HeaderIconButton label="Minimize" onClick={onMinimize}>
          <Minus size={18} aria-hidden="true" />
        </HeaderIconButton>
        <HeaderIconButton label="Close" onClick={onClose}>
          <X size={18} aria-hidden="true" />
        </HeaderIconButton>
      </div>
    </div>
  );
}

// ── Zone B: welcome ──────────────────────────────────────────────────────

export function WelcomeBlock({ iconSrc, compact = false, body = COPY.welcomeBody }) {
  if (compact) {
    return (
      <div className="flex items-center gap-2.5 rounded-[14px] bg-primary-light/60 px-3 py-2 dark:bg-surface-muted">
        <img src={iconSrc} alt="" className="h-7 w-7 shrink-0 rounded-full" />
        <p className="text-[13px] font-semibold text-foreground">{COPY.welcomeSubtitle}</p>
      </div>
    );
  }
  return (
    <div className="flex items-start gap-3">
      <img src={iconSrc} alt="" className="h-11 w-11 shrink-0 rounded-full ring-4 ring-brand-navy/90 max-[359px]:hidden" />
      <div className="min-w-0 flex-1 rounded-[18px] bg-primary-light/60 px-4 py-3.5 dark:bg-surface-muted">
        <h3 className="text-[18px] font-bold leading-snug text-foreground">{COPY.welcomeTitle}</h3>
        <p className="mt-1 text-[14px] text-foreground-secondary">{COPY.welcomeSubtitle}</p>
        <p className="mt-2 text-[13px] leading-relaxed text-foreground-secondary">{body}</p>
      </div>
    </div>
  );
}

// ── Zone C: topics ───────────────────────────────────────────────────────

export function TopicGrid({ topics, activeTopicId, onSelectTopic, onBack, onPrompt, disabled }) {
  const active = topics.find((t) => t.id === activeTopicId);
  const backRef = useRef(null);

  useEffect(() => {
    if (active) backRef.current?.focus();
  }, [active]);

  if (active) {
    const Icon = TOPIC_ICONS[active.icon] || Globe;
    return (
      <section aria-labelledby={`topic-${active.id}`} className="rounded-[16px] border border-border bg-surface p-4">
        <button
          ref={backRef}
          type="button"
          onClick={onBack}
          className={`mb-3 inline-flex items-center gap-1.5 rounded-[8px] text-[12px] font-semibold text-primary hover:underline ${FOCUS_RING}`}
        >
          <ArrowLeft size={14} aria-hidden="true" /> Back to topics
        </button>
        <div className="flex items-center gap-3">
          <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${TONES[active.tone]}`}>
            <Icon size={20} aria-hidden="true" />
          </span>
          <div>
            <h3 id={`topic-${active.id}`} className="text-[15px] font-bold text-foreground">
              {active.title}
            </h3>
            <p className="text-[12px] text-foreground-secondary">{active.description}</p>
          </div>
        </div>
        {active.requiresCountry ? (
          <p className="mt-3 rounded-[10px] bg-surface-muted px-3 py-2 text-[12px] text-foreground-secondary">
            Country-specific rules depend on the jurisdiction — include the country in your question.
          </p>
        ) : null}
        <ul className="mt-3 space-y-2">
          {active.prompts.map((p) => (
            <li key={p.label}>
              <button
                type="button"
                disabled={disabled && p.mode !== "prefill"}
                onClick={() => onPrompt(p, active)}
                className={`flex w-full items-center gap-2.5 rounded-[12px] border border-border bg-surface-muted/60 px-3 py-2.5 text-left text-[13px] text-foreground transition hover:border-primary hover:text-primary disabled:opacity-50 ${FOCUS_RING}`}
              >
                <Search size={15} className="shrink-0 text-primary" aria-hidden="true" />
                <span className="flex-1">{p.label}</span>
                <ChevronRight size={15} className="shrink-0 text-foreground-muted" aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      </section>
    );
  }

  return (
    <section aria-label="Topics">
      <ul className="grid grid-cols-1 gap-2.5 min-[480px]:grid-cols-2">
        {topics.map((topic) => {
          const Icon = TOPIC_ICONS[topic.icon] || Globe;
          return (
            <li key={topic.id}>
              <button
                type="button"
                onClick={() => onSelectTopic(topic.id)}
                className={`group flex h-full w-full items-center gap-2.5 rounded-[14px] border border-border bg-surface p-3 text-left transition hover:border-primary hover:shadow-[0_6px_18px_rgba(8,124,193,0.10)] ${FOCUS_RING}`}
              >
                <span className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-full ${TONES[topic.tone]}`}>
                  <Icon size={19} aria-hidden="true" />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block text-[13px] font-bold leading-tight text-foreground">{topic.title}</span>
                  <span className="mt-0.5 block text-[11.5px] leading-snug text-foreground-secondary">
                    {topic.description}
                  </span>
                </span>
                <ChevronRight
                  size={16}
                  className="shrink-0 text-foreground-muted transition group-hover:translate-x-0.5 group-hover:text-primary motion-reduce:transition-none"
                  aria-hidden="true"
                />
              </button>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// ── Zone D: country check ────────────────────────────────────────────────

const STATUS_CHIPS = {
  live: { label: "Available", className: "bg-success-light text-success" },
  planned: { label: "Planned", className: "bg-warning-light text-warning" },
  unavailable: { label: "Not listed", className: "bg-surface-muted text-foreground-muted" },
};

function statusChip(status) {
  return STATUS_CHIPS[status] || STATUS_CHIPS.unavailable;
}

function normalizeCapability(value) {
  if (value === true) return "verified";
  if (value === false) return "unsupported";
  const s = typeof value === "object" && value ? value.status : value;
  if (s === "verified" || s === "supported" || s === "live") return "verified";
  if (s === "unsupported" || s === "not_supported") return "unsupported";
  return "unconfirmed";
}

function ActionLink({ href, links, children, variant = "outline", icon: Icon }) {
  if (!href || !isSafeLink(href, links)) return null;
  const external = isExternalLink(href);
  const styles =
    variant === "primary"
      ? "bg-primary text-white hover:bg-primary-hover border-transparent"
      : "border-border bg-surface text-foreground hover:border-primary hover:text-primary";
  return (
    <a
      href={href}
      {...(external ? { target: "_blank", rel: "noopener noreferrer" } : {})}
      className={`inline-flex items-center gap-1.5 rounded-[10px] border px-3 py-2 text-[12px] font-semibold transition ${styles} ${FOCUS_RING}`}
    >
      {Icon ? <Icon size={14} aria-hidden="true" /> : null}
      {children}
      {external ? <ExternalLink size={12} aria-hidden="true" /> : null}
      {external ? <span className="sr-only">(opens in a new tab)</span> : null}
    </a>
  );
}

function CountryDetail({ country, links, onAsk, disabled }) {
  if (country.unknown) {
    return (
      <div className="mt-3 rounded-[12px] border border-border bg-surface p-3" role="status">
        <p className="text-[13px] font-semibold text-foreground">{country.name}</p>
        <p className="mt-1 text-[12px] text-foreground-secondary">
          Not currently listed as available. Talk to Sales to confirm options.
        </p>
        <div className="mt-2.5 flex flex-wrap gap-2">
          <ActionLink href={links.talkToSales} links={links} icon={Users}>
            Talk to Sales
          </ActionLink>
        </div>
      </div>
    );
  }

  const chip = statusChip(country.launch_status);
  const capabilityEntries = Object.entries(country.capabilities || {});
  const verified = formatVerifiedDate(country.verified_at);

  return (
    <div className="mt-3 rounded-[12px] border border-border bg-surface p-3" role="status">
      <div className="flex flex-wrap items-center gap-2">
        <p className="text-[14px] font-bold text-foreground">
          {country.name} <span className="font-normal text-foreground-muted">({country.code})</span>
        </p>
        <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${chip.className}`}>{chip.label}</span>
      </div>

      {country.launch_status === "live" ? (
        <>
          {capabilityEntries.length ? (
            <ul className="mt-2.5 space-y-1.5">
              {capabilityEntries.map(([key, value]) => {
                const state = normalizeCapability(value);
                return (
                  <li key={key} className="flex items-center justify-between gap-3 text-[12px]">
                    <span className="text-foreground">{CAPABILITY_LABELS[key] || key.replace(/_/g, " ")}</span>
                    <span
                      className={
                        state === "verified"
                          ? "font-semibold text-success"
                          : state === "unsupported"
                            ? "text-foreground-muted"
                            : "text-warning"
                      }
                    >
                      {state === "verified" ? "Confirmed" : state === "unsupported" ? "Not supported" : "Not confirmed"}
                    </span>
                  </li>
                );
              })}
            </ul>
          ) : (
            <p className="mt-2 text-[12px] text-foreground-secondary">
              Capability details for this country haven&apos;t been published yet. Talk to Sales for specifics.
            </p>
          )}
          {verified ? <p className="mt-2 text-[11px] text-foreground-muted">Last verified {verified}</p> : null}
        </>
      ) : country.launch_status === "planned" ? (
        <p className="mt-2 text-[12px] text-foreground-secondary">
          {country.public_launch_date
            ? `Planned — expected ${formatVerifiedDate(country.public_launch_date)}`
            : "Planned — date not announced"}
        </p>
      ) : (
        <p className="mt-2 text-[12px] text-foreground-secondary">
          Not currently listed as available. Talk to Sales to confirm options.
        </p>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {country.launch_status === "live" && onAsk ? (
          <button
            type="button"
            disabled={disabled}
            onClick={() => onAsk(country)}
            className={`inline-flex items-center gap-1.5 rounded-[10px] bg-primary px-3 py-2 text-[12px] font-semibold text-white transition hover:bg-primary-hover disabled:opacity-50 ${FOCUS_RING}`}
          >
            Ask about payroll in {country.name}
          </button>
        ) : null}
        <ActionLink href={country.source_url} links={links}>
          Learn more
        </ActionLink>
        <ActionLink href={links.talkToSales} links={links} icon={Users}>
          Talk to Sales
        </ActionLink>
      </div>
    </div>
  );
}

export const CountryCheck = forwardRef(function CountryCheck(
  { feed, feedState, links, roadmapNote, onAsk, disabled },
  inputRef
) {
  const baseId = useId();
  const listId = `${baseId}-list`;
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const [selected, setSelected] = useState(null);
  const debouncedQuery = useDebouncedValue(query, 300);
  const wrapRef = useRef(null);
  const refs = useMemo(() => [wrapRef], []);
  useDismiss(open, () => setOpen(false), refs);

  const countries = useMemo(() => {
    const list = (feed?.countries || []).filter((c) => matchesCountry(c, debouncedQuery));
    const rank = { live: 0, planned: 1 };
    return list
      .slice()
      .sort((a, b) => (rank[a.launch_status] ?? 2) - (rank[b.launch_status] ?? 2) || a.name.localeCompare(b.name))
      .slice(0, 50);
  }, [feed, debouncedQuery]);

  const liveCount = useMemo(() => liveCountFromFeed(feed), [feed]);

  function choose(country) {
    setSelected(country);
    setQuery(country.name);
    setOpen(false);
    setActiveIndex(-1);
  }

  function onKeyDown(e) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setOpen(true);
      setActiveIndex((i) => Math.min(i + 1, countries.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setActiveIndex((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (open && activeIndex >= 0 && countries[activeIndex]) choose(countries[activeIndex]);
      else if (query.trim() && countries.length === 0) {
        setSelected({ unknown: true, name: query.trim() });
        setOpen(false);
      } else if (countries.length === 1) choose(countries[0]);
    } else if (e.key === "Escape" && open) {
      e.stopPropagation();
      setOpen(false);
      setActiveIndex(-1);
    }
  }

  const unavailable = feedState === "error";
  const loading = feedState === "loading";

  return (
    <section
      aria-labelledby={`${baseId}-title`}
      className="rounded-[16px] border border-border bg-surface-muted/60 p-4"
    >
      <div className="flex items-start gap-3">
        <Globe size={30} className="mt-0.5 shrink-0 text-primary max-[359px]:hidden" aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <h3 id={`${baseId}-title`} className="text-[15px] font-bold text-foreground">
            Check your country
          </h3>
          <p className="mt-0.5 text-[12px] leading-relaxed text-foreground-secondary">
            See if your country is supported and view local payroll and compliance information.
          </p>
        </div>
      </div>

      <div ref={wrapRef} className="relative mt-3">
        <label htmlFor={`${baseId}-input`} className="sr-only">
          Check your country
        </label>
        <Search
          size={16}
          className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-foreground-muted"
          aria-hidden="true"
        />
        <input
          ref={inputRef}
          id={`${baseId}-input`}
          type="text"
          role="combobox"
          autoComplete="off"
          aria-autocomplete="list"
          aria-expanded={open}
          aria-controls={listId}
          aria-activedescendant={open && activeIndex >= 0 ? `${listId}-${activeIndex}` : undefined}
          disabled={unavailable || loading}
          placeholder={loading ? "Loading countries…" : "Search a country…"}
          value={query}
          onChange={(e) => {
            setQuery(e.target.value);
            setSelected(null);
            setOpen(true);
            setActiveIndex(-1);
          }}
          onFocus={() => !unavailable && setOpen(true)}
          onKeyDown={onKeyDown}
          className="h-11 w-full rounded-[12px] border border-border bg-surface pl-9 pr-9 text-[13px] text-foreground placeholder-foreground-muted outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60"
        />
        <ChevronDown
          size={16}
          className="pointer-events-none absolute right-3 top-1/2 -translate-y-1/2 text-foreground-muted"
          aria-hidden="true"
        />
        {open && !unavailable && !loading ? (
          <ul
            id={listId}
            role="listbox"
            aria-label="Countries"
            className="absolute left-0 right-0 top-12 z-20 max-h-56 overflow-y-auto rounded-[12px] border border-border bg-surface p-1 shadow-[0_12px_32px_rgba(8,43,69,0.16)]"
          >
            {countries.length === 0 ? (
              <li className="px-3 py-2 text-[12px] text-foreground-secondary" role="option" aria-selected="false" aria-disabled="true">
                {query.trim() ? "No listed match — press Enter to check this country." : "Start typing a country name or code."}
              </li>
            ) : (
              countries.map((c, i) => {
                const chip = statusChip(c.launch_status);
                return (
                  <li
                    key={c.code}
                    id={`${listId}-${i}`}
                    role="option"
                    aria-selected={i === activeIndex}
                    onMouseDown={(e) => e.preventDefault()}
                    onClick={() => choose(c)}
                    className={`flex cursor-pointer items-center justify-between gap-2 rounded-[8px] px-3 py-2 text-[13px] text-foreground ${
                      i === activeIndex ? "bg-primary/10" : "hover:bg-surface-muted"
                    }`}
                  >
                    <span>
                      {c.name} <span className="text-foreground-muted">{c.code}</span>
                    </span>
                    <span className={`rounded-full px-2 py-0.5 text-[10.5px] font-semibold ${chip.className}`}>
                      {chip.label}
                    </span>
                  </li>
                );
              })
            )}
          </ul>
        ) : null}
      </div>

      <div className="mt-2.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
        {unavailable ? (
          <span className="flex items-center gap-1.5 text-foreground-secondary">
            <Clock size={14} aria-hidden="true" /> Check country availability
          </span>
        ) : liveCount !== null ? (
          <span className="flex items-center gap-1.5 font-semibold text-foreground">
            <CheckCircle2 size={15} className="text-success" aria-hidden="true" />
            {liveCount} {liveCount === 1 ? "jurisdiction" : "jurisdictions"} live
          </span>
        ) : null}
        {roadmapNote && !unavailable ? (
          <>
            <span aria-hidden="true" className="h-3.5 w-px bg-border" />
            <span className="flex items-center gap-1.5 text-foreground-secondary">
              <Clock size={14} aria-hidden="true" /> {roadmapNote}
            </span>
          </>
        ) : null}
      </div>

      {unavailable ? (
        <div className="mt-2.5 flex flex-wrap gap-2">
          <ActionLink href={links.countryCoverage} links={links} icon={Globe}>
            View country coverage
          </ActionLink>
          <ActionLink href={links.talkToSales} links={links} icon={Users}>
            Talk to Sales
          </ActionLink>
        </div>
      ) : null}

      {selected ? <CountryDetail country={selected} links={links} onAsk={onAsk} disabled={disabled} /> : null}
    </section>
  );
});

// ── Zone E: popular questions ────────────────────────────────────────────

export function PopularQuestions({ questions, onPick, disabled, faqUrl, links, title = "Popular questions" }) {
  if (!questions.length) return null;
  return (
    <section aria-labelledby="concierge-popular-title">
      <div className="mb-2.5 flex items-center justify-between gap-3">
        <h3 id="concierge-popular-title" className="text-[15px] font-bold text-foreground">
          {title}
        </h3>
        {faqUrl && isSafeLink(faqUrl, links) ? (
          <a
            href={faqUrl}
            {...(isExternalLink(faqUrl) ? { target: "_blank", rel: "noopener noreferrer" } : {})}
            className={`inline-flex items-center gap-1 rounded-[6px] text-[12px] font-semibold text-primary hover:underline ${FOCUS_RING}`}
          >
            View all questions <ArrowRight size={13} aria-hidden="true" />
          </a>
        ) : null}
      </div>
      <ul className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {questions.map((q) => (
          <li key={q.id}>
            <button
              type="button"
              disabled={disabled}
              onClick={() => onPick(q)}
              className={`flex h-full w-full items-center gap-2.5 rounded-[12px] border border-border bg-surface-muted/60 px-3 py-2.5 text-left text-[12.5px] text-foreground transition hover:border-primary hover:text-primary disabled:opacity-50 ${FOCUS_RING}`}
            >
              <Search size={15} className="shrink-0 text-primary" aria-hidden="true" />
              <span>{q.label}</span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  );
}

// ── Zone F: commercial & support actions ─────────────────────────────────

export function CtaRow({ links, onSupport, supportExpanded }) {
  const demo = links.bookDemo && isSafeLink(links.bookDemo, links);
  const sales = links.talkToSales && isSafeLink(links.talkToSales, links);
  const btn = `flex min-h-11 flex-1 basis-[140px] items-center justify-center gap-1.5 whitespace-nowrap rounded-[12px] border px-2 py-2.5 text-[13px] font-bold transition ${FOCUS_RING}`;
  const linkProps = (href) => (isExternalLink(href) ? { target: "_blank", rel: "noopener noreferrer" } : {});
  return (
    <div className="flex flex-wrap gap-2">
      {demo ? (
        <a href={links.bookDemo} {...linkProps(links.bookDemo)} className={`${btn} border-transparent bg-primary text-white hover:bg-primary-hover`}>
          <CalendarDays size={17} aria-hidden="true" /> Book a Demo <ChevronRight size={15} aria-hidden="true" />
        </a>
      ) : null}
      {sales ? (
        <a href={links.talkToSales} {...linkProps(links.talkToSales)} className={`${btn} border-primary/40 bg-surface text-foreground hover:border-primary hover:text-primary`}>
          <Users size={17} aria-hidden="true" /> Talk to Sales <ChevronRight size={15} aria-hidden="true" />
        </a>
      ) : null}
      <button
        type="button"
        onClick={onSupport}
        aria-expanded={supportExpanded}
        className={`${btn} border-primary/40 bg-surface text-foreground hover:border-primary hover:text-primary`}
      >
        <Headphones size={17} aria-hidden="true" /> Speak to Support <ChevronRight size={15} aria-hidden="true" />
      </button>
    </div>
  );
}

// Two honest support paths (§07). Live chat only when the server confirms a
// staffed channel; otherwise contact/ticket route — never an "agent online".
export function SupportChooser({ links, liveSupportAvailable, onClose }) {
  const ref = useRef(null);
  useEffect(() => {
    ref.current?.focus();
  }, []);
  return (
    <section
      ref={ref}
      tabIndex={-1}
      aria-label="Support options"
      onKeyDown={(e) => {
        if (e.key === "Escape") {
          e.stopPropagation();
          onClose();
        }
      }}
      className="rounded-[16px] border border-border bg-surface p-4 outline-none"
    >
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[14px] font-bold text-foreground">How can we help?</h3>
        <button
          type="button"
          onClick={onClose}
          aria-label="Close support options"
          className={`rounded-[8px] p-1 text-foreground-muted hover:text-primary ${FOCUS_RING}`}
        >
          <X size={15} aria-hidden="true" />
        </button>
      </div>
      <ul className="mt-3 space-y-2">
        {links.signIn && isSafeLink(links.signIn, links) ? (
          <li>
            <a
              href={links.signIn}
              className={`flex items-center gap-3 rounded-[12px] border border-border px-3 py-2.5 text-[13px] text-foreground transition hover:border-primary ${FOCUS_RING}`}
            >
              <LogIn size={17} className="shrink-0 text-primary" aria-hidden="true" />
              <span className="flex-1">
                <span className="block font-semibold">I&apos;m a customer</span>
                <span className="block text-[12px] text-foreground-secondary">Sign in for account support</span>
              </span>
              <ChevronRight size={15} className="text-foreground-muted" aria-hidden="true" />
            </a>
          </li>
        ) : null}
        <li>
          {links.contactSupport && isSafeLink(links.contactSupport, links) ? (
            <a
              href={links.contactSupport}
              {...(isExternalLink(links.contactSupport) ? { target: "_blank", rel: "noopener noreferrer" } : {})}
              className={`flex items-center gap-3 rounded-[12px] border border-border px-3 py-2.5 text-[13px] text-foreground transition hover:border-primary ${FOCUS_RING}`}
            >
              <Headphones size={17} className="shrink-0 text-primary" aria-hidden="true" />
              <span className="flex-1">
                <span className="block font-semibold">General website or product question</span>
                <span className="block text-[12px] text-foreground-secondary">
                  {liveSupportAvailable ? "Chat with our support team" : "Contact support"}
                </span>
              </span>
              <ChevronRight size={15} className="text-foreground-muted" aria-hidden="true" />
            </a>
          ) : (
            <p className="rounded-[12px] bg-surface-muted px-3 py-2.5 text-[12px] text-foreground-secondary">
              For general questions, ask here — or check our help resources on the Zoiko Payroll website.
            </p>
          )}
        </li>
      </ul>
    </section>
  );
}

// ── Answer follow-up actions ─────────────────────────────────────────────

export function AnswerActions({ actions, links, onCheckCountry }) {
  if (!actions?.length) return null;
  const items = actions
    .map((a) => {
      switch (a) {
        case "signIn":
          return links.signIn ? { key: a, href: links.signIn, label: "Sign in", icon: LogIn } : null;
        case "bookDemo":
          return links.bookDemo ? { key: a, href: links.bookDemo, label: "Book a Demo", icon: CalendarDays, primary: true } : null;
        case "talkToSales":
          return links.talkToSales ? { key: a, href: links.talkToSales, label: "Talk to Sales", icon: Users } : null;
        case "privacy":
          return links.privacy ? { key: a, href: links.privacy, label: "Privacy & trust", icon: ShieldCheck } : null;
        case "checkCountry":
          return onCheckCountry ? { key: a, onClick: onCheckCountry, label: "Check your country", icon: Globe } : null;
        default:
          return null;
      }
    })
    .filter(Boolean);
  if (!items.length) return null;
  return (
    <div className="mt-2.5 flex flex-wrap gap-2">
      {items.map((item) =>
        item.onClick ? (
          <button
            key={item.key}
            type="button"
            onClick={item.onClick}
            className={`inline-flex items-center gap-1.5 rounded-[10px] border border-border bg-surface px-3 py-2 text-[12px] font-semibold text-foreground transition hover:border-primary hover:text-primary ${FOCUS_RING}`}
          >
            <item.icon size={14} aria-hidden="true" /> {item.label}
          </button>
        ) : (
          <ActionLink key={item.key} href={item.href} links={links} icon={item.icon} variant={item.primary ? "primary" : "outline"}>
            {item.label}
          </ActionLink>
        )
      )}
    </div>
  );
}

// ── Public conversation bubbles ──────────────────────────────────────────

export function PublicMessageBubble({ message, links, iconSrc, onRetry, onCheckCountry, retryDisabled }) {
  if (message.role === "user") {
    return (
      <div className="flex flex-col items-end">
        <div className="max-w-[85%] whitespace-pre-wrap break-words rounded-[16px] rounded-br-[4px] bg-primary px-3.5 py-2.5 text-[13px] leading-relaxed text-white">
          {message.content}
        </div>
        {message.status === "failed" ? (
          <p className="mt-1 flex items-center gap-2 text-[11.5px] text-error">
            <TriangleAlert size={13} aria-hidden="true" /> Not sent.
            <button
              type="button"
              disabled={retryDisabled}
              onClick={() => onRetry(message)}
              className={`inline-flex items-center gap-1 font-semibold underline disabled:opacity-50 ${FOCUS_RING}`}
            >
              <RotateCcw size={12} aria-hidden="true" /> Retry
            </button>
          </p>
        ) : null}
      </div>
    );
  }

  return (
    <div className="flex items-start gap-2">
      <img src={iconSrc} alt="" className="mt-0.5 h-7 w-7 shrink-0 rounded-full" />
      <div
        className={`max-w-[85%] rounded-[16px] rounded-bl-[4px] border px-3.5 py-2.5 text-[13px] leading-relaxed ${
          "border-border bg-surface text-foreground"
        }`}
      >
        <p className="whitespace-pre-wrap break-words">{message.content}</p>
        {message.sources?.length ? (
          <div className="mt-2.5 border-t border-border-light pt-2">
            <p className="text-[10.5px] font-semibold uppercase tracking-wide text-foreground-muted">Sources</p>
            <ul className="mt-1 space-y-1">
              {message.sources.map((s, i) => {
                const href = s.approved_url || s.url;
                const verified = formatVerifiedDate(s.verified_at);
                return (
                  <li key={`${s.title}-${i}`} className="text-[11.5px] text-foreground-secondary">
                    {href && isSafeLink(href, links) ? (
                      <a
                        href={href}
                        {...(isExternalLink(href) ? { target: "_blank", rel: "noopener noreferrer" } : {})}
                        className={`font-semibold text-primary hover:underline ${FOCUS_RING}`}
                      >
                        {s.title} — Learn more
                      </a>
                    ) : (
                      <span className="font-semibold text-foreground">{s.title}</span>
                    )}
                    {verified ? <span className="text-foreground-muted"> · Last verified {verified}</span> : null}
                  </li>
                );
              })}
            </ul>
          </div>
        ) : null}
        <AnswerActions actions={message.actions} links={links} onCheckCountry={onCheckCountry} />
      </div>
    </div>
  );
}

export function ThinkingBubble({ iconSrc }) {
  return (
    <div className="flex items-start gap-2">
      <img src={iconSrc} alt="" className="mt-0.5 h-7 w-7 shrink-0 rounded-full" />
      <div className="flex items-center gap-2 rounded-[16px] rounded-bl-[4px] border border-border bg-surface px-3.5 py-2.5 text-[12px] text-foreground-muted">
        <Loader2 size={14} className="animate-spin text-primary motion-reduce:animate-none" aria-hidden="true" />
        Thinking…
      </div>
    </div>
  );
}

// ── Zone G: composer ─────────────────────────────────────────────────────

export const ConciergeComposer = forwardRef(function ConciergeComposer(
  { value, onChange, onSubmit, sending, disabled, maxLength, notice, warning, onStop, onShowTopics, showTopicsButton },
  textareaRef
) {
  const length = value.length;
  const tooLong = length > maxLength;
  const nearLimit = length >= Math.floor(maxLength * 0.8);
  const canSend = !disabled && !sending && value.trim().length > 0 && !tooLong;
  const counterId = useId();

  return (
    <div className="border-t border-border bg-surface px-4 pb-3 pt-3 md:px-5">
      {showTopicsButton ? (
        <button
          type="button"
          onClick={onShowTopics}
          className={`mb-2 inline-flex items-center gap-1.5 rounded-[8px] text-[12px] font-semibold text-primary hover:underline ${FOCUS_RING}`}
        >
          <LayoutGrid size={13} aria-hidden="true" /> Topics
        </button>
      ) : null}
      {warning ? (
        <p role="alert" className="mb-2 flex items-start gap-2 rounded-[10px] bg-warning-light px-3 py-2 text-[12px] text-foreground">
          <TriangleAlert size={14} className="mt-0.5 shrink-0 text-warning" aria-hidden="true" />
          {warning}
        </p>
      ) : null}
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (canSend) onSubmit();
        }}
        className="flex items-end gap-2.5"
      >
        <div className="relative flex min-w-0 flex-1 items-end rounded-[16px] border border-border bg-surface transition focus-within:border-primary focus-within:ring-2 focus-within:ring-primary/20">
          <Sparkles size={18} className="pointer-events-none absolute left-3.5 top-3.5 max-sm:hidden text-primary" aria-hidden="true" />
          <label htmlFor={`${counterId}-input`} className="sr-only">
            {COPY.placeholder}
          </label>
          <textarea
            ref={textareaRef}
            id={`${counterId}-input`}
            value={value}
            disabled={disabled}
            aria-invalid={tooLong}
            aria-describedby={nearLimit ? counterId : undefined}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                if (canSend) onSubmit();
              }
            }}
            rows={1}
            placeholder={COPY.placeholder}
            className="max-h-32 min-h-[48px] w-full resize-none bg-transparent py-3 pl-3.5 pr-3 text-[14px] sm:pl-11 text-foreground placeholder-foreground-muted outline-none disabled:cursor-not-allowed"
          />
        </div>
        {sending && onStop ? (
          <button
            type="button"
            onClick={onStop}
            aria-label="Stop response"
            title="Stop response"
            className={`inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-full border border-border bg-surface text-foreground-muted transition hover:border-error hover:text-error ${FOCUS_RING}`}
          >
            <Square size={15} aria-hidden="true" />
          </button>
        ) : (
          <button
            type="submit"
            disabled={!canSend}
            aria-label={sending ? "Sending…" : "Send message"}
            className={`inline-flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-primary text-white shadow-[0_8px_18px_rgba(8,124,193,0.35)] transition hover:bg-primary-hover disabled:opacity-40 disabled:shadow-none ${FOCUS_RING}`}
          >
            {sending ? (
              <Loader2 size={18} className="animate-spin motion-reduce:animate-none" aria-hidden="true" />
            ) : (
              <Send size={18} aria-hidden="true" />
            )}
          </button>
        )}
      </form>
      <div className="mt-2 flex items-start justify-between gap-3">
        {notice ? (
          <p className="flex items-start gap-1.5 text-[11px] leading-snug text-foreground-muted">
            <Lock size={12} className="mt-px shrink-0" aria-hidden="true" />
            {notice}
          </p>
        ) : (
          <span />
        )}
        {nearLimit ? (
          <p id={counterId} className={`shrink-0 text-[11px] tabular-nums ${tooLong ? "font-semibold text-error" : "text-foreground-muted"}`}>
            {length}/{maxLength}
          </p>
        ) : null}
      </div>
      {tooLong ? (
        <p role="alert" className="mt-1 text-[11.5px] text-error">
          Message is too long (max {maxLength} characters).
        </p>
      ) : null}
    </div>
  );
});
