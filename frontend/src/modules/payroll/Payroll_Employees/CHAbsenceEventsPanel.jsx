import { useEffect, useState } from "react";
import { X, Plus, Loader2, Trash2 } from "lucide-react";
import { listSwissAbsenceEvents, createSwissAbsenceEvent, deleteSwissAbsenceEvent } from "../../../service/payrollService";

const inputCls = "w-full rounded-lg border border-border bg-surface px-3 py-2 text-[13px] text-foreground";
const labelCls = "text-[11px] font-bold uppercase tracking-widest text-foreground-muted";

function todayISO() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

const EMPTY = {
  eventType: "ILLNESS_CO",
  periodFrom: todayISO(),
  periodTo: "",
  dailyAllowanceRate: "",
  insuredSalaryBasis: "",
  insurerClaimReference: "",
  benefitAmountExpected: "",
  benefitAmountReceived: "",
  employerTopupAmount: "",
  reason: "",
};

const TYPES = ["MATERNITY", "OTHER_PARENT", "ADOPTION", "ILLNESS_CO", "ILLNESS_KTG", "ACCIDENT_UVG", "PREGNANCY_PROTECTION"];

export default function CHAbsenceEventsPanel({ employee, onClose }) {
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [creating, setCreating] = useState(false);
  const [form, setForm] = useState(EMPTY);
  const [showForm, setShowForm] = useState(false);

  const load = async () => {
    setLoading(true); setError(null);
    try {
      const res = await listSwissAbsenceEvents({ employeeId: employee.id });
      setRows(Array.isArray(res) ? res : []);
    } catch (e) {
      setError(e?.message || "Failed to load absence events.");
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
      await createSwissAbsenceEvent({
        employeeId: employee.id,
        eventType: form.eventType,
        periodFrom: form.periodFrom,
        periodTo: form.periodTo || null,
        dailyAllowanceRate: num(form.dailyAllowanceRate),
        insuredSalaryBasis: num(form.insuredSalaryBasis),
        insurerClaimReference: form.insurerClaimReference || null,
        benefitAmountExpected: num(form.benefitAmountExpected),
        benefitAmountReceived: num(form.benefitAmountReceived),
        employerTopupAmount: num(form.employerTopupAmount),
        evidenceDocumentId: null,
        reason: form.reason || null,
      });
      setForm(EMPTY);
      setShowForm(false);
      await load();
    } catch (e) {
      setError(e?.message || "Failed to create absence event.");
    } finally {
      setCreating(false);
    }
  };

  const del = async (id) => {
    try {
      await deleteSwissAbsenceEvent(id);
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
            <h2 className="text-[15px] font-bold text-foreground">Switzerland absence events</h2>
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
              <Plus size={13} /> {showForm ? "Cancel" : "Add event"}
            </button>
          </div>

          {showForm && (
            <form onSubmit={submit} className="bg-surface-muted/40 border border-border rounded-[14px] p-4 space-y-3">
              <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                <div>
                  <label className={labelCls}>Event type</label>
                  <select className={`${inputCls} mt-1.5`} value={form.eventType} onChange={set("eventType")}>
                    {TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
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
                  <label className={labelCls}>Daily allowance rate</label>
                  <input className={`${inputCls} mt-1.5`} inputMode="decimal" value={form.dailyAllowanceRate} onChange={set("dailyAllowanceRate")} />
                </div>
                <div>
                  <label className={labelCls}>Insured salary basis</label>
                  <input className={`${inputCls} mt-1.5`} inputMode="decimal" value={form.insuredSalaryBasis} onChange={set("insuredSalaryBasis")} />
                </div>
                <div>
                  <label className={labelCls}>Insurer claim reference</label>
                  <input className={`${inputCls} mt-1.5`} value={form.insurerClaimReference} onChange={set("insurerClaimReference")} />
                </div>
                <div>
                  <label className={labelCls}>Benefit expected</label>
                  <input className={`${inputCls} mt-1.5`} inputMode="decimal" value={form.benefitAmountExpected} onChange={set("benefitAmountExpected")} />
                </div>
                <div>
                  <label className={labelCls}>Benefit received</label>
                  <input className={`${inputCls} mt-1.5`} inputMode="decimal" value={form.benefitAmountReceived} onChange={set("benefitAmountReceived")} />
                </div>
                <div>
                  <label className={labelCls}>Employer top-up</label>
                  <input className={`${inputCls} mt-1.5`} inputMode="decimal" value={form.employerTopupAmount} onChange={set("employerTopupAmount")} />
                </div>
              </div>
              {error && <p className="text-[11px] text-error">{error}</p>}
              <button type="submit" disabled={creating}
                className="rounded-lg bg-primary px-4 py-2 text-[12px] font-bold text-white hover:bg-primary-hover disabled:opacity-60">
                {creating ? <Loader2 size={13} className="inline animate-spin" /> : "Create event"}
              </button>
            </form>
          )}

          {loading ? (
            <p className="flex items-center gap-2 text-[12px] text-foreground-muted"><Loader2 size={13} className="animate-spin" /> Loading…</p>
          ) : rows.length === 0 ? (
            <p className="rounded-xl border border-dashed border-border-light bg-surface px-4 py-6 text-center text-[12px] text-foreground-disabled">
              No absence events recorded for this employee.
            </p>
          ) : (
            <div className="divide-y divide-border-light rounded-xl border border-border overflow-hidden">
              {rows.map((r) => (
                <div key={r.eventId} className="flex items-start justify-between px-3 py-2">
                  <div className="space-y-0.5">
                    <div className="flex items-center gap-2">
                      <span className="text-[12px] font-bold text-foreground">{r.eventType}</span>
                      <span className="text-[11px] text-foreground-muted">{r.periodFrom}{r.periodTo ? ` → ${r.periodTo}` : " (open)"}</span>
                    </div>
                    {r.insurerClaimReference && <p className="text-[11px] text-foreground-muted">Claim: {r.insurerClaimReference}</p>}
                    {r.benefitAmountExpected != null && <p className="text-[11px] text-foreground-muted">Expected: {r.benefitAmountExpected}</p>}
                  </div>
                  <button type="button" onClick={() => del(r.eventId)}
                    className="rounded-lg p-1.5 text-foreground-muted hover:text-error">
                    <Trash2 size={13} />
                  </button>
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