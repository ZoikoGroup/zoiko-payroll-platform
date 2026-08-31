import { useState, useEffect, useMemo } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Info, AlertTriangle, Globe2 } from "lucide-react";
import { getEngineFallbackDefaults } from "../service/superAdminService";
import CountryFlag from "../components/jurisdiction/CountryFlag";

// Super Admin > Compliance > Engine Fallback Defaults
// -----------------------------------------------------------------------
// Read-only viewer for the two layers of hardcoded fallback values the
// payroll engine uses when no canonical/org rate exists — closes the "why
// can't I see this in Compliance" confusion this whole page exists to
// resolve. Nothing here is editable: no inputs, no save buttons. The data
// comes from backend/app/modules/payroll/engine/fallback_registry.py,
// which reads every engine constant LIVE via getattr() — this page can
// never show a stale value even if the underlying constant changes.
const COUNTRIES = [
  { code: "IN", name: "India" },
  { code: "US", name: "United States" },
  { code: "UK", name: "United Kingdom" },
  { code: "AU", name: "Australia" },
  { code: "CA", name: "Canada" },
  { code: "DE", name: "Germany" },
];

function toNumber(v) {
  if (v === null || v === undefined || v === "") return null;
  const n = Number(v);
  return Number.isNaN(n) ? null : n;
}

// Finds the seeded ContributionRate row (if any) matching an engine
// constant's resolverKey, and picks which of its fields to compare against
// using `side` where the constant disambiguates it (UK's employee vs
// employer National Insurance rate share one resolverKey but are genuinely
// different numbers) — otherwise prefers whichever field is actually set.
function findDiscrepancy(constant, seededRatesForCountry) {
  if (constant.skipDiscrepancyCheck || constant.kind !== "scalar") return null;
  const row = (seededRatesForCountry || []).find((r) => r.componentKey === constant.resolverKey);
  if (!row) return { kind: "no-seed-row" };

  let seedValue;
  if (constant.side === "employee") seedValue = row.employeeRatePct;
  else if (constant.side === "employer") seedValue = row.employerRatePct;
  else seedValue = row.flatAmount ?? row.employeeRatePct ?? row.employerRatePct;

  const engineNum = toNumber(constant.value);
  const seedNum = toNumber(seedValue);
  if (engineNum === null || seedNum === null) return null;
  if (engineNum !== seedNum) return { kind: "mismatch", seedValue: seedNum, engineValue: engineNum };
  return null;
}

export default function EngineFallbackDefaultsPage() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [country, setCountry] = useState("IN");

  useEffect(() => {
    getEngineFallbackDefaults().then(setData).finally(() => setLoading(false));
  }, []);

  const seededRates = data?.seeded?.contributionRates?.[country] || [];
  const seededSlabs = data?.seeded?.taxSlabs?.[country] || [];
  const engineConstants = useMemo(
    () => (data?.engineConstants || []).filter((c) => c.country === country),
    [data, country]
  );

  return (
    <div>
      <div className="mb-6">
        <Link to="/super-admin/compliance" className="mb-2 flex items-center gap-1 text-xs font-semibold text-foreground-muted hover:text-foreground">
          <ArrowLeft size={14} /> Back to Compliance
        </Link>
        <h1 className="text-2xl font-bold text-foreground">Engine Fallback Defaults</h1>
        <p className="text-sm text-foreground-muted mt-0.5">
          Every hardcoded value the payroll engine falls back to when no canonical or organization rate exists — for visibility only.
        </p>
      </div>

      <div className="mb-5 flex items-start gap-2 rounded-xl border border-info/20 bg-info/5 px-4 py-3">
        <Info size={15} className="mt-0.5 shrink-0 text-info" />
        <p className="text-xs text-foreground-secondary">
          <strong>Read-only.</strong> Nothing on this page can be edited here. "Seedable Defaults" become real, Super-Admin-editable rows in Compliance the first time an organization uses that jurisdiction. "Engine-Only Constants" have no database row at all today — changing one requires an engineering change, not a Compliance edit.
        </p>
      </div>

      <div className="mb-5 flex flex-wrap items-center gap-1 rounded-lg border border-border bg-surface-muted p-1 w-fit">
        {COUNTRIES.map((c) => (
          <button
            key={c.code}
            onClick={() => setCountry(c.code)}
            className={`flex items-center gap-1.5 rounded-md px-3 py-1.5 text-xs font-semibold transition-colors ${
              country === c.code ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"
            }`}
          >
            <span className="flex h-4 w-4 items-center justify-center overflow-hidden rounded-sm">
              <CountryFlag code={c.code} className="h-full w-full" fallback={<Globe2 size={12} />} />
            </span>
            {c.name}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="py-12 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : (
        <div className="space-y-5">
          <div className="rounded-xl border border-border bg-surface p-5">
            <h3 className="mb-1 text-sm font-bold text-foreground">Seedable Defaults</h3>
            <p className="mb-4 text-xs text-foreground-muted">
              Becomes a real, Super-Admin-editable Contribution Rate / Tax Slab row the first time an organization in this jurisdiction is used.
            </p>
            {seededRates.length === 0 && seededSlabs.length === 0 ? (
              <p className="py-6 text-center text-xs text-foreground-disabled">No seed data for this jurisdiction.</p>
            ) : (
              <>
                {seededRates.length > 0 && (
                  <div className="overflow-x-auto rounded-lg border border-border mb-4">
                    <table className="w-full text-xs">
                      <thead className="bg-background text-left text-foreground-muted">
                        <tr>
                          <th className="px-3 py-2">Component</th>
                          <th className="px-3 py-2">Employee %</th>
                          <th className="px-3 py-2">Employer %</th>
                          <th className="px-3 py-2">Flat Amount</th>
                        </tr>
                      </thead>
                      <tbody>
                        {seededRates.map((r) => (
                          <tr key={r.componentKey} className="border-t border-border-light">
                            <td className="px-3 py-2">
                              <p className="font-semibold text-foreground">{r.label}</p>
                              <p className="font-mono text-[10px] text-foreground-disabled">{r.componentKey}</p>
                            </td>
                            <td className="px-3 py-2 text-foreground-secondary">{r.employeeRatePct != null ? `${r.employeeRatePct}%` : "—"}</td>
                            <td className="px-3 py-2 text-foreground-secondary">{r.employerRatePct != null ? `${r.employerRatePct}%` : "—"}</td>
                            <td className="px-3 py-2 text-foreground-secondary">{r.flatAmount != null ? r.flatAmount : "—"}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
                {seededSlabs.length > 0 && (
                  <div className="overflow-x-auto rounded-lg border border-border">
                    <table className="w-full text-xs">
                      <thead className="bg-background text-left text-foreground-muted">
                        <tr><th className="px-3 py-2">Min</th><th className="px-3 py-2">Max</th><th className="px-3 py-2">Rate</th><th className="px-3 py-2">Label</th></tr>
                      </thead>
                      <tbody>
                        {seededSlabs.map((s, i) => (
                          <tr key={i} className="border-t border-border-light">
                            <td className="px-3 py-2 text-foreground-secondary">{s.minAmount}</td>
                            <td className="px-3 py-2 text-foreground-secondary">{s.maxAmount ?? "and above"}</td>
                            <td className="px-3 py-2 font-semibold text-foreground">{s.ratePct}%</td>
                            <td className="px-3 py-2 text-foreground-secondary">{s.rateLabel}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="rounded-xl border border-border bg-surface p-5">
            <h3 className="mb-1 text-sm font-bold text-foreground">Engine-Only Constants</h3>
            <p className="mb-4 text-xs text-foreground-muted">
              Code-only — there is no database row for these today. Live-read from the actual engine constant, never a copy.
            </p>
            {engineConstants.length === 0 ? (
              <p className="py-6 text-center text-xs text-foreground-disabled">No engine-only constants registered for this jurisdiction.</p>
            ) : (
              <div className="space-y-2">
                {engineConstants.map((c) => {
                  const discrepancy = findDiscrepancy(c, seededRates);
                  return (
                    <div key={c.constantName} className="rounded-lg border border-border-light p-3">
                      <div className="flex items-start justify-between gap-3 flex-wrap">
                        <div>
                          <p className="text-xs font-semibold text-foreground">{c.label}</p>
                          <p className="font-mono text-[10px] text-foreground-disabled">{c.constantName} · resolver key: {c.resolverKey}</p>
                        </div>
                        <div className="text-right">
                          {c.kind === "dict" ? (
                            <pre className="max-w-xs whitespace-pre-wrap text-left font-mono text-[10px] text-foreground-secondary">{JSON.stringify(c.value, null, 1)}</pre>
                          ) : (
                            <span className="font-mono text-sm font-bold tabular-nums text-foreground">{c.value}</span>
                          )}
                        </div>
                      </div>
                      {c.note && (
                        <p className="mt-1.5 text-[11px] text-foreground-muted">{c.note}</p>
                      )}
                      {discrepancy?.kind === "mismatch" && (
                        <div className="mt-2 flex items-start gap-1.5 rounded-md border border-warning/30 bg-warning/5 px-2.5 py-1.5 text-[11px] text-warning">
                          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                          <span>Seed value ({discrepancy.seedValue}) differs from this engine default ({discrepancy.engineValue}) — an org relying on the engine constant instead of the seed row would get a different number.</span>
                        </div>
                      )}
                      {discrepancy?.kind === "no-seed-row" && (
                        <div className="mt-2 flex items-start gap-1.5 rounded-md border border-warning/30 bg-warning/5 px-2.5 py-1.5 text-[11px] text-warning">
                          <AlertTriangle size={13} className="mt-0.5 shrink-0" />
                          <span>No seeded row exists for this component in {country} — this engine constant is the ONLY fallback if never configured.</span>
                        </div>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
