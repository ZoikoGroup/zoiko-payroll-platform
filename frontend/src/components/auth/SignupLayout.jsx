import { Link } from "react-router-dom";

import SignupHero from "./SignupHero";

// Create-account shell: logo and "Already have an account? Log in" header,
// the brand panel on the left and the form card on the right. Always light,
// like the sign-in pages. The panel hides below the lg breakpoint.
export default function SignupLayout({ children }) {
  return (
    <div className="min-h-screen bg-[#eef3f9] font-[Inter,-apple-system,BlinkMacSystemFont,sans-serif] text-slate-900">
      <header className="mx-auto flex max-w-[1440px] items-center justify-between px-4 py-4 sm:px-6">
        <Link to="/" aria-label="Zoiko Payroll home">
          <img src="/zoikopayroll-logo.png" alt="Zoiko Payroll" className="h-11 w-auto" />
        </Link>
        <div className="flex items-center gap-4 text-[14px] text-slate-700">
          <span className="hidden sm:inline">Already have an account?</span>
          <Link
            to="/login"
            className="rounded-lg border border-blue-600 px-5 py-2 font-semibold text-blue-700 transition-colors hover:bg-blue-50"
          >
            Log in
          </Link>
        </div>
      </header>
      <div className="mx-auto flex max-w-[1440px] gap-5 px-4 pb-8 sm:px-6">
        <SignupHero />
        <main className="w-full min-w-0 rounded-2xl border border-slate-200 bg-white p-5 shadow-[0_24px_60px_-28px_rgba(15,23,42,0.35)] sm:p-7 lg:w-[53%]">
          {children}
        </main>
      </div>
    </div>
  );
}
