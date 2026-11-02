import { BarChart3, Globe2, ShieldCheck, Users } from "lucide-react";
import { Link } from "react-router-dom";

// Brand hero for the sign-in card. Every word is real text (sharp at any
// size, readable by assistive tech); only the globe / device scene is art:
// public/auth/login-hero.webp, the designer's export (no text baked in; its
// dark upper-left is where the headline sits).
const HERO_ARTWORK = "/auth/login-hero.webp";

const FEATURES = [
  { icon: Globe2, label: "Multi-jurisdiction payroll" },
  { icon: Users, label: "Automated tax & compliance" },
  { icon: BarChart3, label: "Employee self-service" },
  { icon: ShieldCheck, label: "Secure, scalable and trusted" },
];

const STRIP = ["PEOPLE", "PAYROLL", "COMPLIANCE", "INSIGHTS", "SECURITY"];

export default function AuthHero() {
  return (
    <aside className="relative hidden w-[54%] shrink-0 overflow-hidden bg-[radial-gradient(120%_90%_at_80%_25%,#1a6cf0_0%,#0a3fa8_45%,#06215f_100%)] text-white lg:flex lg:flex-col">
      <img
        src={HERO_ARTWORK} alt="" aria-hidden="true" decoding="async"
        className="pointer-events-none absolute inset-0 h-full w-full object-cover object-bottom"
      />

      <div className="relative z-10 flex flex-1 flex-col px-12 pt-7">
        <Link to="/" aria-label="Zoiko Payroll home" className="w-fit">
          <img src="/zoikopayroll-logo-light.png" alt="Zoiko Payroll" className="h-12 w-auto" />
        </Link>

        <h1 className="mt-6 text-[42px] font-extrabold leading-[1.08] tracking-[-0.02em] [text-shadow:0_2px_18px_rgba(4,26,74,0.55)]">
          Global payroll.
          <br />
          <span className="text-[#29b6ff]">Local compliance.</span>
          <br />
          Total confidence.
        </h1>
        <p className="mt-5 max-w-sm text-[17px] leading-snug text-white/90">
          Accurate payroll. Compliant everywhere.
          <br />
          Built for a global workforce.
        </p>

        <ul className="mt-4 space-y-2">
          {FEATURES.map(({ icon: Icon, label }) => (
            <li key={label} className="flex items-center gap-3 text-[14px] font-semibold">
              <span className="flex h-8 w-8 items-center justify-center rounded-full border border-white/40 bg-white/10">
                <Icon size={15} />
              </span>
              {label}
            </li>
          ))}
        </ul>
      </div>

      <div className="relative z-10 flex items-center justify-center gap-4 bg-gradient-to-t from-[#041a4a]/90 to-transparent px-8 pb-5 pt-10 text-[13px] font-semibold tracking-[0.08em] text-white/90">
        {STRIP.map((word, i) => (
          <span key={word} className="flex items-center gap-4">
            {i > 0 && <span className="text-white/50">/</span>}
            {word}
          </span>
        ))}
      </div>
    </aside>
  );
}
