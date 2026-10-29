import { useEffect, useState } from "react";
import { X } from "lucide-react";
import { createEmployeeStatutoryProfile, getEmployeeStatutoryProfile } from "../../../service/payrollService";

// Saudi Arabia statutory profile (ZP-SA-ENG-001 §3/§5, SA-E4). The GOSI facts
// the engine reads — worker class (branch selector), cohort (pension system)
// with its evidence, the GOSI-registered contributory wage, identity and
// contract facts. Each save is a NEW dated version (fields left unchanged carry
// forward server-side); the server validates every value against the engine's
// own vocabularies. National ID / Iqama and IBAN live on the employee's
// compliance fields, never here.

const WORKER_CLASSES = ["SAUDI", "NON_SAUDI", "GCC", "DOMESTIC"];
const COHORTS = ["NEW", "LEGACY"];
const ID_TYPES = ["NATIONAL_ID", "IQAMA", "GCC_ID", "PASSPORT"];
const CONTRACT_TYPES = ["LIMITED", "UNLIMITED", "PART_TIME", "TEMPORARY"];

// [camelKey, label, kind, choices]
const FACTS = [
  ["saWorkerClass", "Worker class (GOSI branch)", "select", WORKER_CLASSES],
  ["saCohort", "Cohort (pension system)", "select", COHORTS],
  ["saCohortEvidenceRef", "Cohort evidence reference (required for SAUDI / GCC)", "text"],
  ["saContributoryWage", "GOSI-registered contributory wage (SAR / month)", "number"],
  ["saContributoryWageEffectiveFrom", "Registered wage effective from", "date"],
  ["saContributoryWageGosiRef", "GOSI wage reference", "text"],
  ["saInKindHousingValue", "In-kind housing value (SAR / month)", "number"],
  ["saIdentityDocumentType", "Identity document type", "select", ID_TYPES],
  ["saIdentityExpiry", "Identity document expiry", "date"],
  ["saGosiRegistrationStatus", "GOSI registration status", "text"],
  ["saGosiRegistrationDate", "GOSI registration date", "date"],
  ["saContractType", "Contract type", "select", CONTRACT_TYPES],
  ["saOccupation", "Occupation", "text"],
  ["saServiceStartDate", "Service start date (EOS)", "date"],
  ["saReducedRamadanHours", "Reduced Ramadan hours", "bool"],
  ["saSpecialCategory", "Special category (blocks if set)", "text"],
];

const labelCls = "text-[11px] font-bold uppercase tracking-widest text-foreground-muted";
const inputCls = "mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px]";

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function SaudiArabiaStatutoryProfilePanel({ employee, onClose }) {
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
    const v = kind === "bool" ? e.target.checked : e.target.value;
    setChanges((c) => ({ ...c, [k]: v === "" ? null : v }));
  };
  const save = async (e) => {
    e.preventDefault();
    setBusy(true); setMessage(null);
    try {
      await createEmployeeStatutoryProfile(employee.id, { countryCode: "SA", effectiveFrom, ...changes });
      setMessage({ ok: true, text: `New Saudi profile version recorded, effective ${effectiveFrom}. Earlier versions are unchanged.` });
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
            <h2 className="text-[15px] font-bold text-foreground">Saudi Arabia statutory profile</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee?.name} · {employee?.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>
        <form onSubmit={save} className="flex-1 overflow-y-auto px-6 py-5 space-y-4"
          aria-label="Record a new Saudi Arabia statutory profile version">
          {message && (
            <p role={message.ok ? "status" : "alert"} className={`text-[12px] ${message.ok ? "text-success" : "text-error"}`}>
              {message.text}
            </p>
          )}
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {FACTS.map(([k, label, kind, choices]) => (
              <div key={k}>
                <p className={labelCls}>{label}</p>
                {kind === "select" ? (
                  <select className={inputCls} value={value(k)} onChange={set(k)}>
                    <option value="">—</option>
                    {choices.map((c) => <option key={c} value={c}>{c}</option>)}
                  </select>
                ) : kind === "bool" ? (
                  <input type="checkbox" className="mt-2" checked={Boolean(value(k))} onChange={set(k, "bool")} />
                ) : (
                  <input type={kind === "number" ? "number" : kind === "date" ? "date" : "text"} className={inputCls}
                    value={value(k)} onChange={set(k)} />
                )}
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
