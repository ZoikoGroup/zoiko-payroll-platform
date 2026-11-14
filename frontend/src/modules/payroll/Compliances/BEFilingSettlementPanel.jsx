import { useState } from "react";
import {
  approveBeFiling, buildBeBelcotax, buildBeDimonaEvents, buildBeDmfa, buildBeWithholding, cancelBeFiling,
  getBeEmployeeCopy, getBeFiling, listBeFilingCalendar, listBeFilingExceptions, listBeFilings, listBeObligations,
  listBeVariances, reconcileBeObligation, recordBeFilingResponse, recordBeFilingSubmission, recordBeObligationPayment,
  recordBeOnssAdvance, resolveBeVariance, transmitBeFiling, validateBeFiling,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { errorText } from "../../../components/jurisdiction/new_zealand/nzOrgOptions";

// Belgium filing centre (ZP-BE-ENG-001 §10 / §14; Block C1). Dimona events from
// the employment lines, the DmfA per quarter, the withholding object and the
// Belcotax fiches are built from committed payroll as canonical payloads with
// masked identifiers. A filing is VALIDATED only against the schema in force on
// its submission date, archived and mapped (none is yet, G-08); approval is
// four-eyes. Nothing is sent from here (gate G3, D9): the submission and the
// authority's answer are recorded by hand. Obligations keep acceptance apart
// from payment (BE-036); due dates come only from the authority calendar
// content (BE-035). This page shows server values; it computes nothing.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const label = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
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
      reload();
    } catch (err) {
      setState({ busy: false, error: errorText(err), notice: null });
    }
  };
  return [state, run];
}

function Messages({ state, error }) {
  return (
    <>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
    </>
  );
}

function ExceptionQueue() {
  const [rows, error, loading] = useLoad(() => listBeFilingExceptions());
  return (
    <section className={card} data-testid="be-filing-exceptions">
      <h3 className="text-[14px] font-semibold text-foreground">Exception queue</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Rejected filings, late Dimona, filings that could not be validated, overdue or unsourced obligations,
        unexplained variances and failed salary payments — with what each one blocks.
      </p>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No open exceptions."
          columns={[
            { label: "Category", key: "category" }, { label: "Severity", key: "severity" },
            { label: "Subject", render: (r) => (r.filingId ? `filing #${r.filingId}` : r.obligationId
              ? `obligation #${r.obligationId}` : r.batchId ? `batch #${r.batchId}` : `variance #${r.varianceId}`) },
            { label: "Period", render: (r) => r.period || "—" }, { label: "Blocks", key: "blocks" },
            { label: "Detail", render: (r) => r.detail || "—" },
          ]} />
      )}
    </section>
  );
}

function Calendar() {
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [rows, error, loading, reload] = useLoad(() => listBeFilingCalendar(Number(year) || undefined));
  return (
    <section className={card} data-testid="be-filing-calendar">
      <h3 className="text-[14px] font-semibold text-foreground">Authority calendar</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Due dates are content rows maintained by the Super Admin from the published operational calendars. Only an
        Active row with a source is used; without one the due date stays “not sourced” — never assumed.
      </p>
      <label className={label}>
        Year
        <input className={input} value={year} onChange={(e) => setYear(e.target.value)} inputMode="numeric"
          aria-label="Calendar year" />
      </label>
      <button type="button" className={btn} onClick={reload}>Show year</button>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No Belgian calendar rows for this year."
          columns={[
            { label: "Report", key: "reportType" }, { label: "Period", key: "periodKey" },
            { label: "Due", key: "dueDate" }, { label: "Status", key: "status" },
            { label: "Used", render: (r) => (r.used ? "yes" : r.sourced ? "no (not Active)" : "no (no source)") },
          ]} />
      )}
    </section>
  );
}

function Builders({ employees, onBuilt }) {
  const [state, run] = useAction(onBuilt);
  const [quarter, setQuarter] = useState("");
  const [period, setPeriod] = useState("");
  const [year, setYear] = useState(String(new Date().getFullYear() - 1));
  const [employeeId, setEmployeeId] = useState("");
  return (
    <section className={card} data-testid="be-filing-builders">
      <h3 className="text-[14px] font-semibold text-foreground">Build declarations</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Built from committed (approved) payroll only. Building again with nothing changed returns the same filing;
        a change after transmission becomes a linked correction, never an edit.
      </p>
      <Messages state={state} />
      <div className="flex flex-wrap items-end gap-2">
        <label className={label}>
          Employee (Dimona)
          <select className={input} value={employeeId} onChange={(e) => setEmployeeId(e.target.value)}>
            <option value="">— Select —</option>
            {employees.map((e) => <option key={e.id} value={e.id}>{e.name} · {e.employeeCode}</option>)}
          </select>
        </label>
        <button type="button" className={btn} disabled={state.busy || !employeeId}
          onClick={() => run(() => buildBeDimonaEvents(Number(employeeId)), "Dimona events built.")}>
          Dimona IN / update / OUT
        </button>
        <button type="button" className={btn} disabled={state.busy || !employeeId} onClick={() => {
          const reason = ask("Why is the Dimona IN cancelled?");
          if (reason) run(() => buildBeDimonaEvents(Number(employeeId), { event: "CANCEL", reason }), "Cancellation built.");
        }}>Cancel Dimona IN</button>
      </div>
      <div className="mt-2 flex flex-wrap items-end gap-2">
        <label className={label}>
          Quarter (YYYYQn)
          <input className={input} value={quarter} onChange={(e) => setQuarter(e.target.value.toUpperCase())}
            aria-label="DmfA quarter" placeholder="2026Q3" />
        </label>
        <button type="button" className={btn} disabled={state.busy || !quarter}
          onClick={() => run(() => buildBeDmfa(quarter), "DmfA built.")}>Build DmfA</button>
        <label className={label}>
          Withholding period (YYYY-MM or YYYYQn)
          <input className={input} value={period} onChange={(e) => setPeriod(e.target.value.toUpperCase())}
            aria-label="Withholding period" />
        </label>
        <button type="button" className={btn} disabled={state.busy || !period}
          onClick={() => run(() => buildBeWithholding(period), "Withholding object built.")}>Build withholding</button>
        <label className={label}>
          Income year
          <input className={input} value={year} onChange={(e) => setYear(e.target.value)} inputMode="numeric"
            aria-label="Income year" />
        </label>
        <button type="button" className={btn} disabled={state.busy || !year}
          onClick={() => run(() => buildBeBelcotax(Number(year)), "Belcotax fiches built.")}>Build Belcotax fiches</button>
      </div>
    </section>
  );
}

function Filings() {
  const [rows, error, loading, reload] = useLoad(() => listBeFilings());
  const [state, run] = useAction(reload);
  const [preview, setPreview] = useState(null);

  const actions = (r) => {
    const buttons = [];
    if (r.status === "DRAFT" || r.status === "VALIDATED") {
      buttons.push(
        <button key="v" type="button" className={btn} disabled={state.busy} onClick={() => {
          const day = ask("Intended submission date (YYYY-MM-DD) — the schema in force on that day is used");
          if (day) run(() => validateBeFiling(r.id, day), "Validation run; see the note.");
        }}>Validate</button>);
    }
    if (r.status === "VALIDATED") {
      buttons.push(<button key="a" type="button" className={btn} disabled={state.busy}
        onClick={() => run(() => approveBeFiling(r.id), "Filing approved.")}>Approve</button>);
    }
    if (r.status === "APPROVED") {
      buttons.push(<button key="t" type="button" className={btn} disabled={state.busy}
        onClick={() => run(() => transmitBeFiling(r.id), "Transmitted.")}>Transmit</button>);
      buttons.push(<button key="s" type="button" className={btn} disabled={state.busy} onClick={() => {
        const submissionRef = ask("Submission reference (from the authority channel)");
        if (!submissionRef) return;
        const mandateRef = ask("Mandate reference (optional)") || undefined;
        run(() => recordBeFilingSubmission(r.id, { submissionRef, mandateRef }), "Submission recorded.");
      }}>Record submission</button>);
    }
    if (r.status === "TRANSMITTED") {
      buttons.push(<button key="ok" type="button" className={btn} disabled={state.busy} onClick={() => {
        const receiptRef = ask("Receipt reference (acknowledgement)");
        if (receiptRef) run(() => recordBeFilingResponse(r.id, { outcome: "ACCEPTED", receiptRef }), "Acceptance recorded.");
      }}>Accepted</button>);
      buttons.push(<button key="ko" type="button" className={btn} disabled={state.busy} onClick={() => {
        const codes = ask("Rejection error codes (comma separated)");
        if (codes) {
          run(() => recordBeFilingResponse(r.id, { outcome: "REJECTED", errorCodes: codes.split(",") }),
            "Rejection recorded; payroll and payments are unchanged.");
        }
      }}>Rejected</button>);
    }
    if (r.formCode === "BELCOTAX" && r.kind === "ORIGINAL" && ["TRANSMITTED", "ACCEPTED", "SETTLED"].includes(r.status)) {
      buttons.push(<button key="c" type="button" className={btn} disabled={state.busy} onClick={() => {
        const reason = ask("Why is this fiche cancelled?");
        if (reason) run(() => cancelBeFiling(r.id, reason), "Cancellation built.");
      }}>Cancel fiche</button>);
    }
    return buttons.length ? <div className="flex flex-wrap gap-1">{buttons}</div> : "—";
  };

  const open = (r) => (r.formCode === "BELCOTAX" ? getBeEmployeeCopy(r.id).then((copy) => getBeFiling(r.id)
    .then((full) => setPreview({ ...full, employeeCopy: copy.rendition }))) : getBeFiling(r.id).then(setPreview))
    .catch((e) => run(() => Promise.reject(e)));

  return (
    <section className={card} data-testid="be-filings">
      <h3 className="text-[14px] font-semibold text-foreground">Filing centre</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        DRAFT → VALIDATED → APPROVED (second person) → TRANSMITTED → ACCEPTED / REJECTED → SETTLED. Transmission is
        refused until the authority channel is certified (gate G3); record the submission made in the authority portal.
        An accepted receipt is immutable.
      </p>
      <Messages state={state} error={error} />
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No Belgian filings yet."
          columns={[
            { label: "Form", render: (r) => (r.demo ? <span>{r.formCode} <strong className="text-error">DEMO</strong></span> : r.formCode) },
            { label: "Event", render: (r) => r.event || "—" },
            { label: "Period", key: "periodKey" }, { label: "Kind", render: (r) => `${r.kind} v${r.version}` },
            { label: "Status", key: "status" },
            { label: "Schema", render: (r) => r.schemaVersion || "—" },
            { label: "Note", render: (r) => r.validationNote || "—" },
            { label: "Due", render: (r) => r.dueOn || "not sourced" },
            { label: "Reference", render: (r) => r.receiptRef || r.submissionRef || "—" },
            { label: "Payload", render: (r) => <button type="button" className={btn} onClick={() => open(r)}>View</button> },
            { label: "Actions", render: actions },
          ]} />
      )}
      {preview && (
        <div className="mt-3" data-testid="be-filing-preview">
          <div className="flex items-center justify-between">
            <p className="text-[12px] font-semibold text-foreground">
              {preview.formCode} {preview.periodKey} v{preview.version} — hash {preview.payloadHash.slice(0, 12)}…
            </p>
            <button type="button" className={btn} onClick={() => setPreview(null)}>Close</button>
          </div>
          <pre className="mt-1 max-h-72 overflow-auto rounded-lg bg-surface-muted p-2 text-[11px] text-foreground">
            {preview.employeeCopy || preview.rendition}
          </pre>
          {preview.response && (
            <p className="mt-1 text-[12px] text-foreground-muted">Authority response: {JSON.stringify(preview.response)}</p>
          )}
        </div>
      )}
    </section>
  );
}

function Obligations() {
  const [rows, error, loading, reload] = useLoad(() => listBeObligations());
  const [variances, varianceError, , reloadVariances] = useLoad(() => listBeVariances());
  const [state, run] = useAction(() => { reload(); reloadVariances(); });

  const pay = (r) => {
    const amount = ask(`Amount paid for ${r.type} ${r.periodKey} (EUR)`);
    if (!amount) return;
    const paidOn = ask("Payment date (YYYY-MM-DD)");
    if (!paidOn) return;
    const reference = ask("Bank payment reference");
    if (reference) run(() => recordBeObligationPayment(r.id, { amount, paidOn, reference }), "Payment recorded.");
  };
  const advance = () => {
    const month = ask("Month of the ONSS advance (YYYY-MM)");
    if (!month) return;
    const amount = ask("Amount on the ONSS notice (EUR)");
    if (!amount) return;
    const noticeRef = ask("ONSS notice reference");
    if (noticeRef) run(() => recordBeOnssAdvance({ month, amount, noticeRef }), "Advance recorded.");
  };

  return (
    <section className={card} data-testid="be-obligations">
      <h3 className="text-[14px] font-semibold text-foreground">Obligations and reconciliation</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Acceptance by the authority and payment are tracked apart: an accepted declaration with an unpaid amount stays
        open. Each ONSS advance is its own obligation; the quarter carries the balance after the advances.
      </p>
      <Messages state={state} error={error || varianceError} />
      <button type="button" className={btn} disabled={state.busy} onClick={advance}>Record ONSS advance</button>
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty="No Belgian obligations yet."
          columns={[
            { label: "Obligation", key: "type" }, { label: "Period", key: "periodKey" },
            { label: "Acceptance", key: "acceptanceStatus" }, { label: "Due", key: "amountDue" },
            { label: "Paid", key: "paidAmount" }, { label: "Due on", render: (r) => r.dueOn || "not sourced" },
            { label: "Status", render: (r) => (r.open ? `${r.status} (open)` : r.status) },
            { label: "Actions", render: (r) => (r.status === "RECONCILED" ? "—" : (
              <div className="flex flex-wrap gap-1">
                <button type="button" className={btn} disabled={state.busy} onClick={() => pay(r)}>Record payment</button>
                <button type="button" className={btn} disabled={state.busy || r.status !== "PAID"}
                  onClick={() => run(() => reconcileBeObligation(r.id), "Obligation reconciled.")}>Reconcile</button>
              </div>
            )) },
          ]} />
      )}
      <div className="mt-3" data-testid="be-variances">
        <p className="text-[12px] font-semibold text-foreground">Variances</p>
        <Table rows={variances} empty="No variances."
          columns={[
            { label: "Obligation", render: (v) => `#${v.obligationId}` }, { label: "Kind", key: "kind" },
            { label: "Expected", key: "expected" }, { label: "Actual", key: "actual" },
            { label: "Difference", key: "difference" }, { label: "Status", key: "status" },
            { label: "Actions", render: (v) => (v.status !== "OPEN" ? (v.resolution || "—") : (
              <button type="button" className={btn} disabled={state.busy} onClick={() => {
                const resolution = ask("How is this difference explained? (a second person resolves it)");
                if (resolution) run(() => resolveBeVariance(v.id, resolution), "Variance resolved.");
              }}>Resolve</button>)) },
          ]} />
      </div>
    </section>
  );
}

export default function BEFilingSettlementPanel({ employees = [] }) {
  const [refreshKey, setRefreshKey] = useState(0);
  const bump = () => setRefreshKey((k) => k + 1);
  return (
    <div className="space-y-4" data-testid="be-filing-centre">
      <ExceptionQueue key={`x${refreshKey}`} />
      <Calendar />
      <Builders employees={employees} onBuilt={bump} />
      <Filings key={`f${refreshKey}`} />
      <Obligations key={`o${refreshKey}`} />
    </div>
  );
}
