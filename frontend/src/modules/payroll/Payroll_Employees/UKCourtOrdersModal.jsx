import { useEffect, useState } from "react";
import Modal from "../../../components/Modal";
import { listUkCourtOrders, createUkCourtOrder, setUkCourtOrderStatus } from "../../../service/payrollService";

// UK Court-Ordered Deductions (ZP-TAX-UK-2026-27-001 §17 gap-closure Part 8)
// management UI. The backend has always had a complete create/list/status
// API for this — found on a 2026-09-10 gap audit to have NO frontend
// anywhere, so a Super Admin/Org Admin had no way to actually record an
// order despite the calculation engine being fully built. This is that
// missing screen: list an employee's orders, add a new one, and mark one
// completed/cancelled (orders are never hard-deleted — a legal instrument
// stays in the record, matching the backend's own status-only endpoint).
//
// `order_type` is deliberately free text on the backend (may grow without
// a migration) and never affects calculation — only `jurisdiction` decides
// which of engine/countries/uk.py's three separate functions applies. The
// suggested types below are the ones documented on the CourtOrderedDeduction
// model, offered as a starting point, not an enforced enum.
const JURISDICTIONS = [
  { value: "ENGLAND_WALES", label: "England & Wales" },
  { value: "SCOTLAND", label: "Scotland" },
  { value: "NORTHERN_IRELAND", label: "Northern Ireland" },
];

const ORDER_TYPES_BY_JURISDICTION = {
  ENGLAND_WALES: [
    { value: "AEO_PRIORITY", label: "Attachment of Earnings — Priority (e.g. maintenance, fines)" },
    { value: "AEO_NON_PRIORITY", label: "Attachment of Earnings — Non-Priority (e.g. consumer debt)" },
    { value: "COUNCIL_TAX_AEO", label: "Council Tax Attachment of Earnings" },
  ],
  SCOTLAND: [
    { value: "EARNINGS_ARRESTMENT", label: "Earnings Arrestment" },
    { value: "CURRENT_MAINTENANCE_ARRESTMENT", label: "Current Maintenance Arrestment" },
    { value: "CONJOINED_ARRESTMENT", label: "Conjoined Arrestment Order" },
  ],
  NORTHERN_IRELAND: [
    { value: "AEO_NI_STANDARD", label: "Attachment of Earnings Order (Northern Ireland)" },
  ],
};

const inputClass =
  "w-full rounded-[12px] border border-border bg-background px-3.5 py-2.5 text-[13px] text-foreground placeholder:text-foreground-muted focus:outline-none focus:border-primary focus:ring-2 focus:ring-primary/20 transition-all duration-200";
const selectClass = inputClass;

function Field({ label, children, hint }) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">{label}</span>
      {children}
      {hint && <span className="mt-1 block text-[11px] text-foreground-muted">{hint}</span>}
    </label>
  );
}

function statusBadgeClass(status) {
  if (status === "active") return "bg-success/10 text-success";
  if (status === "completed") return "bg-info/10 text-info";
  return "bg-foreground-muted/10 text-foreground-muted"; // cancelled
}

const emptyForm = {
  jurisdiction: "ENGLAND_WALES",
  orderType: "AEO_PRIORITY",
  courtReference: "",
  issueDate: "",
  startDate: "",
  endDate: "",
  priority: "",
  deductionBasis: "STANDARD", // STANDARD | RATE | AMOUNT
  fixedDeductionRatePct: "",
  fixedDeductionAmount: "",
  protectedEarningsAmount: "",
  totalAmountToCollect: "",
};

export default function UKCourtOrdersModal({ employee, onClose }) {
  const [orders, setOrders] = useState([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(emptyForm);
  const [submitError, setSubmitError] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [statusUpdatingId, setStatusUpdatingId] = useState(null);

  async function refresh() {
    setLoading(true);
    setLoadError("");
    try {
      const data = await listUkCourtOrders(employee.id);
      setOrders(Array.isArray(data) ? data : []);
    } catch (err) {
      setLoadError(err.message || "Could not load court orders.");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [employee.id]);

  function updateField(key, value) {
    setForm((prev) => ({ ...prev, [key]: value }));
  }

  function handleJurisdictionChange(value) {
    const firstType = ORDER_TYPES_BY_JURISDICTION[value]?.[0]?.value || "";
    setForm((prev) => ({ ...prev, jurisdiction: value, orderType: firstType }));
  }

  async function handleCreate() {
    setSubmitError("");
    if (!form.startDate) {
      setSubmitError("Start date is required.");
      return;
    }
    if (form.deductionBasis === "RATE" && !form.fixedDeductionRatePct) {
      setSubmitError("Enter the fixed deduction percentage, or switch to the standard published table.");
      return;
    }
    if (form.deductionBasis === "AMOUNT" && !form.fixedDeductionAmount) {
      setSubmitError("Enter the fixed deduction amount, or switch to the standard published table.");
      return;
    }
    setSubmitting(true);
    try {
      await createUkCourtOrder(employee.id, {
        jurisdiction: form.jurisdiction,
        orderType: form.orderType,
        startDate: form.startDate,
        courtReference: form.courtReference,
        issueDate: form.issueDate,
        endDate: form.endDate,
        priority: form.priority,
        fixedDeductionRatePct: form.deductionBasis === "RATE" ? form.fixedDeductionRatePct : null,
        fixedDeductionAmount: form.deductionBasis === "AMOUNT" ? form.fixedDeductionAmount : null,
        protectedEarningsAmount: form.protectedEarningsAmount,
        totalAmountToCollect: form.totalAmountToCollect,
      });
      setForm(emptyForm);
      setShowForm(false);
      refresh();
    } catch (err) {
      setSubmitError(err.message || "Could not record this court order.");
    } finally {
      setSubmitting(false);
    }
  }

  async function handleStatusChange(orderId, status) {
    setStatusUpdatingId(orderId);
    try {
      await setUkCourtOrderStatus(employee.id, orderId, status);
      refresh();
    } catch (err) {
      setLoadError(err.message || "Could not update this order's status.");
    } finally {
      setStatusUpdatingId(null);
    }
  }

  return (
    <Modal title={`Court-Ordered Deductions — ${employee.name}`} onClose={onClose} maxWidth="max-w-2xl">
      <p className="mb-4 rounded-[12px] bg-info/10 px-3.5 py-2.5 text-[12px] text-foreground-secondary">
        England &amp; Wales AEOs, Scottish arrestments, and Northern Ireland's equivalent orders are each
        calculated separately, per HMRC's own rule — pick the correct jurisdiction below. An order is never
        deleted once recorded; mark it completed or cancelled instead.
      </p>

      {loadError && (
        <div className="mb-4 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{loadError}</div>
      )}

      {loading ? (
        <p className="text-[13px] text-foreground-muted">Loading…</p>
      ) : orders.length === 0 ? (
        <p className="text-[13px] text-foreground-muted">No court orders recorded for this employee.</p>
      ) : (
        <div className="space-y-2.5 mb-4">
          {orders.map((o) => (
            <div key={o.id} className="rounded-[14px] border border-border bg-surface-muted p-4">
              <div className="flex items-center justify-between gap-3">
                <div>
                  <p className="text-[13px] font-bold text-foreground">
                    {JURISDICTIONS.find((j) => j.value === o.jurisdiction)?.label || o.jurisdiction} — {o.orderType}
                  </p>
                  <p className="mt-0.5 text-[12px] text-foreground-muted">
                    {o.courtReference ? `Ref ${o.courtReference} · ` : ""}
                    Started {o.startDate}{o.endDate ? ` · Ends ${o.endDate}` : ""}
                    {o.priority !== null && o.priority !== undefined ? ` · Priority ${o.priority}` : ""}
                  </p>
                  <p className="mt-1 text-[12px] text-foreground-secondary">
                    {o.fixedDeductionRatePct ? `Fixed rate ${o.fixedDeductionRatePct}%` : o.fixedDeductionAmount ? `Fixed amount ${o.fixedDeductionAmount}` : "Uses standard published table"}
                    {o.protectedEarningsAmount ? ` · Protected earnings ${o.protectedEarningsAmount}` : ""}
                  </p>
                  {o.totalAmountToCollect && (
                    <p className="mt-1 text-[12px] text-foreground-secondary">
                      Collected {o.totalAmountCollected} of {o.totalAmountToCollect}
                    </p>
                  )}
                </div>
                <span className={`shrink-0 inline-flex items-center rounded-full px-3 py-1 text-[11px] font-bold ${statusBadgeClass(o.status)}`}>
                  {o.status}
                </span>
              </div>
              {o.status === "active" && (
                <div className="mt-3 flex gap-2 border-t border-border-light pt-3">
                  <button
                    onClick={() => handleStatusChange(o.id, "completed")}
                    disabled={statusUpdatingId === o.id}
                    className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary disabled:opacity-50"
                  >
                    Mark completed
                  </button>
                  <button
                    onClick={() => handleStatusChange(o.id, "cancelled")}
                    disabled={statusUpdatingId === o.id}
                    className="rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-error hover:border-error disabled:opacity-50"
                  >
                    Cancel order
                  </button>
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {!showForm ? (
        <button
          onClick={() => setShowForm(true)}
          className="w-full rounded-[12px] border border-dashed border-border px-4 py-2.5 text-[13px] font-semibold text-foreground-secondary hover:border-primary hover:text-primary"
        >
          + Add court order
        </button>
      ) : (
        <div className="rounded-[14px] border border-border p-4">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Jurisdiction">
              <select className={selectClass} value={form.jurisdiction} onChange={(e) => handleJurisdictionChange(e.target.value)}>
                {JURISDICTIONS.map((j) => <option key={j.value} value={j.value}>{j.label}</option>)}
              </select>
            </Field>
            <Field label="Order type">
              <select className={selectClass} value={form.orderType} onChange={(e) => updateField("orderType", e.target.value)}>
                {(ORDER_TYPES_BY_JURISDICTION[form.jurisdiction] || []).map((t) => (
                  <option key={t.value} value={t.value}>{t.label}</option>
                ))}
              </select>
            </Field>

            <Field label="Court reference (optional)">
              <input className={inputClass} value={form.courtReference} onChange={(e) => updateField("courtReference", e.target.value)} />
            </Field>
            <Field label="Priority (optional)" hint="Lower number = deducted first when several orders are active.">
              <input type="number" min="1" className={inputClass} value={form.priority} onChange={(e) => updateField("priority", e.target.value)} />
            </Field>

            <Field label="Issue date (optional)">
              <input type="date" className={inputClass} value={form.issueDate} onChange={(e) => updateField("issueDate", e.target.value)} />
            </Field>
            <Field label="Start date">
              <input type="date" className={inputClass} value={form.startDate} onChange={(e) => updateField("startDate", e.target.value)} />
            </Field>
            <Field label="End date (optional)" hint="Leave blank for an ongoing/open-ended order.">
              <input type="date" className={inputClass} value={form.endDate} onChange={(e) => updateField("endDate", e.target.value)} />
            </Field>
            <Field label="Protected earnings amount (optional)">
              <input type="number" min="0" step="0.01" className={inputClass} value={form.protectedEarningsAmount} onChange={(e) => updateField("protectedEarningsAmount", e.target.value)} />
            </Field>

            <div className="col-span-2">
              <Field label="Deduction basis" hint="The order's own specified rate/amount always overrides the standard published table.">
                <select className={selectClass} value={form.deductionBasis} onChange={(e) => updateField("deductionBasis", e.target.value)}>
                  <option value="STANDARD">Use the standard published rate table</option>
                  <option value="RATE">Order specifies a fixed percentage</option>
                  <option value="AMOUNT">Order specifies a fixed amount</option>
                </select>
              </Field>
            </div>

            {form.deductionBasis === "RATE" && (
              <Field label="Fixed deduction percentage">
                <input type="number" min="0" step="0.01" className={inputClass} value={form.fixedDeductionRatePct} onChange={(e) => updateField("fixedDeductionRatePct", e.target.value)} />
              </Field>
            )}
            {form.deductionBasis === "AMOUNT" && (
              <Field label="Fixed deduction amount">
                <input type="number" min="0" step="0.01" className={inputClass} value={form.fixedDeductionAmount} onChange={(e) => updateField("fixedDeductionAmount", e.target.value)} />
              </Field>
            )}

            <Field label="Total amount to collect (optional)" hint="Leave blank for an ongoing order with no fixed total (e.g. current maintenance).">
              <input type="number" min="0" step="0.01" className={inputClass} value={form.totalAmountToCollect} onChange={(e) => updateField("totalAmountToCollect", e.target.value)} />
            </Field>
          </div>

          {submitError && (
            <div className="mt-3 rounded-[12px] bg-error/10 px-4 py-3 text-[13px] text-error border border-error/20">{submitError}</div>
          )}

          <div className="mt-4 flex justify-end gap-2">
            <button onClick={() => { setShowForm(false); setSubmitError(""); }} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">
              Cancel
            </button>
            <button
              onClick={handleCreate} disabled={submitting}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50"
            >
              {submitting ? "Saving…" : "Save order"}
            </button>
          </div>
        </div>
      )}

      <div className="mt-5 flex justify-end">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Close</button>
      </div>
    </Modal>
  );
}
