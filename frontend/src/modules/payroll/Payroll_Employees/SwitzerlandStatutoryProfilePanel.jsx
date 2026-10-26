import { useEffect, useState } from "react";
import { X, Loader2, Search } from "lucide-react";
import {
  createEmployeeStatutoryProfile, getEmployeeStatutoryProfile, getSwissEntityProfile, getSwissRulesEffective,
  listSwissSchemes, resolveSwissQst,
} from "../../../service/payrollService";

const CANTONS = ["AG", "AI", "AR", "BE", "BL", "BS", "FR", "GE", "GL", "GR", "JU", "LU", "NE", "NW", "OW", "SG", "SH",
  "SO", "SZ", "TG", "TI", "UR", "VD", "VS", "ZG", "ZH"].map((c) => `CH-${c}`);
// The ch_* worker facts the Swiss resolver reads (CH-004). [camelKey, label, kind, choices]
const FACTS = [
  ["chWorkCanton", "Work canton", "select", CANTONS],
  ["chResidenceCountry", "Residence country (ISO-2)", "text"],
  ["chResidenceCanton", "Residence canton (CH residents)", "select", CANTONS],
  ["chQstSubject", "Source tax (QST) liable", "select", ["YES", "NO", "REVIEW_REQUIRED"]],
  ["chQstCanton", "QST canton", "select", CANTONS],
  ["chQstTariffCode", "QST tariff code (e.g. A, B, C, H)", "text"],
  ["chChildrenCount", "Children (QST tariff)", "number"],
  ["chChurchTax", "Church tax", "bool"],
  ["chMaritalStatus", "Marital status", "text"],
  ["chSpouseEmployed", "Spouse employed", "bool"],
  ["chCrossBorder", "Cross-border worker", "bool"],
  ["chWeeklyHours", "Weekly hours", "number"],
  ["chBvgPlanSchemeId", "BVG pension plan", "scheme", "BVG_PLAN"],
  ["chUvgPolicySchemeId", "UVG accident policy", "scheme", "UVG_POLICY"],
  ["chUvgRiskClass", "UVG risk class", "text"],
  ["chKtgPolicySchemeId", "KTG sickness policy", "scheme", "KTG_POLICY"],
  ["chContractEnd", "Contract end (fixed-term)", "date"],
];
const inputCls = "mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px]";

// Worker facts: shown from the version in force, saved as a NEW dated version
// through the shared statutory-profile endpoint (fields left unchanged carry
// forward server-side). The server validates every value against the resolver's
// own vocabularies; scheme ids must be this organisation's schemes.
function WorkerFacts({ employee, onDate }) {
  const [current, setCurrent] = useState(null);
  const [schemes, setSchemes] = useState([]);
  const [changes, setChanges] = useState({});
  const [effectiveFrom, setEffectiveFrom] = useState(onDate);
  const [message, setMessage] = useState(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let live = true;
    getEmployeeStatutoryProfile(employee.id, onDate).then((p) => { if (live) setCurrent(p || null); }).catch(() => {});
    listSwissSchemes().then((r) => { if (live) setSchemes(Array.isArray(r) ? r : r?.items || r?.data || []); }).catch(() => {});
    return () => { live = false; };
  }, [employee.id, onDate]);

  const value = (k) => (k in changes ? changes[k] : current?.[k] ?? "");
  const set = (k, kind) => (e) => {
    const v = kind === "bool" ? e.target.checked : e.target.value;
    setChanges((c) => ({ ...c, [k]: v === "" ? null : v }));
  };
  const save = async (e) => {
    e.preventDefault();
    setBusy(true); setMessage(null);
    try {
      await createEmployeeStatutoryProfile(employee.id, { countryCode: "CH", effectiveFrom, ...changes });
      setMessage({ ok: true, text: `New Swiss profile version recorded, effective ${effectiveFrom}.` });
      setChanges({});
      setCurrent(await getEmployeeStatutoryProfile(employee.id, effectiveFrom));
    } catch (err) {
      setMessage({ ok: false, text: err?.message || "Could not save the profile." });
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={save} className="bg-surface-muted/40 border border-border rounded-[14px] p-4 space-y-3"
      aria-label="Record a new Switzerland statutory profile version">
      <h3 className="text-[13px] font-bold text-foreground">Worker facts (statutory profile)</h3>
      {message && <p role={message.ok ? "status" : "alert"} className={`text-[12px] ${message.ok ? "text-success" : "text-error"}`}>{message.text}</p>}
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {FACTS.map(([k, label, kind, choices]) => (
          <Field key={k} label={label}>
            {kind === "select" || kind === "scheme" ? (
              <select className={inputCls} value={value(k)} onChange={set(k)}>
                <option value="">—</option>
                {(kind === "scheme"
                  ? schemes.filter((s) => (s.schemeType || s.scheme_type) === choices)
                    .map((s) => ({ v: s.id, t: `${s.schemeCode || s.scheme_code || s.id} ${s.name ? `— ${s.name}` : ""}` }))
                  : choices.map((c) => ({ v: c, t: c }))
                ).map((o) => <option key={o.v} value={o.v}>{o.t}</option>)}
              </select>
            ) : kind === "bool" ? (
              <input type="checkbox" className="mt-2" checked={Boolean(value(k))} onChange={set(k, "bool")} />
            ) : (
              <input type={kind === "number" ? "number" : kind === "date" ? "date" : "text"} className={inputCls}
                value={value(k)} onChange={set(k)} />
            )}
          </Field>
        ))}
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <Field label="Effective from">
          <input type="date" className={inputCls} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} />
        </Field>
        <button type="submit" disabled={busy || Object.keys(changes).length === 0}
          className="rounded-lg bg-primary px-3 py-2 text-[12px] font-semibold text-white disabled:opacity-40">
          {busy ? "Saving…" : "Save new version"}
        </button>
      </div>
    </form>
  );
}

// Switzerland statutory profile. AHV is stored
// on the employee's compliance fields (SENSITIVE, EAN-13 validated). The
// employer's UID/compensation office/canton registrations live at org level
// (Swiss Employer Profile). This panel shows the employer's current profile,
// the QST resolution for this employee (advisory) and the effective rules
// for the employee's canton as of a chosen date — no payroll-calculated
// figures are edited here. The worker's own ch_* facts are edited in the
// "Worker facts" section below (a new dated version, never an overwrite).

const labelCls = "text-[11px] font-bold uppercase tracking-widest text-foreground-muted";
const valueCls = "mt-1 text-[13px] text-foreground";

function Field({ label, children }) {
  return (
    <div>
      <p className={labelCls}>{label}</p>
      {children}
    </div>
  );
}

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

export default function SwitzerlandStatutoryProfilePanel({ employee, onClose }) {
  const [onDate, setOnDate] = useState(todayISO());
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [orgProfile, setOrgProfile] = useState(null);
  const [qst, setQst] = useState(null);
  const [qstLoading, setQstLoading] = useState(false);
  const [rules, setRules] = useState(null);
  const [rulesLoading, setRulesLoading] = useState(false);

  const ahv = employee?.complianceFields?.ahv_number || "—";
  const cantonRegs = orgProfile?.current?.cantonRegistrations || [];
  const seat = orgProfile?.current?.seatCanton || "—";

  useEffect(() => {
    let live = true;
    setLoading(true);
    setError(null);
    getSwissEntityProfile(onDate)
      .then((p) => { if (live) setOrgProfile(p || null); })
      .catch((e) => { if (live) setError(e?.message || "Failed to load Swiss employer profile."); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [onDate]);

  const runQst = async () => {
    setQstLoading(true); setError(null);
    try {
      const payload = { employeeId: employee.id, on: onDate || undefined };
      const res = await resolveSwissQst(payload);
      setQst(res || null);
    } catch (e) {
      setError(e?.message || "QST resolution failed.");
    } finally {
      setQstLoading(false);
    }
  };

  const runRules = async () => {
    setRulesLoading(true); setError(null);
    try {
      const canton = orgProfile?.current?.seatCanton || undefined;
      const res = await getSwissRulesEffective(onDate, canton);
      setRules(res || null);
    } catch (e) {
      setError(e?.message || "Failed to load Swiss rules effective.");
    } finally {
      setRulesLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-2xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">Switzerland statutory profile</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee?.name} · {employee?.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-5">
          {loading && <p className="flex items-center gap-2 text-[13px] text-foreground-muted"><Loader2 size={14} className="animate-spin" /> Loading…</p>}
          {error && <p role="alert" className="text-[12px] font-medium text-error">{error}</p>}

          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <Field label="AHV/AVS number">
              <p className={`${valueCls} font-mono`}>{ahv}</p>
            </Field>
            <Field label="Effective date">
              <input type="date" className="mt-1.5 w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px]" value={onDate} onChange={(e) => setOnDate(e.target.value)} />
            </Field>
            <Field label="Seat canton"><p className={valueCls}>{seat}</p></Field>
            <Field label="UID (Business ID)"><p className={valueCls}>{orgProfile?.current?.uid || "—"}</p></Field>
          </div>

          {cantonRegs.length > 0 && (
            <div>
              <p className={labelCls}>Canton QST registrations</p>
              <div className="mt-2 divide-y divide-border-light rounded-xl border border-border">
                {cantonRegs.map((r, i) => (
                  <div key={i} className="grid grid-cols-1 gap-2 px-3 py-2 text-[12px] sm:grid-cols-3">
                    <p className="text-foreground font-medium">{r.canton}</p>
                    <p className="text-foreground-muted">Debtor: {r.qstDebtorNumber || "—"}</p>
                    <p className="text-foreground-muted">Ref: {r.reference || "—"}</p>
                  </div>
                ))}
              </div>
            </div>
          )}

          <WorkerFacts employee={employee} onDate={onDate} />

          <div className="bg-surface-muted/40 border border-border rounded-[14px] p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-[13px] font-bold text-foreground">QST resolution (advisory)</h3>
              <button type="button" onClick={runQst} disabled={qstLoading}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[11px] font-bold text-foreground-muted hover:text-foreground disabled:opacity-40">
                <Search size={12} /> {qstLoading ? <Loader2 size={12} className="animate-spin" /> : "Resolve"}
              </button>
            </div>
            {qst ? (
              <div className="grid grid-cols-1 gap-2 text-[12px] sm:grid-cols-2">
                <Field label="QST subject"><p className={valueCls}>{qst.qstSubject ?? "—"}</p></Field>
                <Field label="Basis"><p className={valueCls}>{qst.qstBasis ?? "—"}</p></Field>
                <Field label="Canton"><p className={valueCls}>{qst.canton ?? "—"}</p></Field>
                <Field label="Tariff file ID"><p className={valueCls}>{qst.tariffFileId ?? "—"}</p></Field>
              </div>
            ) : (
              <p className="text-[12px] text-foreground-disabled">No QST resolution yet — click Resolve to check (read-only).</p>
            )}
          </div>

          <div className="bg-surface-muted/40 border border-border rounded-[14px] p-4 space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-[13px] font-bold text-foreground">Effective rules (seat canton)</h3>
              <button type="button" onClick={runRules} disabled={rulesLoading}
                className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[11px] font-bold text-foreground-muted hover:text-foreground disabled:opacity-40">
                <Search size={12} /> {rulesLoading ? <Loader2 size={12} className="animate-spin" /> : "Load"}
              </button>
            </div>
            {rules ? (
              <div className="space-y-2 text-[12px]">
                <p className="text-foreground-muted">Federal packs: {rules.federalPacks?.length || 0}; Canton packs: {rules.cantonPacks?.length || 0}; Schemes (LIVE): {rules.liveSchemes?.length || 0}; QST tariff files: {rules.qstTariffFiles?.length || 0}</p>
              </div>
            ) : (
              <p className="text-[12px] text-foreground-disabled">No effective rules loaded yet.</p>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}