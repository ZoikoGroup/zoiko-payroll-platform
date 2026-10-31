import { Globe2, Landmark, ShieldCheck, Users, Zap } from "lucide-react";

import { REGISTRATION_COUNTRIES } from "../../utils/registrationRegions";

// Brand panel for the create-account page. Every figure is derived from the
// platform itself (the country count is the live registration list) - no
// marketing claim is hard-coded here that the product cannot back up.
// Swap REGISTER_HERO_ARTWORK for the designer's sign-up export when it is
// added to public/auth/ (until then it shares the sign-in artwork).
const REGISTER_HERO_ARTWORK = "/auth/login-hero.webp";

const COUNTRY_COUNT = REGISTRATION_COUNTRIES.length;

const FEATURES = [
  { icon: Globe2, title: "Global compliance", text: `Local payroll, taxes and filings in ${COUNTRY_COUNT} countries.` },
  { icon: Zap, title: "Accurate and automated", text: "Pay runs, statutory rates and payslips — done right." },
  { icon: ShieldCheck, title: "Secure and reliable", text: "Enterprise-grade security and data privacy." },
  { icon: Users, title: "Built for global teams", text: "From startups to global enterprises." },
];

const STATS = [
  { icon: Globe2, value: String(COUNTRY_COUNT), label: "Countries" },
  { icon: ShieldCheck, value: "MFA", label: "Protected admin sign-in" },
  { icon: Landmark, value: "Enterprise", label: "Security" },
];

export default function SignupHero() {
  return (
    <aside className="relative hidden w-[47%] shrink-0 overflow-hidden rounded-2xl lg:min-h-[760px] bg-[radial-gradient(120%_90%_at_80%_25%,#1a6cf0_0%,#0a3fa8_45%,#06215f_100%)] text-white lg:flex lg:flex-col">
      <img
        src={REGISTER_HERO_ARTWORK} alt="" aria-hidden="true" decoding="async"
        className="pointer-events-none absolute inset-0 h-full w-full object-cover object-bottom opacity-90"
      />
      <div className="relative z-10 flex flex-1 flex-col px-10 pt-10">
        <p className="text-[12px] font-semibold uppercase tracking-[0.22em] text-[#5cc4ff]">Global payroll platform</p>
        <h1 className="mt-4 text-[44px] font-extrabold leading-[1.06] tracking-[-0.02em] [text-shadow:0_2px_18px_rgba(4,26,74,0.55)]">
          Payroll for a
          <br />
          <span className="text-[#29b6ff]">borderless world.</span>
        </h1>
        <p className="mt-4 max-w-sm text-[16px] leading-snug text-white/90">
          Run payroll, stay compliant and take care of your people in {COUNTRY_COUNT} countries — from one secure
          platform.
        </p>

        <ul className="mt-6 space-y-4">
          {FEATURES.map(({ icon: Icon, title, text }) => (
            <li key={title} className="flex items-start gap-3.5">
              <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-full bg-[#1260e6] shadow-[0_6px_16px_-6px_rgba(18,96,230,0.9)]">
                <Icon size={19} />
              </span>
              <span>
                <span className="block text-[15px] font-semibold">{title}</span>
                <span className="block max-w-[15rem] text-[13px] leading-snug text-white/80">{text}</span>
              </span>
            </li>
          ))}
        </ul>
      </div>

      <div className="relative z-10 grid grid-cols-3 divide-x divide-white/15 bg-gradient-to-t from-[#041a4a]/95 to-[#041a4a]/40 px-6 py-5">
        {STATS.map(({ icon: Icon, value, label }) => (
          <div key={label} className="flex items-center justify-center gap-3 px-2">
            <Icon size={26} className="shrink-0 text-white/90" />
            <span>
              <span className="block text-[17px] font-bold leading-tight">{value}</span>
              <span className="block text-[12px] text-white/75">{label}</span>
            </span>
          </div>
        ))}
      </div>
    </aside>
  );
}
