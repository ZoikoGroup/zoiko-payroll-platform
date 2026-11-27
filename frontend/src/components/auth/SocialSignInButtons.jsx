import { useEffect, useId, useState } from "react";
import { ArrowRight, Building2, ChevronRight, Loader2 } from "lucide-react";
import { API_BASE } from "../../api/client";

// Provider sign-in buttons, shared by the sign-in and create-account pages so
// both show the same four options in the same order and style.
//
// `mode` ("login" | "register") picks the API endpoint: register mode sends a
// new identity to /register to finish org signup instead of signing in.
// Microsoft and Apple run only once the server has their credentials (GET
// /api/auth/providers); until then the button explains it isn't available.
// Company SSO is shown only when the server enables it (COMPANY_SSO_ENABLED,
// off by default until organization SSO is fully built). It asks for the work
// email and looks up its domain: a domain whose organization has SSO set up
// goes straight to that organization's sign-in.
// `compact` lays the buttons out two per row (create-account wizard).

const MicrosoftIcon = () => (
  <svg width="20" height="20" viewBox="0 0 20 20" aria-hidden="true">
    <rect x="0" y="0" width="9.5" height="9.5" fill="#F25022" />
    <rect x="10.5" y="0" width="9.5" height="9.5" fill="#7FBA00" />
    <rect x="0" y="10.5" width="9.5" height="9.5" fill="#00A4EF" />
    <rect x="10.5" y="10.5" width="9.5" height="9.5" fill="#FFB900" />
  </svg>
);

const GoogleIcon = () => (
  <svg width="20" height="20" viewBox="0 0 18 18" aria-hidden="true">
    <path d="M17.64 9.2c0-.637-.057-1.251-.164-1.84H9v3.481h4.844c-.209 1.125-.843 2.078-1.796 2.716v2.259h2.908c1.702-1.567 2.684-3.875 2.684-6.615z" fill="#4285F4" />
    <path d="M9 18c2.43 0 4.467-.806 5.956-2.18l-2.908-2.259c-.806.54-1.837.86-3.048.86-2.344 0-4.328-1.584-5.036-3.711H.957v2.332A8.997 8.997 0 0 0 9 18z" fill="#34A853" />
    <path d="M3.964 10.71A5.41 5.41 0 0 1 3.682 9c0-.593.102-1.17.282-1.71V4.958H.957A8.996 8.996 0 0 0 0 9c0 1.452.348 2.827.957 4.042l3.007-2.332z" fill="#FBBC05" />
    <path d="M9 3.58c1.321 0 2.508.454 3.44 1.345l2.582-2.58C13.463.891 11.426 0 9 0A8.997 8.997 0 0 0 .957 4.958L3.964 7.29C4.672 5.163 6.656 3.58 9 3.58z" fill="#EA4335" />
  </svg>
);

const AppleIcon = () => (
  <svg width="20" height="20" viewBox="0 0 24 24" fill="#000" aria-hidden="true">
    <path d="M16.37 12.6c-.02-2.2 1.8-3.26 1.88-3.31-1.02-1.5-2.62-1.7-3.19-1.72-1.36-.14-2.65.8-3.34.8-.69 0-1.75-.78-2.88-.76-1.48.02-2.85.86-3.61 2.19-1.54 2.67-.39 6.62 1.11 8.79.73 1.06 1.6 2.25 2.74 2.21 1.1-.04 1.52-.71 2.85-.71 1.33 0 1.71.71 2.88.69 1.19-.02 1.94-1.08 2.66-2.15.84-1.23 1.19-2.42 1.21-2.48-.03-.01-2.32-.89-2.34-3.53zM14.18 6.13c.6-.73 1.01-1.75.9-2.76-.87.04-1.92.58-2.54 1.31-.56.65-1.05 1.68-.92 2.67.97.08 1.96-.49 2.56-1.22z" />
  </svg>
);

const SsoIcon = () => <Building2 size={20} className="text-slate-700" aria-hidden="true" />;

export const SOCIAL_PROVIDERS = [
  { key: "microsoft", label: "Continue with Microsoft", name: "Microsoft", icon: MicrosoftIcon },
  { key: "google", label: "Continue with Google", name: "Google", icon: GoogleIcon },
  { key: "apple", label: "Continue with Apple", name: "Apple", icon: AppleIcon },
  { key: "sso", label: "Continue with Company SSO", name: "Company SSO", icon: SsoIcon },
];

// Before the server answers, Google keeps its long-standing behaviour
// (always offered); Microsoft / Apple wait for confirmation.
const DEFAULT_STATUS = { google: true, microsoft: false, apple: false, sso: false };
let statusPromise = null;

function loadProviderStatus() {
  if (!statusPromise) {
    statusPromise = fetch(`${API_BASE}/api/auth/providers`, { credentials: "include" })
      .then((res) => (res.ok ? res.json() : DEFAULT_STATUS))
      .then((status) => ({ ...DEFAULT_STATUS, ...status }))
      .catch(() => {
        statusPromise = null; // try again next time a page mounts
        return DEFAULT_STATUS;
      });
  }
  return statusPromise;
}

function CompanySsoPanel({ mode, onClose }) {
  const inputId = useId();
  const [email, setEmail] = useState("");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState(null);

  async function discover(e) {
    e.preventDefault();
    setMessage(null);
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email.trim())) {
      setMessage({ tone: "error", text: "Enter your work email address, like name@company.com." });
      return;
    }
    setBusy(true);
    try {
      const res = await fetch(`${API_BASE}/api/auth/sso/discover`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim() }),
      });
      const data = res.ok ? await res.json() : null;
      if (!res.ok) {
        setMessage({ tone: "error", text: res.status === 429
          ? "Too many attempts. Please wait a minute and try again."
          : "We couldn't check that email. Please try again." });
      } else if (data.sso && data.login_url) {
        setMessage({ tone: "info", text: "Your organization uses single sign-on. Taking you to its sign-in page…" });
        window.location.assign(data.login_url);
        return;
      } else if (mode === "register") {
        setMessage({
          tone: "info",
          text: "Company SSO is set up by an administrator after your organization's account exists. "
            + "Create the account with your work email or another option above, then your IT team can connect SSO.",
        });
      } else {
        setMessage({
          tone: "info",
          text: "Single sign-on isn't set up for this email's organization. Sign in with your email and password, "
            + "or ask your administrator.",
        });
      }
    } catch {
      setMessage({ tone: "error", text: "We couldn't check that email. Please try again." });
    }
    setBusy(false);
  }

  return (
    <form onSubmit={discover} noValidate className="mt-2 rounded-lg border border-slate-200 bg-slate-50 p-3">
      <label htmlFor={inputId} className="mb-1.5 block text-[13px] font-semibold text-slate-800">
        Work email for Company SSO
      </label>
      <div className="flex gap-2">
        <input
          id={inputId} type="email" autoComplete="email" value={email} autoFocus
          onChange={(e) => setEmail(e.target.value)} placeholder="name@company.com"
          className="h-10 min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 text-[14px] text-slate-900 outline-none focus:border-blue-600 focus:ring-2 focus:ring-blue-600/15"
        />
        <button type="submit" disabled={busy}
          className="inline-flex h-10 shrink-0 items-center gap-1.5 rounded-lg bg-[#1260e6] px-4 text-[14px] font-semibold text-white hover:bg-[#0e52c7] disabled:bg-blue-300">
          {busy ? <Loader2 size={16} className="animate-spin" aria-hidden="true" /> : <ArrowRight size={16} aria-hidden="true" />}
          Continue
        </button>
      </div>
      {message && (
        <p role={message.tone === "error" ? "alert" : "status"}
          className={`mt-2 text-[13px] leading-snug ${message.tone === "error" ? "text-red-600" : "text-slate-700"}`}>
          {message.text}
        </p>
      )}
      <button type="button" onClick={onClose} className="mt-2 text-[12px] font-medium text-slate-500 hover:text-slate-800">
        Cancel
      </button>
    </form>
  );
}

export default function SocialSignInButtons({ mode = "login", compact = false }) {
  const [status, setStatus] = useState(DEFAULT_STATUS);
  const [notice, setNotice] = useState(null);
  const [ssoOpen, setSsoOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    loadProviderStatus().then((s) => { if (!cancelled) setStatus(s); });
    return () => { cancelled = true; };
  }, []);

  function start(provider) {
    setNotice(null);
    if (provider.key === "sso") {
      setSsoOpen((open) => !open);
      return;
    }
    if (!status[provider.key]) {
      setNotice(`${provider.name} sign-in isn't available yet. Please use your work email${
        mode === "register" ? " to create your account" : ""} instead.`);
      return;
    }
    window.location.assign(`${API_BASE}/api/auth/${provider.key}/${mode === "register" ? "register" : "login"}`);
  }

  const shown = SOCIAL_PROVIDERS.filter((provider) => provider.key !== "sso" || status.sso);

  return (
    <div>
      <div className={compact ? `grid gap-2 sm:grid-cols-2 ${shown.length === 3 ? "xl:grid-cols-3" : ""}` : "grid gap-2"}>
        {shown.map((provider) => {
          const Icon = provider.icon;
          const available = Boolean(status[provider.key]);
          return (
            <button
              key={provider.key}
              type="button"
              onClick={() => start(provider)}
              aria-disabled={available ? undefined : "true"}
              aria-expanded={provider.key === "sso" ? ssoOpen : undefined}
              title={available ? undefined : "Not available yet"}
              className={`flex w-full items-center gap-3 rounded-lg border border-slate-200 bg-white px-4 text-left text-[14px] font-medium text-slate-800 transition-colors hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600 ${
                compact ? "h-10" : "py-2.5"} ${available ? "" : "opacity-60"}`}
            >
              <Icon />
              <span className="min-w-0 flex-1 truncate">{provider.label}</span>
              <ChevronRight size={16} className="shrink-0 text-slate-500" aria-hidden="true" />
            </button>
          );
        })}
      </div>
      {ssoOpen && status.sso && <CompanySsoPanel mode={mode} onClose={() => setSsoOpen(false)} />}
      {notice && (
        <p role="status" className="mt-2 rounded-lg bg-blue-50 px-3 py-2 text-[13px] text-blue-800">{notice}</p>
      )}
    </div>
  );
}
