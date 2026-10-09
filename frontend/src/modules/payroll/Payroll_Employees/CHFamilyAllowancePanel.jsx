import { useEffect, useState } from "react";
import { X, Plus, Loader2, CheckCircle, Trash2 } from "lucide-react";
import { listSwissFamilyAllowances, createSwissFamilyAllowance, approveSwissFamilyAllowance, deleteSwissFamilyAllowance } from "../../../service/payrollService";
import { CH_CANTONS } from "../../../components/jurisdiction/switzerland/chComponentConfig";

// Switzerland family allowances (FAK) — the employer records entitlements
// (child/education/birth/adoption, primary/differential). Approval marks the
// fund's decision of record; APPROVED rows cannot be edited or deleted — only
// REQUESTED rows can be edited/deleted. This is a simple CRUD surface for the
// org's own family-allowance entitlements.

const inputCls = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const labelCls = "text-[11px] font-bold uppercase tracking-widest text-foreground-muted";

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const EMPTY = {
  allowanceType: "CHILD",
  childReference: "",
  childBirthDate: "",
  trainingStatus: "",
  entitlementBasis: "PRIMARY",
  primaryFundAmount: "",
  primaryFundReference: "",
  canton: "",
  fakSchemeId: "",
  periodFrom: todayISO(),
  periodTo: "",
  fundDecisionReference: "",
  sourceDocumentId: "",
  reason: "",
};

function statusTone(s) {
  if (s === "APPROVED") return "bg-primary/10 text-primary";
  if (s === "REQUESTED") return "bg-warning/10 text-warning";
  return "bg-foreground-muted/10 text-foreground-muted";
}

export default function CHFamilyAllowancePanel({ employee, onClose }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [showForm, setShowForm] = useState(false);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const res = await listSwissFamilyAllowances({ employeeId: employee.id });
      setRows(Array.isArray(res) ? res : []);
    } catch (e) {
      setError(e?.message || "Failed to load family allowances.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => { load(); /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [employee.id]);

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const num = (v) => (v === "" ? null : Number(v));

  const submit = async (e) => {
    e.preventDefault();
    setCreating(true); setError(null);
    try {
      await createSwissFamilyAllowance({
        employeeId: employee.id,
        allowanceType: form.allowanceType,
        childReference: form.childReference || null,
        childBirthDate: form.childBirthDate || null,
        trainingStatus: form.trainingStatus || null,
        entitlementBasis: form.entitlementBasis,
        primaryFundAmount: form.entitlementBasis === "DIFFERENTIAL" ? num(form.primaryFundAmount) : null,
        primaryFundReference: form.entitlementBasis === "DIFFERENTIAL" ? (form.primaryFundReference || null) : null,
        canton: form.canton || null,
        fakSchemeId: form.fakSchemeId ? Number(form.fakSchemeId) : null,
        periodFrom: form.periodFrom,
        periodTo: form.periodTo || null,
        fundDecisionReference: form.fundDecisionReference || null,
        sourceDocumentId: form.sourceDocumentId ? Number(form.sourceDocumentId) : null,
        reason: form.reason || null,
      });
      setForm(EMPTY);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e?.message || "Failed to create family allowance.");
    } finally {
      setCreating(false);
    }
  };

  const approve = async (id) => {
    try {
      await approveSwissFamilyAllowance(id, { reason: "APPROVED BY OPERATOR" });
      await load();
    } catch (e) {
      setError(e?.message || "Failed to approve.");
    }
  };

  const del = async (id) => {
    try {
      await deleteSwissFamilyAllowance(id);
      await load();
    } catch (e) {
      setError(e?.message || "Failed to delete.");
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-background/40 backdrop-blur-sm" onClick={onClose}>
      <div className="flex h-full w-full max-w-2xl flex-col bg-surface border-l border-border shadow-[0_24px_48px_rgba(0,0,0,0.15)]"
        onClick={(e) => e.stopPropagation()}>
        <div className="flex items-center justify-between px-6 py-5 border-b border-border">
          <div>
            <h2 className="text-[15px] font-bold text-foreground">Switzerland family allowances (FAK)</h2>
            <p className="text-[12px] text-foreground-muted mt-0.5">{employee?.name} · {employee?.employeeCode}</p>
          </div>
          <button type="button" onClick={onClose} aria-label="Close" className="rounded-lg p-1.5 text-foreground-muted hover:bg-surface-muted">
            <X size={16} />
          </button>
        </div>

        <div className="flex-1 overflow-y-auto px-6 py-5 space-y-4">
          <div className="flex items-center justify-between">
            <button type="button" onClick={() => setShowForm((s) => !s)}
              className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-[12px] font-bold text-foreground-muted hover:text-foreground">
              <Plus size={13} /> {showForm ? "Cancel" : "Add entitlement"}
            </button>
          </div>

          {showForm && (
            <form onSubmit={submit} className="bg-surface-muted/40 border border-border rounded-[14px] p-4 space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className={labelCls}>Allowance type</label>
                  <select className={`${inputCls} mt-1.5`} value={form.allowanceType} onChange={set("allowanceType")}>
                    <option value="CHILD">CHILD</option>
                    <option value="EDUCATION">EDUCATION</option>
                    <option value="BIRTH">BIRTH</option>
                    <option value="ADOPTION">ADOPTION</option>
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Basis</label>
                  <select className={`${inputCls} mt-1.5`} value={form.entitlementBasis} onChange={set("entitlementBasis")}>
                    <option value="PRIMARY">PRIMARY</option>
                    <option value="DIFFERENTIAL">DIFFERENTIAL</option>
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Period from</label>
                  <input type="date" className={`${inputCls} mt-1.5`} value={form.periodFrom} onChange={set("periodFrom")} required />
                </div>
                <div>
                  <label className={labelCls}>Period to (optional)</label>
                  <input type="date" className={`${inputCls} mt-1.5`} value={form.periodTo} onChange={set("periodTo")} />
                </div>
                <div>
                  <label className={labelCls}>Canton</label>
                  <select className={`${inputCls} mt-1.5`} value={form.canton} onChange={set("canton")}>
                    <option value="">Select…</option>
                    {CH_CANTONS.map(([code, name]) => <option key={code} value={code}>{code} — {name}</option>)}
                  </select>
                </div>
                <div>
                  <label className={labelCls}>Child reference</label>
                  <input className={`${inputCls} mt-1.5`} value={form.childReference} onChange={set("childReference")} />
                </div>
                <div>
                  <label className={labelCls}>Child birth date</label>
                  <input type="date" className={`${inputCls} mt-1.5`} value={form.childBirthDate} onChange={set("childBirthDate")} />
                </div>
                <div>
                  <label className={labelCls}>Training status</label>
                  <input className={`${inputCls} mt-1.5`} value={form.trainingStatus} onChange={set("trainingStatus")} />
                </div>
                {form.entitlementBasis === "DIFFERENTIAL" && (
                  <>
                    <div>
                      <label className={labelCls}>Primary fund amount (monthly)</label>
                      <input className={`${inputCls} mt-1.5`} inputMode="decimal" value={form.primaryFundAmount} onChange={set("primaryFundAmount")} />
                    </div>
                    <div>
                      <label className={labelCls}>Primary fund reference</label>
                      <input className={`${inputCls} mt-1.5`} value={form.primaryFundReference} onChange={set("primaryFundReference")} />
                    </div>
                  </>
                )}
                <div>
                  <label className={labelCls}>Fund decision reference</label>
                  <input className={`${inputCls} mt-1.5`} value={form.fundDecisionReference} onChange={set("fundDecisionReference")} />
                </div>
              </div>
              {error && <p className="text-[11px] text-error">{error}</p>}
              <button type="submit" disabled={creating}
                className="rounded-lg bg-primary px-4 py-2 text-[12px] font-bold text-white hover:bg-primary-hover disabled:opacity-60">
                {creating ? <Loader2 size={13} className="inline animate-spin" /> : "Create entitlement"}
              </button>
            </form>
          )}

          {loading ? (
            <p className="flex items-center gap-2 text-[12px] text-foreground-muted"><Loader2 size={13} className="animate-spin" /> Loading…</p>
          ) : rows.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border-light bg-surface px-4 py-6 text-center text-[12px] text-foreground-disabled">
              No family allowances recorded for this employee.
            </p>
          ) : (
            <div className="divide-y divide-border-light rounded-xl border border-border overflow-hidden">
              {rows.map((r) => (
                <div key={r.entitlementId} className="px-3 py-2 space-y-1.5">
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2">
                      <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${statusTone(r.status)}`}>{r.status}</span>
                      <span className="text-[12px] font-bold text-foreground">{r.allowanceType}</span>
                      <span className="text-[11px] text-foreground-muted">{r.canton || "—"}</span>
                      <span className="text-[11px] text-foreground-muted">{r.periodFrom}{r.periodTo ? ` → ${r.periodTo}` : " (open)"}</span>
                    </div>
                    <div className="flex items-center gap-1.5">
                      {r.status === "REQUESTED" && (
                        <>
                          <button type="button" onClick={() => approve(r.entitlementId)}
                            className="inline-flex items-center gap-1 rounded-lg bg-primary/10 px-2 py-1 text-[10px] font-bold text-primary hover:bg-primary/20">
                            <CheckCircle size={11} /> Approve
                          </button>
                          <button type="button" onClick={() => del(r.entitlementId)}
                            className="inline-flex items-center gap-1 rounded-lg bg-error/10 px-2 py-1 text-[10px] font-bold text-error hover:bg-error/20">
                            <Trash2 size={11} /> Delete
                          </button>
                        </>
                      )}
                    </div>
                  </div>
                  {r.childReference && <p className="text-[11px] text-foreground-muted">Child: {r.childReference}{r.childBirthDate ? ` (dob ${r.childBirthDate})` : ""}</p>}
                  {r.entitlementBasis === "DIFFERENTIAL" && r.primaryFundAmount != null && (
                    <p className="text-[11px] text-foreground-muted">Primary fund: {r.primaryFundAmount} {r.primaryFundReference ? `(${r.primaryFundReference})` : ""}</p>
                  )}
                </div>
              ))}
            </div>
          )}

          {error && !showForm && <p className="text-[11px] text-error">{error}</p>}
        </div>
      </div>
    </div>
  );
}