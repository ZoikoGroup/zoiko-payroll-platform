import { useEffect, useState } from "react";
import { AlertTriangle, CheckCircle2, Clock, ShieldAlert, XCircle } from "lucide-react";
import { getCompliancePolicies, getFilingCalendarEntries, getTestCertificationRuns } from "../../../service/superAdminService";
import {
  HEALTH, IR21_WORKFLOW, NOT_BUILT, evaluateSgHealth, formatDate, formatSgdAuto, fractionToPct, rateByKey, shgRows, SHG_FUNDS,
} from "./sgComponentConfig";
import useSgStatutorySummary from "./useSgStatutorySummary";

// Singapore Overview (JurisdictionLayout overviewTabOverride — the UK's
// UKOverviewDashboard precedent). Read-only: component summary, Compliance
// Health, the three distinct compliance clocks (+ the worker-specific IR21
// clock), upcoming changes and production-gate status. Uses only existing
// Super Admin read APIs (test-certification runs, filing calendar, packs).
const LEVEL_STYLE = {
  [HEALTH.COMPLIANT]: { cls: "text-success", Icon: CheckCircle2 },
  [HEALTH.WARNING]: { cls: "text-warning", Icon: AlertTriangle },
  [HEALTH.BLOCKED]: { cls: "text-error", Icon: XCircle },
};

export default function SGOverviewDashboard({ pack, rates, slabs }) {
  const [latestRun, setLatestRun] = useState(null);
  const [aisEntry, setAisEntry] = useState(null);
  const [packs, setPacks] = useState([]);
  // PWM reference data and statutory-operations state come from the backend
  // summary (the PWM schedule is not a pack row, so `rates` cannot show it).
  const summary = useSgStatutorySummary(undefined);
  const sections = summary.data?.sections || [];
  const pwmValues = sections.find((s) => s.key === "pwm")?.values;
  const gates = summary.data?.activationReadiness?.productionGates || [];
  const ops = Object.fromEntries((sections.find((s) => s.key === "operations")?.values?.items || []).map((i) => [i.key, i]));
  const pwmText = summary.loading ? "PWM loading…" : summary.error ? "PWM unavailable" : pwmValues?.overtimeSchedule
    ? `PWM ${pwmValues.floorRows ?? 0} floors · ${pwmValues.overtimeSchedule.totalRows} OT-gross rows`
    : "PWM not configured";

  useEffect(() => {
    getTestCertificationRuns({ jurisdiction_country: "SG" })
      .then((runs) => setLatestRun([...(runs || [])].sort((a, b) => String(b.runAt).localeCompare(String(a.runAt)))[0] || null))
      .catch(() => setLatestRun(null));
    getFilingCalendarEntries({ country: "SG", reportType: "IR8A", reportingYear: pack.taxYear || undefined })
      .then((rows) => setAisEntry((rows || [])[0] || null))
      .catch(() => setAisEntry(null));
    getCompliancePolicies({ country: "SG", packType: "tax" }).then((rows) => setPacks(rows || [])).catch(() => setPacks([]));
  }, [pack.id, pack.taxYear]);

  const health = evaluateSgHealth({ pack, rates, slabs, latestRun, aisCalendarEntry: aisEntry });
  const overall = LEVEL_STYLE[health.overall];
  const val = (key, fmt = (r) => formatSgdAuto(r.flatAmount)) => {
    const r = rateByKey(rates, key);
    return r ? fmt(r) : "Not configured";
  };
  const today = new Date().toISOString().slice(0, 10);
  const upcoming = [
    ...(rates || []).filter((r) => r.effectiveFrom && r.effectiveFrom > today).map((r) => ({ key: `r${r.id}`, date: r.effectiveFrom, text: r.label })),
    ...packs.filter((p) => p.id !== pack.id && p.effectiveFrom && p.effectiveFrom > (pack.effectiveFrom || ""))
      .map((p) => ({ key: `p${p.id}`, date: p.effectiveFrom, text: `${p.packId} v${p.version} (${p.status})` })),
  ].sort((a, b) => a.date.localeCompare(b.date));
  const has2027Pack = packs.some((p) => (p.effectiveFrom || "") >= "2027-01-01");

  return (
    <div className="mb-5 space-y-4">
      <div className={`flex flex-wrap items-center gap-2 rounded-xl border border-border bg-surface-muted/50 p-3 ${overall.cls}`} role="status">
        <overall.Icon size={18} aria-hidden="true" />
        <span className="text-sm font-bold">Compliance Health: {health.overall}</span>
        <span className="text-xs text-foreground-muted">
          {health.checks.filter((c) => c.level === HEALTH.BLOCKED).length} blocked · {health.checks.filter((c) => c.level === HEALTH.WARNING).length} warnings
          · not payroll-activatable until every production gate is evidenced
        </span>
      </div>

      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Kpi label="CPF" value={`OW ceiling ${val("cpf_ow_ceiling_monthly")}`} sub={`Annual ${val("cpf_annual_wage_ceiling")}`} />
        <Kpi label="SDL (employer cost)" value={val("sdl", (r) => fractionToPct(r.employerRatePct))} sub={`${val("sdl_min_monthly")} – ${val("sdl_max_monthly")}`} />
        <Kpi label="SHG" value={`${SHG_FUNDS.filter((f) => shgRows(slabs, f.key).length).length} of 4 funds`} sub="CDAC · ECF · MBMF · SINDA" />
        <Kpi label="Foreign Worker Levy" value={`S Pass ${val("fwl_s_pass_monthly")}`} sub="Employer cost — never deducted" />
        <Kpi label="LQS / PWM" value={`FT ${val("lqs_full_time_monthly")}`} sub={`PT ${val("lqs_part_time_hourly", (r) => `${formatSgdAuto(r.flatAmount)}/h`)} · ${pwmText}`} />
        <Kpi label="IRAS AIS" value={ops.ais_api ? "API: external integration required" : NOT_BUILT.aisApi}
          sub={ops.ir8a ? `IR8A export ${ops.ir8a.state === "READY" ? "ready" : ops.ir8a.state.toLowerCase().replace(/_/g, " ")} · 2026 income → YA2027` : "2026 income → YA2027"} />
        <Kpi label="IR21" value="Case workflow" sub="Per organization — IR21 Tax Clearance tab" />
        <Kpi label="Golden vectors" value={latestRun ? `${latestRun.status}` : "No run"} sub={latestRun ? `${latestRun.passedCases}/${latestRun.totalCases} · ${new Date(latestRun.runAt).toLocaleDateString("en-SG")}` : "Run from the Golden Vectors tab"} />
      </div>

      <div className="grid grid-cols-1 gap-4 xl:grid-cols-2">
        <section className="rounded-xl border border-border bg-surface p-4" aria-labelledby="sg-health-heading">
          <h3 id="sg-health-heading" className="mb-2 text-sm font-bold text-foreground">Health checks</h3>
          <ul className="space-y-1.5">
            {health.checks.map((c) => {
              const s = LEVEL_STYLE[c.level];
              return (
                <li key={c.key} className="flex items-start gap-2 text-xs">
                  <s.Icon size={14} className={`mt-0.5 shrink-0 ${s.cls}`} aria-hidden="true" />
                  <span>
                    <span className="font-semibold text-foreground">{c.label}</span>
                    <span className={`ml-1.5 text-[10px] font-bold ${s.cls}`}>{c.level}</span>
                    <span className="block text-foreground-muted">{c.detail}</span>
                  </span>
                </li>
              );
            })}
          </ul>
        </section>

        <div className="space-y-4">
          <section className="rounded-xl border border-border bg-surface p-4" aria-labelledby="sg-clocks-heading">
            <h3 id="sg-clocks-heading" className="mb-2 flex items-center gap-1.5 text-sm font-bold text-foreground"><Clock size={14} aria-hidden="true" /> Compliance clocks</h3>
            <p className="mb-2 text-[11px] text-foreground-muted">Distinct deadlines — never the same date.</p>
            <ol className="space-y-2 text-xs">
              <Clk n="1" title="Salary payment" text={val("salary_payment_deadline_days", (r) => `Within ${Number(r.flatAmount)} days after the salary period`)}
                extra={val("overtime_payment_deadline_days", (r) => `Overtime: within ${Number(r.flatAmount)} days`)} />
              <Clk n="2" title="CPF / SDL / SHG contribution" text="Legal due: last day of the calendar month"
                extra={val("cpf_enforcement_day_following_month", (r) => `Enforcement if unpaid after the ${Number(r.flatAmount)}th of the following month`)} />
              <Clk n="3" title="IRAS AIS annual" text={aisEntry ? `${formatDate(aisEntry.dueDate)} — ${aisEntry.periodLabel}` : "Not configured in the filing calendar"}
                extra={aisEntry ? `Calendar status: ${aisEntry.status}` : null} />
              <Clk n="+" title="IR21 (per worker)" text={val("ir21_filing_lead_months", (r) => `File at least ${Number(r.flatAmount)} month(s) before cessation / departure`)}
                extra={`Worker-specific clock — ${IR21_WORKFLOW}`} />
            </ol>
          </section>

          <section className="rounded-xl border border-border bg-surface p-4" aria-labelledby="sg-upcoming-heading">
            <h3 id="sg-upcoming-heading" className="mb-2 text-sm font-bold text-foreground">Upcoming changes</h3>
            <ul className="space-y-1 text-xs">
              {upcoming.map((u) => <li key={u.key}><span className="font-semibold text-foreground">{formatDate(u.date)}</span> — <span className="text-foreground-secondary">{u.text}</span></li>)}
              {!has2027Pack && (
                <li className="text-warning">1 Jan 2027 — CPF senior-worker rates change; no 2027 pack exists yet (create a new version, never edit 2026 rows).</li>
              )}
              {upcoming.length === 0 && has2027Pack && <li className="text-foreground-disabled">None scheduled.</li>}
            </ul>
          </section>

          <section className="rounded-xl border border-border bg-surface p-4" aria-labelledby="sg-gates-heading">
            <h3 id="sg-gates-heading" className="mb-2 flex items-center gap-1.5 text-sm font-bold text-foreground"><ShieldAlert size={14} aria-hidden="true" /> Production gates (ZP-SG-ENG-001 §18)</h3>
            <ul className="grid grid-cols-1 gap-1 text-xs sm:grid-cols-2">
              {gates.map((g) => (
                <li key={g.key} className="flex items-start gap-1.5">
                  <XCircle size={12} className="mt-0.5 shrink-0 text-error" aria-hidden="true" />
                  <span><span className="font-semibold text-foreground">{g.key}</span> <span className="text-foreground-secondary">{g.label}</span> <span className="text-[10px] font-bold text-error">{g.status.replace(/_/g, " ")}</span></span>
                </li>
              ))}
              {!gates.length && <li className="text-foreground-muted">{summary.loading ? "Loading…" : "Gate status unavailable"}</li>}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}

function Kpi({ label, value, sub }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-3">
      <p className="text-[11px] font-medium text-foreground-muted">{label}</p>
      <p className="mt-0.5 text-sm font-bold text-foreground">{value}</p>
      {sub && <p className="mt-0.5 text-[11px] text-foreground-muted">{sub}</p>}
    </div>
  );
}

function Clk({ n, title, text, extra }) {
  return (
    <li className="flex gap-2">
      <span className="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-primary/10 text-[10px] font-bold text-primary" aria-hidden="true">{n}</span>
      <span>
        <span className="font-semibold text-foreground">{title}: </span>
        <span className="text-foreground-secondary">{text}</span>
        {extra && <span className="block text-[11px] text-foreground-muted">{extra}</span>}
      </span>
    </li>
  );
}
