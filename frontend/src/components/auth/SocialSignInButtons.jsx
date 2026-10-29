import { useState } from "react";
import { Building2, ChevronRight } from "lucide-react";

// Provider sign-in buttons from the sign-in design. There is no Microsoft /
// Google / Apple / company-SSO backend yet, so they are announced as coming
// soon instead of pretending to work; wire `onSelect` when one exists.

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

const PROVIDERS = [
  { key: "microsoft", label: "Continue with Microsoft", icon: MicrosoftIcon },
  { key: "google", label: "Continue with Google", icon: GoogleIcon },
  { key: "apple", label: "Continue with Apple", icon: AppleIcon },
  { key: "sso", label: "Continue with Company SSO", icon: () => <Building2 size={20} className="text-slate-700" /> },
];

export default function SocialSignInButtons() {
  const [notice, setNotice] = useState(false);

  return (
    <div>
      <div className="space-y-2">
        {PROVIDERS.map(({ key, label, icon: Icon }) => (
          <button
            key={key}
            type="button"
            aria-disabled="true"
            title="Coming soon"
            onClick={() => setNotice(true)}
            className="flex w-full items-center gap-4 rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-left text-[14px] font-medium text-slate-800 transition-colors hover:border-slate-300 hover:bg-slate-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
          >
            <Icon />
            <span className="flex-1">{label}</span>
            <ChevronRight size={16} className="text-slate-500" />
          </button>
        ))}
      </div>
      {notice && (
        <p role="status" className="mt-3 rounded-lg bg-blue-50 px-3 py-2 text-sm text-blue-800">
          Single sign-on is coming soon. Please sign in with your work email for now.
        </p>
      )}
    </div>
  );
}
