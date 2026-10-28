import { useState } from "react";
import { listZaDeductionOrders, recordZaDeductionOrder } from "../../../service/payrollService";
import { useLoad } from "../../../components/jurisdiction/southAfrica/zaFormat";
import { Table } from "../../../components/jurisdiction/southAfrica/zaShared";

// South Africa non-statutory deductions (ZP-ZA-ENG-001 §5, ZA-013; "ZA" — "SA"
// is Saudi Arabia). A deduction needs a recognised authority and evidence of
// it; the server validates the authority against the rule pack and the engine
// BLOCKS a damage / loss deduction while no limit is configured.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
const AUTHORITIES = [
  ["STATUTORY", "Statutory"], ["COURT_ORDER", "Court order"], ["CONSENT", "Written consent"],
  ["COLLECTIVE", "Collective agreement"],
];
const EMPTY = { orderType: "", authorityType: "COURT_ORDER", amount: "", evidenceRef: "", reference: "",
  startDate: "", endDate: "" };

export default function ZADeductionOrdersBlock({ employeeId }) {
  const [rows, error, , reload] = useLoad(() => listZaDeductionOrders(employeeId));
  const [form, setForm] = useState(EMPTY);
  const [state, setState] = useState({ busy: false, error: null });
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const submit = async () => {
    setState({ busy: true, error: null });
    try {
      await recordZaDeductionOrder(employeeId, { ...form, endDate: form.endDate || null });
      setForm(EMPTY);
      setState({ busy: false, error: null });
      reload();
    } catch (e) {
      setState({ busy: false, error: e?.message || "The deduction could not be recorded." });
    }
  };
  return (
    <div className="bg-surface-muted rounded-[18px] p-5 mt-4" data-testid="za-deduction-orders">
      <h4 className="text-[11px] font-bold uppercase tracking-widest text-foreground-muted mb-3">
        South Africa deductions (authority &amp; evidence required)
      </h4>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      <Table rows={rows || []} empty="No deductions recorded." columns={[
        { label: "Type", key: "order_type" },
        { label: "Authority", key: "za_authority_type" },
        { label: "Amount", key: "fixed_deduction_amount" },
        { label: "Evidence", key: "za_evidence_ref" },
        { label: "From", key: "start_date" },
        { label: "To", render: (r) => r.end_date || "Open" },
        { label: "Status", key: "status" },
      ]} />
      <div className="mt-3 grid grid-cols-2 gap-2 md:grid-cols-4">
        <label className={labelCls}>Type
          <input className={input} value={form.orderType} onChange={set("orderType")} placeholder="e.g. GARNISHEE" />
        </label>
        <label className={labelCls}>Authority
          <select className={input} value={form.authorityType} onChange={set("authorityType")}>
            {AUTHORITIES.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
          </select>
        </label>
        <label className={labelCls}>Amount per period
          <input className={input} value={form.amount} onChange={set("amount")} inputMode="decimal" />
        </label>
        <label className={labelCls}>Evidence reference
          <input className={input} value={form.evidenceRef} onChange={set("evidenceRef")} maxLength={300} />
        </label>
        <label className={labelCls}>Order reference
          <input className={input} value={form.reference} onChange={set("reference")} maxLength={100} />
        </label>
        <label className={labelCls}>Start date
          <input className={input} type="date" value={form.startDate} onChange={set("startDate")} />
        </label>
        <label className={labelCls}>End date
          <input className={input} type="date" value={form.endDate} onChange={set("endDate")} />
        </label>
        <div className="flex items-end">
          <button type="button" onClick={submit}
            disabled={state.busy || !form.orderType || !form.amount || !form.evidenceRef || !form.startDate}
            className="rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white hover:opacity-90 disabled:opacity-40">
            Record deduction
          </button>
        </div>
      </div>
      {state.error && <p role="alert" className="mt-2 text-[12px] text-error">{state.error}</p>}
    </div>
  );
}
