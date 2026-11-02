import { useState } from "react";
import {
  calculateJpYeaCase, getJpSalaryPaymentReports, getJpWithholdingCertificate, listJpYeaCases, reviewJpYeaCase,
  applyJpYeaCase, voidJpYeaCase,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/japan/jpFormat";
import { Table } from "../../../components/jurisdiction/japan/jpShared";
import { btn } from "../../../components/jurisdiction/japan/JPRecordSection";
import { formatJpyAuto } from "../../../components/jurisdiction/japan/jpComponentConfig";

// Japan year-end adjustment (ZP-JP-ENG-001 §8, S3). OPEN -> CALCULATED ->
// REVIEWED (a second person) -> APPLIED to one open salary run -> LOCKED when
// that run is paid. Cases are opened from an employee's records; the
// calculation blocks until the year-end tables are signed (G1).

function errorText(e) {
  const detail = e?.response?.data?.detail;
  return typeof detail === "string" ? detail : "The action failed.";
}

function CaseRows({ year }) {
  const [rows, error, loading, reload] = useLoad(() => listJpYeaCases(year));
  const [runIds, setRunIds] = useState({});
  const [preview, setPreview] = useState(null);
  const [state, setState] = useState({ busy: false, error: null });
  const act = async (fn) => {
    setState({ busy: true, error: null });
    try {
      await fn();
      setState({ busy: false, error: null });
      reload();
    } catch (e) {
      setState({ busy: false, error: errorText(e) });
    }
  };
  return (
    <>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
      {loading ? <p className="text-[12px] text-foreground-muted">Loading…</p> : (
        <Table rows={rows} empty={`No year-end cases for ${year}.`}
          columns={[
            { label: "Employee", key: "employee_id" },
            { label: "State", render: (r) => `${r.state}${r.excluded_reason ? ` (${r.excluded_reason})` : ""}` },
            { label: "Pay", render: (r) => (r.annual_income == null ? "—" : formatJpyAuto(r.annual_income)) },
            { label: "Withheld", render: (r) => (r.tax_withheld == null ? "—" : formatJpyAuto(r.tax_withheld)) },
            { label: "Annual tax", render: (r) => (r.annual_tax == null ? "—" : formatJpyAuto(r.annual_tax)) },
            { label: "Difference", render: (r) => (r.difference == null ? "—"
              : `${formatJpyAuto(Math.abs(Number(r.difference)))} ${Number(r.difference) >= 0 ? "refund" : "to collect"}`) },
            {
              label: "Actions",
              render: (r) => (
                <div className="flex flex-wrap items-center gap-1">
                  {["OPEN", "CALCULATED", "EXCLUDED"].includes(r.state) && (
                    <button type="button" className={btn} disabled={state.busy} onClick={() => act(() => calculateJpYeaCase(r.id))}>Calculate</button>)}
                  {r.state === "CALCULATED" && (
                    <button type="button" className={btn} disabled={state.busy} onClick={() => act(() => reviewJpYeaCase(r.id))}>Review (second user)</button>)}
                  {r.state === "REVIEWED" && (
                    <>
                      <input className="w-20 rounded-lg border border-border bg-surface px-2 py-1 text-[12px]" placeholder="Run #"
                        value={runIds[r.id] || ""} onChange={(e) => setRunIds((v) => ({ ...v, [r.id]: e.target.value.replace(/\D/g, "") }))} />
                      <button type="button" className={btn} disabled={state.busy || !runIds[r.id]}
                        onClick={() => act(() => applyJpYeaCase(r.id, Number(runIds[r.id])))}>Apply to run</button>
                    </>)}
                  {["APPLIED", "LOCKED", "EXCLUDED"].includes(r.state) && (
                    <button type="button" className={btn} disabled={state.busy}
                      onClick={() => act(async () => setPreview(await getJpWithholdingCertificate(r.id)))}>Certificate</button>)}
                  {!["LOCKED", "VOID"].includes(r.state) && (
                    <button type="button" className={btn} disabled={state.busy} onClick={() => act(() => voidJpYeaCase(r.id))}>Void</button>)}
                </div>
              ),
            },
          ]} />
      )}
      {preview && (
        <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-surface-muted p-3 text-[11px]" data-testid="jp-yea-preview">
          {JSON.stringify(preview, null, 2)}
        </pre>
      )}
    </>
  );
}

export default function JPYearEndPanel() {
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [reports, setReports] = useState(null);
  const [error, setError] = useState(null);
  return (
    <section className={card} data-testid="jp-year-end">
      <h3 className="text-[14px] font-semibold text-foreground">Year-end adjustment</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Annual pay, withholding and social insurance come only from committed payslips. A case is calculated, reviewed
        by a second user and applied to one open salary run; the run must then be recalculated before approval.
      </p>
      <div className="mb-3 flex flex-wrap items-end gap-2">
        <label className="flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted">Tax year
          <input className="w-24 rounded-lg border border-border bg-surface px-2 py-1 text-[12px]" value={year}
            onChange={(e) => setYear(e.target.value.replace(/\D/g, "").slice(0, 4))} />
        </label>
        <button type="button" className={btn} disabled={year.length !== 4}
          onClick={async () => {
            setError(null);
            try { setReports(await getJpSalaryPaymentReports(year)); } catch (e) { setError(errorText(e)); }
          }}>Salary payment reports</button>
      </div>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {year.length === 4 && <CaseRows key={year} year={year} />}
      {reports && (
        <pre className="mt-3 max-h-72 overflow-auto rounded-lg bg-surface-muted p-3 text-[11px]" data-testid="jp-salary-reports">
          {JSON.stringify(reports, null, 2)}
        </pre>
      )}
    </section>
  );
}
