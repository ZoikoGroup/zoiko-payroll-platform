import { BarChart3, Globe2, ShieldCheck, Users } from "lucide-react";
import { Link } from "react-router-dom";

// Brand hero for the sign-in card. Every word is real text (sharp at any
// size, readable by assistive tech); only the globe / device scene is art.
// Set HERO_ARTWORK to the designer's export (e.g. "/auth/login-hero.webp" in
// public/) to replace the drawn placeholder scene.
const HERO_ARTWORK = null;

const FEATURES = [
  { icon: Globe2, label: "Multi-jurisdiction payroll" },
  { icon: Users, label: "Automated tax & compliance" },
  { icon: BarChart3, label: "Employee self-service" },
  { icon: ShieldCheck, label: "Secure, scalable and trusted" },
];

const STRIP = ["PEOPLE", "PAYROLL", "COMPLIANCE", "INSIGHTS", "SECURITY"];

function PlaceholderScene() {
  // A lit globe with meridians and city lights, and a laptop + phone showing
  // a payroll overview — drawn, so it stays crisp until the artwork lands.
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden="true">
      <svg className="absolute -right-28 -top-10 h-[470px] w-[470px] opacity-80" viewBox="0 0 400 400">
        <defs>
          <radialGradient id="zp-globe" cx="38%" cy="35%" r="70%">
            <stop offset="0%" stopColor="#3b9cff" stopOpacity="0.95" />
            <stop offset="55%" stopColor="#0b4fb3" stopOpacity="0.9" />
            <stop offset="100%" stopColor="#04225c" stopOpacity="0.95" />
          </radialGradient>
          <radialGradient id="zp-glow" cx="50%" cy="50%" r="50%">
            <stop offset="70%" stopColor="#5ab4ff" stopOpacity="0" />
            <stop offset="100%" stopColor="#7cc4ff" stopOpacity="0.55" />
          </radialGradient>
        </defs>
        <circle cx="200" cy="200" r="190" fill="url(#zp-glow)" />
        <circle cx="200" cy="200" r="170" fill="url(#zp-globe)" />
        <g fill="none" stroke="#9fd2ff" strokeOpacity="0.35" strokeWidth="0.8">
          {[30, 60, 90, 120, 150].map((rx) => <ellipse key={rx} cx="200" cy="200" rx={rx} ry="170" />)}
          {[-120, -60, 0, 60, 120].map((dy) => (
            <ellipse key={dy} cx="200" cy={200 + dy} rx={Math.sqrt(170 * 170 - dy * dy)} ry={Math.max(6, 28 - Math.abs(dy) / 6)} />
          ))}
        </g>
        <g fill="#e3f2ff">
          {[[150, 140], [172, 152], [210, 128], [236, 170], [258, 196], [182, 214], [140, 236], [226, 246], [268, 120], [120, 182], [292, 228], [200, 290]].map(([x, y]) => (
            <circle key={`${x}-${y}`} cx={x} cy={y} r="2.2" />
          ))}
        </g>
        <g fill="none" stroke="#bfe3ff" strokeOpacity="0.55" strokeWidth="1">
          <path d="M150 140 Q 200 90 268 120" />
          <path d="M172 152 Q 230 150 258 196" />
          <path d="M120 182 Q 160 230 226 246" />
          <path d="M182 214 Q 250 200 292 228" />
        </g>
      </svg>

      {/* Laptop */}
      <div className="absolute bottom-[72px] right-6 w-[330px] rotate-[-3deg]">
        <div className="rounded-t-xl border-[6px] border-slate-900 bg-white p-2 shadow-2xl">
          <div className="flex gap-2">
            <div className="w-16 space-y-1.5 rounded bg-[#0b2a5b] p-1.5">
              <div className="h-2 w-10 rounded bg-white/80" />
              {[0, 1, 2, 3, 4, 5].map((i) => <div key={i} className="h-1.5 w-11 rounded bg-white/30" />)}
            </div>
            <div className="flex-1 space-y-1.5">
              <div className="h-2 w-24 rounded bg-slate-800" />
              <div className="grid grid-cols-4 gap-1">
                {["124", "3", "1", "0"].map((n) => (
                  <div key={n} className="rounded border border-slate-200 p-1 text-[8px] font-bold text-slate-800">{n}</div>
                ))}
              </div>
              <div className="flex h-12 items-end gap-1 rounded border border-slate-200 p-1">
                {[30, 42, 50, 46, 70, 56, 62, 80, 74].map((h, i) => (
                  <div key={i} className="flex-1 rounded-sm bg-blue-600" style={{ height: `${h}%` }} />
                ))}
              </div>
              <div className="space-y-1 rounded border border-slate-200 p-1">
                {[0, 1, 2].map((i) => <div key={i} className="h-1.5 rounded bg-slate-200" />)}
              </div>
            </div>
          </div>
        </div>
        <div className="mx-auto h-3 w-[110%] -translate-x-[4.5%] rounded-b-xl bg-gradient-to-b from-slate-300 to-slate-500" />
      </div>

      {/* Phone */}
      <div className="absolute bottom-[64px] left-10 w-[118px] rotate-[-2deg] rounded-[22px] border-[5px] border-slate-900 bg-white p-2 shadow-2xl">
        <div className="mx-auto mb-2 h-1.5 w-10 rounded-full bg-slate-900" />
        <div className="h-2 w-12 rounded bg-slate-800" />
        <div className="mt-2 rounded border border-slate-200 p-1.5">
          <div className="text-[7px] text-slate-500">This month</div>
          <div className="text-[11px] font-bold text-slate-900">$162,580</div>
        </div>
        <div className="mt-1.5 space-y-1">
          {[0, 1, 2, 3].map((i) => <div key={i} className="h-2 rounded bg-slate-100" />)}
        </div>
      </div>
    </div>
  );
}

export default function AuthHero() {
  return (
    <aside className="relative hidden w-[54%] shrink-0 overflow-hidden bg-[radial-gradient(120%_90%_at_80%_25%,#1a6cf0_0%,#0a3fa8_45%,#06215f_100%)] text-white lg:flex lg:flex-col">
      {HERO_ARTWORK ? (
        <img src={HERO_ARTWORK} alt="" aria-hidden="true" className="pointer-events-none absolute inset-0 h-full w-full object-cover" />
      ) : (
        <PlaceholderScene />
      )}

      <div className="relative z-10 flex flex-1 flex-col px-12 pt-9">
        <Link to="/" aria-label="Zoiko Payroll home" className="w-fit">
          <img src="/zoikopayroll-logo-light.png" alt="Zoiko Payroll" className="h-12 w-auto" />
        </Link>

        <h1 className="mt-8 text-[42px] font-extrabold leading-[1.08] tracking-[-0.02em] [text-shadow:0_2px_18px_rgba(4,26,74,0.55)]">
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

        <ul className="mt-5 space-y-2.5">
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
