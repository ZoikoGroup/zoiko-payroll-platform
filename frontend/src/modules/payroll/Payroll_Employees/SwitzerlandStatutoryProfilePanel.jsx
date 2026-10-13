import { useEffect, useState } from "react";
import { X, Loader2, Search } from "lucide-react";
import { getSwissEntityProfile, resolveSwissQst, getSwissRulesEffective } from "../../../service/payrollService";

// Switzerland statutory profile (read-only advisory surface). AHV is stored
// on the employee's compliance fields (SENSITIVE, EAN-13 validated). The
// employer's UID/compensation office/canton registrations live at org level
// (Swiss Employer Profile). This panel shows the employer's current profile,
// the QST resolution for this employee (advisory) and the effective rules
// for the employee's canton as of a chosen date — no payroll-calculated
// figures are edited here.

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