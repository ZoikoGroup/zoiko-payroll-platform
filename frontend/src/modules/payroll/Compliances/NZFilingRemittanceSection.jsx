import { useState } from "react";
import {
  approveNzFiling, getNzFiling, getNzRemittance, listNzEmployerProfiles, listNzFilings, listNzRemittances,
  matchNzSettlement, recordNzFilingResponse, recordNzSettlement, reverseNzSettlement, setNzJournalAccounts,
  submitNzFiling,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// New Zealand payday filing, remittance and the journal account map
// (ZP-NZ-ENG-001 §9, NZ-018, NZ-019). Filings and remittance lines are built
// by the server when a run is PAID, from the frozen payslips only; nothing
// here edits an amount. A filing is approved by a second user and cannot be
// submitted until gate G3 certifies the schema (the JSON preview carries the
// IRD number masked only). A remittance is paid only by settlements a second
// user has matched — a filing's acceptance never pays anything.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
const ask = (message) => {
  const value = window.prompt(message);
  return value && value.trim() ? value.trim() : null;
};

function useAction(reload) {
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const run = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      await fn();
      setState({ busy: false, error: null, notice });
      reload?.();
    } catch (err) {
      setState({ busy: false, error: errorText(err), notice: null });
    }
  };
  return [state, run];
}

function Messages({ state, loadError }) {
  return (
    <>
      {loadError && <p role="alert" className="text-[12px] text-error">{loadError}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
    </>
  );
}

function Filings() {
  const [rows, loadError, loading, reload] = useLoad(() => listNzFilings());
  const [state, run] = useAction(reload);
  const [preview, setPreview] = useState(null);

  const respond = (r) => {
    const outcome = ask("Inland Revenue's outcome: ACCEPTED or REJECTED");
    if (!outcome) return;
    const reference = ask("Inland Revenue reference (optional)") || undefined;
    const errorCodes = outcome.toUpperCase() === "REJECTED"
      ? String(ask("Error codes (comma-separated)") || "").split(",").map((c) => c.trim()).filter(Boolean)
      : [];
    run(() => recordNzFilingResponse(r.id, { outcome, reference, errorCodes }), "Response recorded.");
  };

  return (
    <section className={card} data-testid="nz-filings">
      <h3 className="text-[14px] font-semibold text-foreground">Payday filing</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Employment information (every employee paid that payday, across its paid runs) and employee details (starters
        and leavers), per legal employer. Built when a run is paid; a change after approval makes a new version, after
        submission an amendment. The due date stays empty until the working-day rule and the public holidays are
        signed. Submission is refused until the filing schema is certified (gate G3).
      </p>
      <Messages state={state} loadError={loadError} />
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No filings yet — they appear when a New Zealand run is paid."
          columns={[
            { label: "Payday", key: "payDate" }, { label: "Schedule", key: "filingType" },
            { label: "Kind", render: (r) => `${r.kind} v${r.version}${r.amendsId ? ` (amends #${r.amendsId})` : ""}` },
            { label: "Runs", render: (r) => (r.runIds || []).map((id) => `#${id}`).join(", ") },
            { label: "Channel", key: "channel" }, { label: "Due", render: (r) => r.dueOn || "Not computed (rule unsigned)" },
            { label: "Status", render: (r) => `${r.status}${r.authorityErrors?.length ? ` (${r.authorityErrors.join(", ")})` : ""}` },
            { label: "Actions", render: (r) => (
              <div className="flex flex-wrap gap-1">
                <button type="button" className={btn} disabled={state.busy}
                  onClick={() => run(async () => setPreview(await getNzFiling(r.id)), null)}>Preview</button>
                {r.status === "DRAFT" && (
                  <button type="button" className={btn} disabled={state.busy}
                    onClick={() => run(() => approveNzFiling(r.id), "Filing approved.")}>Approve</button>
                )}
                {r.status === "APPROVED" && (
                  <button type="button" className={btn} disabled={state.busy}
                    onClick={() => run(() => submitNzFiling(r.id), "Filing submitted.")}>Submit (gate G3)</button>
                )}
                {r.status === "SUBMITTED" && (
                  <button type="button" className={btn} disabled={state.busy} onClick={() => respond(r)}>Record response</button>
                )}
              </div>
            ) },
          ]} />
      )}
      {preview && (
        <div className="mt-3" data-testid="nz-filing-preview">
          <div className="flex items-center justify-between">
            <p className="text-[12px] font-semibold text-foreground">
              Filing #{preview.id} — {preview.filingType} {preview.kind} v{preview.version} (IRD numbers masked)
            </p>
            <button type="button" className={btn} onClick={() => setPreview(null)}>Close</button>
          </div>
          <pre className="mt-2 max-h-80 overflow-auto rounded-lg bg-surface-muted p-2 text-[11px] text-foreground">
            {JSON.stringify(preview.payload, null, 2)}
          </pre>
        </div>
      )}
    </section>
  );
}

function RemittanceDetail({ remittanceId, onChanged }) {
  const [detail, loadError, loading, reload] = useLoad(() => getNzRemittance(remittanceId));
  const [state, run] = useAction(() => { reload(); onChanged(); });
  const [v, setV] = useState({});
  const set = (key) => (e) => setV({ ...v, [key]: e.target.value });

  const submit = (e) => {
    e.preventDefault();
    run(async () => {
      await recordNzSettlement(remittanceId, { amount: v.amount, paid_on: v.paidOn, payment_reference: v.reference, reason: v.reason });
      setV({});
    }, "Settlement recorded — a second user must match it.");
  };

  return (
    <div className="mt-3 rounded-lg border border-border p-3" data-testid="nz-remittance-detail">
      <Messages state={state} loadError={loadError} />
      {loading || !detail ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <>
          <p className="text-[12px] font-semibold text-foreground">
            {detail.obligation} · {detail.periodStart} to {detail.periodEnd} · {detail.amount} owed, {detail.settled} settled
          </p>
          <Table rows={detail.lines} empty="No lines."
            columns={[{ label: "Run", render: (l) => `#${l.runId}` }, { label: "Payslip", render: (l) => `#${l.payslipItemId}` },
              { label: "Source", key: "source" }, { label: "Amount", key: "amount" }]} />
          <div className="mt-3">
            <Table rows={detail.settlements} empty="No settlements recorded."
              columns={[
                { label: "Paid on", key: "paidOn" }, { label: "Amount", key: "amount" },
                { label: "Reference", key: "paymentReference" }, { label: "Status", key: "status" },
                { label: "Actions", render: (s) => (
                  <div className="flex flex-wrap gap-1">
                    {s.status === "RECORDED" && (
                      <button type="button" className={btn} disabled={state.busy}
                        onClick={() => run(() => matchNzSettlement(s.id), "Settlement matched.")}>Match</button>
                    )}
                    {s.status !== "REVERSED" && (
                      <button type="button" className={btn} disabled={state.busy} onClick={() => {
                        const reason = ask("Why is the settlement reversed?");
                        if (reason) run(() => reverseNzSettlement(s.id, reason), "Settlement reversed.");
                      }}>Reverse</button>
                    )}
                  </div>
                ) },
              ]} />
          </div>
          <form onSubmit={submit} className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4" aria-label="Record a settlement">
            <label className={labelCls}>Amount *<input className={input} required inputMode="decimal" value={v.amount || ""} onChange={set("amount")} /></label>
            <label className={labelCls}>Paid on *<input className={input} required type="date" value={v.paidOn || ""} onChange={set("paidOn")} /></label>
            <label className={labelCls}>Payment reference *<input className={input} required value={v.reference || ""} onChange={set("reference")} /></label>
            <label className={labelCls}>Reason *<input className={input} required value={v.reason || ""} onChange={set("reason")} /></label>
            <div className="flex items-end"><button type="submit" className={btn} disabled={state.busy}>Record settlement</button></div>
          </form>
        </>
      )}
    </div>
  );
}

function Remittances() {
  const [rows, loadError, loading, reload] = useLoad(() => listNzRemittances());
  const [open, setOpen] = useState(null);
  return (
    <section className={card} data-testid="nz-remittances">
      <h3 className="text-[14px] font-semibold text-foreground">Remittance</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        What is owed per period, obligation and destination (Inland Revenue or a complying KiwiSaver fund). A correction
        is added to the original payday&apos;s period and flagged late if that period was already due.
      </p>
      {loadError && <p role="alert" className="text-[12px] text-error">{loadError}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="Nothing owed yet."
          columns={[
            { label: "Period", render: (r) => `${r.periodStart} – ${r.periodEnd}` }, { label: "Obligation", key: "obligation" },
            { label: "Destination", render: (r) => (r.fundRef ? `${r.destination} (${r.fundRef})` : r.destination) },
            { label: "Owed", key: "amount" }, { label: "Settled", key: "settled" },
            { label: "Due", render: (r) => r.dueOn || "Not computed (rule unsigned)" },
            { label: "Status", render: (r) => `${r.status}${r.late ? " · LATE" : ""}` },
            { label: "", render: (r) => (
              <button type="button" className={btn} onClick={() => setOpen(open === r.id ? null : r.id)}>
                {open === r.id ? "Hide" : "Details"}
              </button>
            ) },
          ]} />
      )}
      {open && <RemittanceDetail key={open} remittanceId={open} onChanged={reload} />}
    </section>
  );
}

const ACCOUNT_FIELDS = [
  ["salary_expense", "Salary expense"], ["employer_kiwisaver_expense", "Employer KiwiSaver expense"],
  ["paye_payable", "PAYE payable (incl. ACC earner levy)"], ["student_loan_payable", "Student loan payable"],
  ["kiwisaver_payable", "KiwiSaver payable"], ["esct_payable", "ESCT payable"],
  ["child_support_payable", "Child support payable"], ["other_deductions_payable", "Other deductions payable"],
  ["net_pay_payable", "Net pay payable"],
];

function JournalAccounts() {
  const [profiles, loadError, loading, reload] = useLoad(() => listNzEmployerProfiles());
  const active = (profiles || []).filter((p) => p.status === "ACTIVE");
  const [selected, setSelected] = useState("");
  const [v, setV] = useState({});
  const [state, run] = useAction(reload);
  const set = (key) => (e) => setV({ ...v, [key]: e.target.value });

  const choose = (e) => {
    const id = e.target.value;
    setSelected(id);
    const profile = active.find((p) => String(p.id) === id);
    setV({ ...(profile?.nz_journal_accounts || {}) });
  };
  const submit = (e) => {
    e.preventDefault();
    const { reason, ...rest } = v;
    const accounts = Object.fromEntries(ACCOUNT_FIELDS.map(([k]) => [k, rest[k]]).filter(([, x]) => x));
    run(() => setNzJournalAccounts(Number(selected), accounts, reason), "Account map saved.");
  };

  return (
    <section className={card} data-testid="nz-journal-accounts">
      <h3 className="text-[14px] font-semibold text-foreground">Journal account map</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Your own general-ledger codes. A paid run&apos;s journal stays blocked until every account is mapped — it is never
        posted to a guessed account.
      </p>
      <Messages state={state} loadError={loadError} />
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <label className={labelCls}>Employer profile
          <select className={input} value={selected} onChange={choose}>
            <option value="">— choose an ACTIVE profile —</option>
            {active.map((p) => <option key={p.id} value={p.id}>{p.legal_name}{p.legal_entity_id ? ` (entity #${p.legal_entity_id})` : ""}</option>)}
          </select>
        </label>
      )}
      {selected && (
        <form onSubmit={submit} className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3" aria-label="Journal account map">
          {ACCOUNT_FIELDS.map(([key, label]) => (
            <label key={key} className={labelCls}>{label}
              <input className={input} value={v[key] || ""} onChange={set(key)} />
            </label>
          ))}
          <label className={labelCls}>Reason *<input className={input} required value={v.reason || ""} onChange={set("reason")} /></label>
          <div className="flex items-end"><button type="submit" className={btn} disabled={state.busy}>Save account map</button></div>
        </form>
      )}
    </section>
  );
}

export default function NZFilingRemittanceSection() {
  return (
    <div className="space-y-4">
      <Filings />
      <Remittances />
      <JournalAccounts />
    </div>
  );
}
