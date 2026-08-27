import { ArrowRight } from "lucide-react";
import { Link } from "react-router-dom";

export default function LandingHeader() {
  return (
    <header className="sticky top-0 z-50 bg-gradient-to-b from-primary-light to-white border-b border-border-light shadow-[0_1px_0_rgba(30,27,75,0.03)] rounded-b-xl">
      <div className="mx-auto flex max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8 h-16">
        <Link
          to="/"
          className="flex items-center gap-2 shrink-0 no-underline rounded-lg focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
        >
          <img src="/zoikopayroll-logo.png" alt="Zoiko Payroll" className="h-10 w-auto object-contain" />
        </Link>

        <div className="flex items-center gap-2 sm:gap-3 text-sm font-semibold">
          <Link
            to="/login"
            className="text-foreground no-underline whitespace-nowrap rounded-full px-4 py-2.5 transition-colors duration-150 hover:bg-brand-navy/[0.06] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-focus-ring"
          >
            Sign In
          </Link>
          <Link
            to="/register"
            className="inline-flex items-center gap-1 bg-primary hover:bg-primary-hover text-white rounded-full px-5 py-2.5 shadow-md shadow-primary/20 transition-all duration-200 no-underline whitespace-nowrap focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-brand-navy"
          >
            Create your account <ArrowRight size={15} />
          </Link>
        </div>
      </div>
    </header>
  );
}
