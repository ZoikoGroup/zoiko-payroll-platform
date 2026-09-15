import { useState, useEffect, useMemo } from "react";
import { useNavigate } from "react-router-dom";
import { HeartHandshake, ExternalLink } from "lucide-react";
import { getCanonicalContributionRates } from "../../../service/superAdminService";

// A DEDICATED, cross-state overview of every state's paid-leave/SDI/TDI-
// style statutory program (ZP-TAX-US-2026-001 §5/§11.1, gap-closure Plan
// Phase 4, 2026-09-14) — previously these rows were only ever visible one
// state at a time, buried inside that state's own Tax Components tab
// alongside its ordinary income-tax brackets, with no single place to see
// "which states have which program configured" at a glance. Read-only by
// design: editing still happens in the state's own pack (Federal/State-
// District), reached via the "Edit in <state>" link — this panel reuses
// the EXACT SAME canonical-contribution-rate data (list_canonical_
// contribution_rates(country="US")), not a separate/duplicated store, so
// it can never drift out of sync with what Tax Components actually shows.

// Primary program component_keys (their own "_wage_cap"/"_annual_max"/
// "_employer_headcount_min/_max" companion rows are attached inline
// rather than listed as their own row — same merge convention
// usaComponentConfig.js's associatedKey already uses for the per-pack view).
const PROGRAM_KEYS = [
  "sdi", "paid_leave", "paid_leave_parental", "tdi", "wa_cares",
  "worker_ui", "worker_di", "workforce_dev", "fli", "famli", "ma_pfml", "pfml", "vt_ccc",
];
const PROGRAM_LABELS = {
  sdi: "State Disability Insurance (SDI)",
  paid_leave: "Paid Leave",
  paid_leave_parental: "Paid Leave (Parental Tier)",
  tdi: "Temporary Disability Insurance (TDI)",
  wa_cares: "WA Cares Fund",
  worker_ui: "Worker Unemployment Insurance",
  worker_di: "Worker Disability Insurance",
  workforce_dev: "Workforce Development",
  fli: "Family Leave Insurance",
  famli: "Family & Medical Leave Insurance (FAMLI)",
  ma_pfml: "Paid Family & Medical Leave (MA)",
  pfml: "Paid Family & Medical Leave",
  vt_ccc: "Child Care Contribution",
};

function fmtPct(v) {
  return v != null ? `${v}%` : "—";
}
function fmtAmount(v) {
  return v != null ? `$${Number(v).toLocaleString()}` : "—";
}

export default function USASpecialProgramsPanel({ onNavigateToState }) {
  const navigate = useNavigate();
  const [rates, setRates] = useState(null);

  useEffect(() => {
    getCanonicalContributionRates({ country: "US" }).then(setRates).catch(() => setRates([]));
  }, []);

  const rows = useMemo(() => {
    if (!rates) return [];
    const byState = new Map();
    for (const r of rates) {
      const isCompanion = /_(wage_cap|annual_max|employer_headcount_min|employer_headcount_max)$/.test(r.componentKey || "");
      const baseKey = isCompanion ? r.componentKey.replace(/_(wage_cap|annual_max|employer_headcount_min|employer_headcount_max)$/, "") : r.componentKey;
      if (!PROGRAM_KEYS.includes(baseKey) || !r.jurisdictionState) continue;
      const groupKey = `${r.jurisdictionState}::${baseKey}`;
      if (!byState.has(groupKey)) {
        byState.set(groupKey, { state: r.jurisdictionState, componentKey: baseKey, primary: null, wageCap: null, annualMax: null, headcountMin: null });
      }
      const entry = byState.get(groupKey);
      if (!isCompanion) entry.primary = r;
      else if (r.componentKey.endsWith("_wage_cap")) entry.wageCap = r.flatAmount;
      else if (r.componentKey.endsWith("_annual_max")) entry.annualMax = r.flatAmount;
      else if (r.componentKey.endsWith("_employer_headcount_min")) entry.headcountMin = r.flatAmount;
    }
    return Array.from(byState.values())
      .filter((e) => e.primary)
      .sort((a, b) => a.state.localeCompare(b.state) || a.componentKey.localeCompare(b.componentKey));
  }, [rates]);

  function goToState(state) {
    if (onNavigateToState) onNavigateToState(state);
    else navigate(`/super-admin/compliance/united-states/${encodeURIComponent(state)}?section=stateDistrict`);
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4 flex items-center gap-2">
        <HeartHandshake size={18} className="text-primary" />
        <div>
          <h2 className="text-lg font-bold text-foreground">Special Programs</h2>
          <p className="mt-0.5 text-xs text-foreground-muted">
            Every state's paid-leave/SDI/TDI-style statutory program, in one place — read-only here; edit in the
            state's own Federal/State-District pack.
          </p>
        </div>
      </div>

      {rates === null ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : rows.length === 0 ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">No special programs configured yet.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border-light">
          <table className="w-full text-xs">
            <thead className="bg-surface-muted text-foreground-muted">
              <tr>
                <th className="px-3 py-2 text-left">State</th>
                <th className="px-3 py-2 text-left">Program</th>
                <th className="px-3 py-2 text-right">Employee %</th>
                <th className="px-3 py-2 text-right">Employer %</th>
                <th className="px-3 py-2 text-right">Wage Cap</th>
                <th className="px-3 py-2 text-right">Annual Max</th>
                <th className="px-3 py-2 text-right">Employer Headcount Min</th>
                <th className="px-3 py-2" />
              </tr>
            </thead>
            <tbody>
              {rows.map((e) => (
                <tr key={`${e.state}-${e.componentKey}`} className="border-t border-border-light">
                  <td className="px-3 py-2 font-mono font-medium text-foreground">{e.state}</td>
                  <td className="px-3 py-2">{PROGRAM_LABELS[e.componentKey] || e.componentKey}</td>
                  <td className="px-3 py-2 text-right">{fmtPct(e.primary.employeeRatePct)}</td>
                  <td className="px-3 py-2 text-right">{fmtPct(e.primary.employerRatePct)}</td>
                  <td className="px-3 py-2 text-right">{fmtAmount(e.wageCap)}</td>
                  <td className="px-3 py-2 text-right">{fmtAmount(e.annualMax)}</td>
                  <td className="px-3 py-2 text-right">{e.headcountMin ?? "—"}</td>
                  <td className="px-3 py-2 text-right">
                    <button onClick={() => goToState(e.state)} className="inline-flex items-center gap-1 font-semibold text-primary hover:underline">
                      Edit in {e.state} <ExternalLink size={11} />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
