import { useState } from "react";
import { AlertTriangle, CheckCircle2, CircleDashed, XCircle } from "lucide-react";
import { formatDate, fractionToPct } from "./sgComponentConfig";
import useSgStatutorySummary from "./useSgStatutorySummary";

// Singapore Statutory Summary (Phase 5.6) — renders
// GET /super-admin/compliance/singapore/statutory-summary as returned. Every
// figure is a persisted row value from the backend; nothing is computed or
// defaulted here. Rows the pack does not hold show "Not configured".
const STATUS_STYLE = {
  CONFIGURED: { cls: "text-success", Icon: CheckCircle2 },
  PASS: { cls: "text-success", Icon: CheckCircle2 },
  PARTIAL: { cls: "text-warning", Icon: AlertTriangle },
  REVIEW: { cls: "text-warning", Icon: AlertTriangle },
  NOT_CONFIGURED: { cls: "text-foreground-muted", Icon: CircleDashed },
  BLOCKED: { cls: "text-error", Icon: XCircle },
};

export function SgStatus({ status }) {
  const s = STATUS_STYLE[status] || STATUS_STYLE.NOT_CONFIGURED;
  return (
    <span className={`inline-flex items-center gap-1 text-[11px] font-bold ${s.cls}`}>
      <s.Icon size={13} aria-hidden="true" /> {status}
    </span>
  );
}

const LABELS = {
  owCeilingMonthly: "OW ceiling (monthly)", annualWageCeiling: "Annual wage ceiling", ageBandSemantics: "Age-band rule",
  enforcementDayFollowingMonth: "Enforcement day (following month)", rateBands: "CPF rate bands", cohorts: "CPF cohorts",
  rate: "SDL rate", minimumMonthly: "Minimum (monthly)", maximumMonthly: "Maximum (monthly)",
  fundBands: "SHG fund bands", funds: "SHG funds", fundCount: "Number of funds",
  sPassMonthly: "S Pass levy (monthly)", workPermitLevyRows: "Work Permit levy rows", paymentDueDay: "Levy payment due day",
  sPassEndDayBasis: "Pass end-day basis", fullTimeMonthly: "Full-time (monthly)", partTimeHourly: "Part-time (hourly)",
  floorRows: "PWM wage-floor rows", overtimeRateRows: "PWM overtime-rate rows", overtimeSchedule: "Overtime gross schedule",
  aisMandatoryEmployeeThreshold: "AIS mandatory threshold (employees)", aisSubmissionMode: "AIS submission mode",
  aisFilingCalendar: "AIS filing calendar", retentionYearsFromYa: "Record retention (years from YA)",
  departureTriggerMonths: "Departure trigger (months)", filingLeadMonths: "Filing lead time (months)",
  template: "EZPay report template",
  activePack: "Active pack", valuesFromPack: "Values shown from", valuesFromActivePack: "Values from an Active pack",
  versions: "Pack versions",
};

function rowValue(v) {
  if (v.employerRatePct !== null && v.employerRatePct !== undefined) return fractionToPct(v.employerRatePct);
  if (v.flatAmount !== null && v.flatAmount !== undefined) return v.flatAmount;
  return v.textValue ?? "—";
}

function packText(p) {
  return `${p.packId} v${p.version} (${p.status}, from ${formatDate(p.effectiveFrom)})`;
}

function renderValue(key, v) {
  if (v === null || v === undefined) return <span className="text-foreground-disabled">Not configured</span>;
  if (Array.isArray(v)) return v.map((x) => (x && typeof x === "object" && "packId" in x ? packText(x) : x)).join(", ");
  if (typeof v === "boolean") return v ? "Yes" : <span className="text-warning">No</span>;
  if (typeof v !== "object") return String(v);
  if ("flatAmount" in v || "employerRatePct" in v) {
    const validity = v.effectiveFrom || v.effectiveTo ? ` · ${formatDate(v.effectiveFrom)} – ${v.effectiveTo ? formatDate(v.effectiveTo) : "open"}` : "";
    return <span title={v.label}>{rowValue(v)}<span className="text-foreground-muted">{validity}</span></span>;
  }
  if (key === "overtimeSchedule") {
    return `${v.totalRows} rows · ${v.schedules} schedules · ${v.overtimeHoursMin}–${v.overtimeHoursMax} OT hours · ${v.rowsEffectiveOnDate} in force · retrieved ${formatDate((v.latestRetrievedAt || "").slice(0, 10))}`;
  }
  if (key === "aisFilingCalendar") return `${formatDate(v.dueDate)} — ${v.periodLabel} (${v.status})`;
  if (key === "template") return `v${v.version} (${v.status})`;
  if ("packId" in v) return packText(v);
  return JSON.stringify(v);
}

// Phase 5.8 — the backend's activation-readiness block, shown as returned.
// Read-only: activation itself stays in the pack lifecycle (maker-checker).
const GATE_TEXT = {
  distinct_approver: "Approved by someone other than the last editor",
  source_evidence_linked: "Source evidence linked to the pack",
  effective_from_set: "Effective-from date set",
  latest_golden_run_pass: "Latest SG golden-vector run PASS",
};

function ActivationReadiness({ readiness }) {
  const pack = readiness.statutoryPack;
  const rows = [
    ["Status", pack.status ?? "Not configured"], ["Version", pack.packId ? `${pack.packId} v${pack.version}` : "—"],
    ["Effective from", formatDate(pack.effectiveFrom)], ["Source", pack.source ? `${pack.source.agency} — ${pack.source.title}` : "Not linked"],
    ["Source hash", pack.sourceHash ? `${pack.sourceHash.slice(0, 16)}…` : "—"],
    ["Approval", pack.approval.approvedById ? `User #${pack.approval.approvedById}` : "Not approved"],
    ["Activation", pack.activation], ["External validation", pack.externalValidation],
  ];
  return (
    <section className="rounded-xl border border-border bg-surface p-4" aria-labelledby="sg-activation-heading">
      <h3 id="sg-activation-heading" className="mb-2 text-sm font-bold text-foreground">Activation readiness (read-only)</h3>
      <div className="grid grid-cols-1 gap-4 text-xs md:grid-cols-3">
        <dl className="space-y-1">
          {rows.map(([k, v]) => (
            <div key={k} className="flex justify-between gap-3"><dt className="text-foreground-muted">{k}</dt><dd className="text-right font-medium text-foreground">{v}</dd></div>
          ))}
        </dl>
        <ul className="space-y-1">
          {pack.activationGates.map((g) => (
            <li key={g.key} className="flex items-start gap-1.5"><SgStatus status={g.met ? "PASS" : "BLOCKED"} /><span className="text-foreground-secondary">{GATE_TEXT[g.key] || g.key}</span></li>
          ))}
        </ul>
        <dl className="space-y-1">
          {Object.entries(readiness.reportTemplates).map(([k, v]) => (
            <div key={`t-${k}`} className="flex justify-between gap-3"><dt className="text-foreground-muted">Templates {k}</dt><dd className="font-medium text-foreground">{v}</dd></div>
          ))}
          {Object.entries(readiness.pwm).map(([k, v]) => (
            <div key={`p-${k}`} className="flex justify-between gap-3"><dt className="text-foreground-muted">PWM {k}</dt><dd className="font-medium text-foreground">{v ?? "—"}</dd></div>
          ))}
        </dl>
      </div>
    </section>
  );
}

export default function SGStatutorySummaryTab() {
  const [asOf, setAsOf] = useState(() => new Date().toISOString().slice(0, 10));
  const { loading, error, data } = useSgStatutorySummary(asOf);
  const statutory = (data?.sections || []).filter((s) => s.key !== "readiness" && s.key !== "reportTemplates");
  const readiness = (data?.sections || []).find((s) => s.key === "readiness");
  const templates = (data?.sections || []).find((s) => s.key === "reportTemplates");
  const pack = data?.valuesFromPack;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-xs font-medium text-foreground-muted">
          Point in time
          <input type="date" value={asOf} onChange={(e) => e.target.value && setAsOf(e.target.value)}
            className="mt-1 block rounded-lg border border-border bg-surface px-2 py-1 text-sm text-foreground" />
        </label>
        {data && (
          <p className="text-xs text-foreground-muted" role="status">
            {data.valuesFromActivePack
              ? <>Values from Active pack <b className="text-foreground">{pack.packId} v{pack.version}</b></>
              : pack
                ? <span className="text-warning">No Active pack on this date — values shown from {pack.packId} v{pack.version} ({pack.status}) for review only; not in force.</span>
                : <span className="text-error">No Singapore tax pack covers this date.</span>}
          </p>
        )}
      </div>

      {loading && <p className="text-sm text-foreground-muted">Loading…</p>}
      {error && <p className="text-sm text-error" role="alert">{error}</p>}

      {data && (
        <>
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {statutory.map((s) => (
              <section key={s.key} className="rounded-xl border border-border bg-surface p-3" aria-labelledby={`sg-sum-${s.key}`}>
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 id={`sg-sum-${s.key}`} className="text-sm font-bold text-foreground">{s.label}</h3>
                  <SgStatus status={s.status} />
                </div>
                {s.configurationStatus && s.configurationStatus !== s.status && (
                  <p className="mb-1 text-[11px] text-warning">Configuration {s.configurationStatus} — not in force</p>
                )}
                {s.lifecycleState && (
                  <p className="mb-1 text-[11px] text-foreground-muted">
                    Pack {s.lifecycleState} · {s.validationState} · sources reviewed {s.sourcesReviewed}
                    {s.lastRetrievedAt ? ` · retrieved ${formatDate(s.lastRetrievedAt.slice(0, 10))}` : ""}
                    {s.effectiveTo ? ` · effective to ${formatDate(s.effectiveTo)}` : ""}
                  </p>
                )}
                <dl className="space-y-1 text-xs">
                  {Object.entries(s.values).map(([k, v]) => (
                    <div key={k} className="flex justify-between gap-3">
                      <dt className="text-foreground-muted">{LABELS[k] || k}</dt>
                      <dd className="text-right font-medium text-foreground">{renderValue(k, v)}</dd>
                    </div>
                  ))}
                </dl>
                {s.sources.length > 0 && (
                  <p className="mt-2 text-[11px] text-foreground-muted">
                    Sources: {s.sources.map((src) => `${src.agency} — ${src.title}${src.reviewed ? "" : " (unreviewed)"}`).join("; ")}
                  </p>
                )}
                {s.notes.map((n) => <p key={n} className="mt-1 text-[11px] text-foreground-muted">{n}</p>)}
              </section>
            ))}
            {templates && (
              <section className="rounded-xl border border-border bg-surface p-3" aria-labelledby="sg-sum-templates">
                <div className="mb-2 flex items-center justify-between gap-2">
                  <h3 id="sg-sum-templates" className="text-sm font-bold text-foreground">{templates.label}</h3>
                  <SgStatus status={templates.status} />
                </div>
                <p className="text-xs text-foreground">{templates.values.present} of {templates.values.expected} present</p>
                {templates.missing.length > 0 && <p className="mt-1 text-[11px] text-warning">Missing: {templates.missing.join(", ")}</p>}
                <p className="mt-1 text-[11px] text-foreground-muted">See the Report Templates tab.</p>
              </section>
            )}
          </div>

          {data.activationReadiness && <ActivationReadiness readiness={data.activationReadiness} />}

          {readiness && (
            <section className="rounded-xl border border-border bg-surface p-4" aria-labelledby="sg-sum-readiness">
              <div className="mb-2 flex items-center gap-2">
                <h3 id="sg-sum-readiness" className="text-sm font-bold text-foreground">Readiness</h3>
                <SgStatus status={readiness.status} />
              </div>
              <ul className="space-y-1.5 text-xs">
                {readiness.values.items.map((i) => (
                  <li key={i.key} className="flex flex-wrap items-baseline gap-2">
                    <SgStatus status={i.status} />
                    <span className="font-semibold text-foreground">{i.label}</span>
                    <span className="text-foreground-muted">{i.evidence}</span>
                  </li>
                ))}
              </ul>
              <p className="mt-3 text-[11px] text-foreground-muted">{data.certification}</p>
            </section>
          )}
        </>
      )}
    </div>
  );
}
