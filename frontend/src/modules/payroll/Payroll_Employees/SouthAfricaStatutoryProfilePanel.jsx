import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { createEmployeeStatutoryProfile, getEmployeeStatutoryProfile } from "../../../service/payrollService";

// South Africa statutory profile (ZP-ZA-ENG-001 §5, ZA-005; "ZA" — "SA" is
// Saudi Arabia). The tax facts countries/south_africa.py resolves BEFORE it
// calculates: a missing required fact BLOCKS, it is never guessed. Each save is
// a NEW dated version (fields left unchanged carry forward server-side); the
// server validates every value (south_africa_service._za_statutory_profile_errors).
// SA ID / passport / SARS income-tax number and bank routing live on the
// employee's compliance fields, never here.

const EMPLOYMENT_TYPES = ["STANDARD", "NON_STANDARD"];
const TAX_RESIDENCIES = ["RESIDENT", "NON_RESIDENT"];

// [camelKey, label, kind, choices, note]
// "tri" = not recorded / Yes / No: the engine treats "not recorded" differently
// from "No" (e.g. a director's UIF status must be recorded explicitly).
const FACTS = [
  ["zaEmploymentType", "Employment type", "select", EMPLOYMENT_TYPES, "NON_STANDARD blocks — not certified"],
  ["zaTaxResidency", "Tax residency", "select", TAX_RESIDENCIES, "NON_RESIDENT blocks — deferred scope"],
  ["zaIsDirector", "Director", "tri"],
  ["zaMedicalSchemeMember", "Medical scheme member", "tri"],
  ["zaMedicalDependants", "Medical scheme dependants", "integer", null, "Required for a member (0 or more)"],
  ["zaTravelBusinessUse80", "Travel allowance: ≥ 80% business use", "tri", null, "Yes = 20% PAYE inclusion; otherwise 80%"],
  ["zaUifExcluded", "UIF excluded", "tri", null, "Must be recorded for directors"],
  ["zaUifExclusionReason", "UIF exclusion reason / evidence", "text"],
  ["zaEtiEligible", "ETI eligibility evidence held", "tri", null, "Employer incentive only — never changes the employee's pay"],
  ["zaEtiFirstQualifyingMonth", "ETI first qualifying month", "date"],
  ["zaSezEmployee", "SEZ employee", "tri", null, "Yes blocks — SEZ ETI is deferred scope"],
  ["zaVoluntaryAdditionalPaye", "Voluntary additional PAYE (ZAR / month)", "number"],
  ["zaEvidenceRef", "Evidence reference", "text"],
];

const labelCls = "text-[11px] font-bold uppercase tracking-widest text-foreground-muted";
const inputCls = "mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px]";
const TRI = [["", "— not recorded"], ["true", "Yes"], ["false", "No"]];

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

function triValue(v) {
  if (v === true) return "true";
  if (v === false) return "false";
  return "";
}

export default function SouthAfricaStatutoryProfilePanel({ employee, onClose }) {
  const [current, setCurrent] = useState(null);
  const [changes, setChanges] = useState({});
  const [effectiveFrom, setEffectiveFrom] = useState(todayISO());
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    getEmployeeStatutoryProfile(employee.id).then((p) => { if (live) setCurrent(p || null); }).catch(() => {});
    return () => { live = false; };
  }, [employee.id]);

  const value = (k) => (k in changes ? changes[k] : current?.[k] ?? "");
  const set = (k, kind) => (e) => {
    const raw = e.target.value;
    let v = raw === "" ? null : raw;
    if (kind === "tri") v = raw === "" ? null : raw === "true";
    if (kind === "integer" && v !== null) v = Number.parseInt(raw, 10);
    if (kind === "number" && v !== null) v = raw;
    setChanges((c) => ({ ...c, [k]: v }));
  };
  const save = async (e) => {
    e.preventDefault();
    setBusy(true); setMessage(null);
    try {
      await createEmployeeStatutoryProfile(employee.id, { countryCode: "ZA", effectiveFrom, ...changes });
      setMessage({ ok: true, text: `New South Africa profile version recorded, effective ${effectiveFrom}. Earlier versions are unchanged.` });
      setChanges({});
      setCurrent(await getEmployeeStatutoryProfile(employee.id, effectiveFrom));
    } catch (err) {
      setMessage({ ok: false, text: err?.message || "Could not save the profile." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-2xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">South Africa statutory profile</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee?.name} · {employee?.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={save} className="flex-1 overflow-y-auto px-6 py-5 space-y-4"
          aria-label="Record a new South Africa statutory profile version">
          <p className="text-[12px] text-foreground-muted">
            Facts the PAYE / UIF / SDL calculation needs. A missing required fact blocks the payslip with its reason —
            it is never assumed.
          </p>
          {message && (
            <p role={message.ok ? "status" : "alert"} className={`text-[12px] ${message.ok ? "text-success" : "text-error"}`}>
              {message.text}
            </p>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {FACTS.map(([k, label, kind, choices, note]) => (
              <div key={k}>
                <p className={labelCls}>{label}</p>
                {kind === "select" ? (
                  <select className={inputCls} value={value(k)} onChange={set(k)}>
                    <option value="">—</option>
                    {choices.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                ) : kind === "tri" ? (
                  <select className={inputCls} value={triValue(value(k))} onChange={set(k, "tri")}>
                    {TRI.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
                  </select>
                ) : (
                  <input
                    type={kind === "integer" || kind === "number" ? "number" : kind === "date" ? "date" : "text"}
                    min={kind === "integer" || kind === "number" ? 0 : undefined}
                    step={kind === "integer" ? 1 : kind === "number" ? "0.01" : undefined}
                    className={inputCls} value={value(k)} onChange={set(k, kind)} />
                )}
                {note && <p className="mt-1 text-[11px] text-foreground-muted">{note}</p>}
              </div>
            ))}
          </div>
          <div className="flex flex-wrap items-end gap-3">
            <div>
              <p className={labelCls}>Effective from</p>
              <input type="date" className={inputCls} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
            </div>
            <button type="submit" disabled={busy || Object.keys(changes).length === 0}
              className="rounded-lg bg-primary px-3 py-2 text-[12px] font-semibold text-white disabled:opacity-40">
              {busy ? "Saving…" : "Save new version"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}
