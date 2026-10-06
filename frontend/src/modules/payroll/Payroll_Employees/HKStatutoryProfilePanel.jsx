import { useEffect, useState } from "react";
import { History, ShieldAlert, X } from "lucide-react";
import {
  createEmployeeStatutoryProfile,
  getEmployeeStatutoryProfileHistory,
} from "../../../service/payrollService";

// Hong Kong statutory profile (ZP-HK-ENG-001 §3 worker resolver) — FACTS
// only, recorded as a new effective-dated version on the shared statutory
// profile (never edited in place; history stays replayable). No MPF, tax or
// net-pay figure is entered or stored here. Only the fields changed are sent:
// every other HK fact carries forward server-side, and the frozen
// pre-1-May-2025 wage can never change once recorded (HK-017).
const CHOICES = {
  hkgEmploymentRelationship: ["EMPLOYEE", "CASUAL_INDUSTRY", "DOMESTIC", "CONTRACTOR_REVIEW"],
  hkgIdentityDocumentType: ["HKID", "PASSPORT"],
  hkgResidencyStatus: ["RESIDENT", "NON_RESIDENT"],
  hkgMpfExemptionCode: ["NONE", "EXEMPT_AGE", "EXEMPT_DOMESTIC", "EXEMPT_STATUTORY_SCHEME", "EXEMPT_ORSO",
    "EXEMPT_INBOUND", "INDUSTRY_SCHEME_SPECIAL"],
  hkgPayBasis: ["MONTHLY", "DAILY", "HOURLY", "PIECE"],
  hkgTerminationReason: ["REDUNDANCY", "FIXED_TERM_EXPIRY_REDUNDANCY", "LAY_OFF", "DISMISSAL", "FIXED_TERM_EXPIRY",
    "DEATH", "RESIGNATION_ILL_HEALTH", "RESIGNATION_AGE_65", "SUMMARY_DISMISSAL", "RESIGNATION"],
  hkgPreTransitionWageBasis: ["LAST_FULL_MONTH", "TWELVE_MONTH_AVERAGE"],
};
const BOOLEANS = ["hkgEnteredForEmployment", "hkgOverseasSchemeMember", "hkgLikelyChargeable", "hkgFrequentTravelExempt"];
const DATES = ["hkgPermissionToStayUntil", "hkgEmploymentContinuityStart", "hkgArrivalDate", "hkgExpectedDepartureDate",
  "hkgTerminationDate"];

const SECTIONS = [
  ["Employment relationship", [["hkgEmploymentRelationship", "Relationship"], ["hkgPayBasis", "Pay basis"],
    ["hkgContractualWeeklyHours", "Contractual weekly hours"], ["hkgEmploymentContinuityStart", "Continuous employment since (if not joining date)"]]],
  ["Identity & residency", [["hkgIdentityDocumentType", "Identity document"], ["hkgResidencyStatus", "Residency"],
    ["hkgVisaType", "Visa / permission type"], ["hkgEnteredForEmployment", "Entered HK for employment (s.11 IO)"],
    ["hkgArrivalDate", "Arrival date"], ["hkgPermissionToStayUntil", "Permission to stay until"]]],
  ["MPF coverage (never inferred from full-/part-time)", [["hkgMpfExemptionCode", "Exemption"],
    ["hkgMpfExemptionReason", "Exemption reason"], ["hkgMpfExemptionEvidenceRef", "Exemption evidence reference"],
    ["hkgOverseasSchemeMember", "Member of an overseas retirement scheme"], ["hkgMpfSchemeRef", "MPF scheme / eMPF mapping"]]],
  ["IRD reporting & departure", [["hkgLikelyChargeable", "Likely chargeable to Salaries Tax (IR56E)"],
    ["hkgExpectedDepartureDate", "Expected departure from HK (> 1 month)"],
    ["hkgFrequentTravelExempt", "Required to leave HK at frequent intervals (no IR56G)"]]],
  ["Termination", [["hkgTerminationDate", "Termination date"], ["hkgTerminationReason", "Termination reason"]]],
  ["Frozen pre-1-May-2025 wage (SP/LSP transition, HK-017)", [["hkgPreTransitionMonthlyWage", "Last full month's wages before 1 May 2025 (HK$)"],
    ["hkgPreTransitionWageBasis", "Wage basis"], ["hkgPreTransitionEvidenceRef", "Evidence reference"]]],
];

const input = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const labelCls = "mb-1 block text-[12px] font-semibold text-foreground-secondary";

export default function HKStatutoryProfilePanel({ employee, onClose }) {
  const [history, setHistory] = useState([]);
  const [changes, setChanges] = useState({});
  const [effectiveFrom, setEffectiveFrom] = useState(new Date().toISOString().slice(0, 10));
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const current = history[0] || {};

  const [version, setVersion] = useState(0);   // bumped after a save to reload the history

  useEffect(() => {
    let alive = true;
    getEmployeeStatutoryProfileHistory(employee.id)
      .then((rows) => { if (alive) setHistory(Array.isArray(rows) ? rows : []); })
      .catch((err) => { if (alive) setError(err?.message || "Could not load the statutory profile history."); });
    return () => { alive = false; };
  }, [employee.id, version]);

  const value = (k) => (k in changes ? changes[k] : current[k] ?? "");
  const set = (k) => (e) => {
    const v = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setChanges((c) => ({ ...c, [k]: v === "" ? null : v }));
  };

  async function submit(e) {
    e.preventDefault();
    setError(null);
    setNotice(null);
    try {
      await createEmployeeStatutoryProfile(employee.id, { countryCode: "HK", effectiveFrom, reason: reason || null, ...changes });
      setChanges({});
      setNotice(`New version recorded, effective ${effectiveFrom}. Earlier versions are unchanged.`);
      setVersion((v) => v + 1);
    } catch (err) {
      setError(err?.message || "The statutory profile version was not accepted.");
    }
  }

  function field(k, text) {
    const id = `hkp-${k}`;
    if (BOOLEANS.includes(k)) {
      return (
        <label key={k} htmlFor={id} className="flex items-center gap-2 text-[12px] text-foreground-secondary">
          <input id={id} type="checkbox" checked={Boolean(value(k))} onChange={set(k)} /> {text}
        </label>
      );
    }
    return (
      <div key={k}>
        <label className={labelCls} htmlFor={id}>{text}</label>
        {CHOICES[k] ? (
          <select id={id} className={input} value={value(k)} onChange={set(k)}>
            <option value="">—</option>
            {CHOICES[k].map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        ) : (
          <input id={id} type={DATES.includes(k) ? "date" : "text"} className={input} value={value(k)} onChange={set(k)} />
        )}
      </div>
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-2xl flex-col border-l border-border bg-surface shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()} role="dialog" aria-modal="true" aria-labelledby="hk-profile-title">
        <div className="flex items-center justify-between border-b border-border px-6 py-5">
          <div>
            <h2 id="hk-profile-title" className="text-[15px] font-bold text-foreground">Hong Kong statutory profile</h2>
            <p className="mt-0.5 text-[12px] text-foreground-muted">{employee.name} · {employee.employeeCode}</p>
          </div>
          <button onClick={onClose} aria-label="Close panel"
            className="rounded-[12px] border border-border bg-surface-muted p-2 text-foreground-muted hover:border-primary hover:text-primary">
            <X size={15} />
          </button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5">
          <div className="mb-5 flex items-start gap-3 rounded-[14px] border border-warning/30 bg-warning/10 px-4 py-3">
            <ShieldAlert size={16} className="mt-0.5 shrink-0 text-warning" />
            <p className="text-[12px] text-foreground">
              Facts only. MPF contributions, minimum-wage checks and IRD reporting are computed by the server from the
              version in force on each payroll date. Identity numbers are held masked in the employee record.
            </p>
          </div>
          <form onSubmit={submit} className="space-y-5" aria-label="Record a new Hong Kong statutory profile version">
            {SECTIONS.map(([title, fields]) => (
              <fieldset key={title} className="rounded-xl border border-border p-4">
                <legend className="px-1 text-[12px] font-bold uppercase tracking-wide text-foreground-muted">{title}</legend>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{fields.map(([k, t]) => field(k, t))}</div>
              </fieldset>
            ))}
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
              <div>
                <label className={labelCls} htmlFor="hkp-eff">Effective from</label>
                <input id="hkp-eff" type="date" className={input} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} required />
              </div>
              <div>
                <label className={labelCls} htmlFor="hkp-reason">Reason / source of the change</label>
                <input id="hkp-reason" className={input} value={reason} onChange={(e) => setReason(e.target.value)} />
              </div>
            </div>
            {error && <p role="alert" className="text-[12px] font-medium text-error">{error}</p>}
            {notice && <p role="status" className="text-[12px] font-medium text-success">{notice}</p>}
            <button type="submit" disabled={!Object.keys(changes).length}
              className="rounded-lg bg-primary px-4 py-2 text-[13px] font-semibold text-white disabled:opacity-60">
              Record new version
            </button>
          </form>
          <section className="mt-6" aria-labelledby="hk-history">
            <h3 id="hk-history" className="mb-2 flex items-center gap-1.5 text-[13px] font-semibold text-foreground">
              <History size={14} /> Version history (immutable)
            </h3>
            <ul className="space-y-1 text-[12px] text-foreground-secondary">
              {history.map((h) => (
                <li key={h.id}>
                  #{h.id} · {h.effectiveFrom} – {h.effectiveTo || "current"} · MPF {h.hkgMpfExemptionCode || "—"}
                  {h.reason ? ` · ${h.reason}` : ""}
                </li>
              ))}
              {!history.length && <li>No version recorded yet — Hong Kong payroll is blocked until one exists.</li>}
            </ul>
          </section>
        </div>
      </div>
    </div>
  );
}
