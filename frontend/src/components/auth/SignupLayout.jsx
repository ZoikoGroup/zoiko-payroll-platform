import { Link } from "react-router-dom";

import SignupHero from "./SignupHero";

// Create-account shell: logo and "Already have an account? Log in" header,
// the brand panel on the left and the form card on the right. Always light,
// like the sign-in pages.
//
// From the lg breakpoint the page is locked to the viewport: the brand panel
// keeps the full height (its width follows from the artwork's proportions)
// and never moves, and only the card's body scrolls when a step is taller
// than the screen. `footer` (the step's Back / Continue buttons) stays pinned
// to the bottom of the card. Below lg the panel is hidden, the card is full
// width, the page scrolls normally and the footer sticks to the viewport's
// bottom edge.
export default function SignupLayout({ children, footer = null }) {
  return (
    <div className="flex min-h-dvh flex-col bg-[#eef3f9] font-[Inter,-apple-system,BlinkMacSystemFont,sans-serif] text-slate-900 lg:h-dvh lg:overflow-hidden">
      <header className="mx-auto flex w-full max-w-[1440px] shrink-0 items-center justify-between px-4 py-3 sm:px-6">
        <Link to="/" aria-label="Zoiko Payroll home">
          <img src="/zoikopayroll-logo.png" alt="Zoiko Payroll" className="h-10 w-auto sm:h-11" />
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
      <div className="mx-auto flex w-full max-w-[1440px] flex-1 gap-5 px-4 pb-4 sm:px-6 lg:min-h-0 lg:pb-5">
        <SignupHero />
        <main className="flex w-full min-w-0 flex-col rounded-2xl border border-slate-200 bg-white shadow-[0_24px_60px_-28px_rgba(15,23,42,0.35)] lg:min-h-0 lg:flex-1">
          <div id="register-scroll" className="min-h-0 flex-1 px-4 py-5 sm:px-7 lg:overflow-y-auto">
            {children}
          </div>
          {footer && (
            <div className="sticky bottom-0 z-10 rounded-b-2xl border-t border-slate-200 bg-white px-4 py-2.5 sm:px-7 lg:static">
              {footer}
            </div>
          )}
        </main>
      </div>
    </div>
  );
}
