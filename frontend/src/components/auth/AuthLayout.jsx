import { Link, NavLink, useLocation } from "react-router-dom";

import AuthHero from "./AuthHero";

// Shared sign-in shell for /login, /register, /forgot-password and
// /reset-password: one card
// with the brand hero on the left and the tabbed form panel on the right.
// The hero hides below the lg breakpoint, and `wide` drops it entirely so the
// Register plan picker keeps its room. Always light: the public auth pages do
// not follow the in-app dark theme.

// Fill these with the published policy pages; until then they point at the
// Zoiko One site, the only public URL the app already links to.
export const AUTH_FOOTER_LINKS = [
  { label: "Privacy", href: "https://zoikoone.com" },
  { label: "Terms", href: "https://zoikoone.com" },
  { label: "Accessibility", href: "https://zoikoone.com" },
  { label: "Help", href: "https://zoikoone.com" },
];

// `also` lists other routes that belong to the same tab (the emailed
// set-new-password link lives under Reset Password).
const TABS = [
  { to: "/login", label: "Login" },
  { to: "/register", label: "Register" },
  { to: "/forgot-password", label: "Reset Password", also: ["/reset-password"] },
];

function Tabs() {
  const { pathname } = useLocation();
  return (
    <nav className="grid grid-cols-3 border-b border-slate-200" aria-label="Account">
      {TABS.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          className={({ isActive: exact }) => {
            const isActive = exact || (tab.also || []).includes(pathname);
            return `relative px-2 py-3.5 text-center text-[15px] font-medium transition-colors focus-visible:outline-2 focus-visible:outline-offset-[-2px] focus-visible:outline-blue-600 ${
              isActive
                ? "text-slate-900 after:absolute after:inset-x-4 after:bottom-[-1px] after:h-[3px] after:rounded-full after:bg-blue-600"
                : "text-slate-600 hover:text-slate-900"
            }`;
          }}
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}

function CardFooter() {
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 border-t border-slate-100 px-6 py-4 text-xs text-slate-500">
      <div className="flex flex-wrap items-center gap-x-2 gap-y-1">
        {AUTH_FOOTER_LINKS.map((link, i) => (
          <span key={link.label} className="flex items-center gap-2">
            {i > 0 && <span aria-hidden="true">•</span>}
            <a href={link.href} target="_blank" rel="noopener noreferrer" className="hover:text-slate-800">
              {link.label}
            </a>
          </span>
        ))}
      </div>
      <span>© {new Date().getFullYear()} Zoiko Tech Inc.</span>
    </div>
  );
}

export default function AuthLayout({ children, wide = false }) {
  return (
    <div className="min-h-screen bg-[#eef3f9] font-[Inter,-apple-system,BlinkMacSystemFont,sans-serif] text-slate-900 lg:flex lg:items-center lg:justify-center lg:p-8">
      <div
        className={`mx-auto flex w-full overflow-hidden bg-white lg:min-h-[800px] lg:rounded-2xl lg:shadow-[0_24px_60px_-20px_rgba(15,23,42,0.35)] ${
          wide ? "max-w-[1100px]" : "max-w-[1280px]"
        }`}
      >
        {!wide && <AuthHero />}
        <div className={`flex w-full flex-col ${wide ? "" : "lg:w-[46%] lg:shrink-0"}`}>
          {wide && (
            <div className="flex items-center justify-between px-6 pt-5">
              <Link to="/" aria-label="Zoiko Payroll home">
                <img src="/zoikopayroll-logo.png" alt="Zoiko Payroll" className="h-9 w-auto" />
              </Link>
            </div>
          )}
          <div className="px-4 pt-4 sm:px-6">
            {!wide && (
              <div className="mb-2 flex justify-center lg:hidden">
                <Link to="/" aria-label="Zoiko Payroll home">
                  <img src="/zoikopayroll-logo.png" alt="Zoiko Payroll" className="h-9 w-auto" />
                </Link>
              </div>
            )}
            <Tabs />
          </div>
          <main className="flex-1 px-6 py-6 sm:px-10">{children}</main>
          <CardFooter />
        </div>
      </div>
    </div>
  );
}
