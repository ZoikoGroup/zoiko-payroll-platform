import { useState } from "react";
import {
  acceptZaParallelDifference, acceptZaParallelImport, explainZaParallelDifference, getZaParallelImport,
  importZaParallel, listZaParallelImports, withdrawZaParallelImport,
} from "../../../service/payrollService";
import { card, useLoad } from "../../../components/jurisdiction/southAfrica/zaFormat";
import { Table } from "../../../components/jurisdiction/southAfrica/zaShared";

// South Africa G6 parallel payroll cycles (ZP-ZA-ENG-001 §13; Phase 10; "ZA" —
// "SA" is Saudi Arabia). An incumbent payroll's results for a committed run are
// compared with Zoiko's frozen payslips (never recomputed). The server refuses
// identifier columns, enforces four-eyes on every acceptance and never calls a
// cycle clean until the owner's materiality threshold (decision D-4) is
// recorded. Nothing here changes a payslip. ETI is not compared: it is never an
// employee line.

const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const btn = "rounded-lg border border-border px-3 py-1.5 text-[12px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const btnPrimary = "rounded-lg bg-primary px-3 py-1.5 text-[12px] font-semibold text-white hover:opacity-90 disabled:opacity-40";
const labelCls = "flex flex-col gap-1 text-[11px] font-semibold text-foreground-muted";
const CONCEPTS = [
  ["gross", "Gross"], ["paye", "PAYE"], ["uif_employee", "UIF (employee)"], ["uif_employer", "UIF (employer)"],
  ["sdl", "SDL"], ["other_deductions", "Other deductions"], ["net", "Net pay"],
];

function useAction(onDone) {
  const [state, setState] = useState({ busy: false, error: null });
  const act = async (fn) => {
    setState({ busy: true, error: null });
    try {
      const out = await fn();
      setState({ busy: false, error: null });
      onDone?.(out);
      return out;
    } catch (e) {
      setState({ busy: false, error: e?.message || "The action failed." });
      return null;
    }
  };
  return [state, act];
}

function ImportForm({ onImported }) {
  const [form, setForm] = useState({ payrollRunId: "", sourceLabel: "", csv: "", employeeCode: "",
    ...Object.fromEntries(CONCEPTS.map(([k]) => [k, ""])) });
  const [state, act] = useAction(onImported);
  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));
  const headers = (form.csv.split(/\r?\n/)[0] || "").split(",").map((h) => h.trim()).filter(Boolean);
  const submit = () => act(() => importZaParallel({
    payrollRunId: Number(form.payrollRunId), sourceLabel: form.sourceLabel, csv: form.csv,
    columnMapping: Object.fromEntries([["employeeCode", form.employeeCode],
      ...CONCEPTS.map(([k]) => [k, form[k]]).filter(([, v]) => v)]),
  }));
  const pick = (k) => (
    <select className={input} value={form[k]} onChange={set(k)}>
      <option value="">—</option>
      {headers.map((h) => <option key={h} value={h}>{h}</option>)}
    </select>
  );
  return (
    <div className="space-y-2">
      <div className="grid grid-cols-2 gap-2 md:grid-cols-3">
        <label className={labelCls}>Committed run id
          <input className={input} value={form.payrollRunId} onChange={set("payrollRunId")} inputMode="numeric" />
        </label>
        <label className={labelCls}>Incumbent payroll / bureau
          <input className={input} value={form.sourceLabel} onChange={set("sourceLabel")} maxLength={120} />
        </label>
      </div>
      <label className={labelCls}>Incumbent results (CSV with a header row; employee code, no ID / tax / bank numbers)
        <textarea className={`${input} h-28 font-mono`} value={form.csv} onChange={set("csv")} />
      </label>
      {headers.length > 0 && (
        <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
          <label className={labelCls}>Employee code column{pick("employeeCode")}</label>
          {CONCEPTS.map(([k, l]) => <label key={k} className={labelCls}>{l}{pick(k)}</label>)}
        </div>
      )}
      <button type="button" className={btnPrimary} onClick={submit}
        disabled={state.busy || !form.payrollRunId || !form.sourceLabel || !form.csv || !form.employeeCode}>
        Import and compare
      </button>
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
    </div>
  );
}

function ImportDetail({ importId, onChanged }) {
  const [data, error, loading, reload] = useLoad(() => getZaParallelImport(importId));
  const [reasons, setReasons] = useState({});
  const [state, act] = useAction(() => { reload(); onChanged?.(); });
  if (loading) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  if (error) return <p role="alert" className="text-[12px] text-error">{error}</p>;
  const open = data.status === "OPEN";
  return (
    <div className="mt-2 space-y-2" data-testid="za-parallel-detail">
      <p className="text-[12px] text-foreground">
        {data.sourceLabel} · run #{data.payrollRunId} ({data.payDate}) · {data.matchedCount} matched,
        {" "}{data.unmatchedCount} unmatched · materiality {data.materiality ? `R${data.materiality}` : "not recorded"}
      </p>
      <p className={`text-[12px] ${data.clean ? "text-success" : "text-warning"}`} data-testid="za-parallel-clean">
        {data.clean ? "Clean — a second person may accept the cycle." : `Not clean: ${data.reason}`}
      </p>
      <Table rows={data.differences} empty="No differences." columns={[
        { label: "Employee", render: (d) => `#${d.employeeId}` },
        { label: "Concept", key: "concept" },
        { label: "Zoiko", key: "zoikoAmount" },
        { label: "Incumbent", key: "incumbentAmount" },
        { label: "Delta", key: "delta" },
        { label: "Status", key: "status" },
        { label: "Explanation", render: (d) => (open && d.status !== "ACCEPTED" ? (
          <div className="flex gap-1">
            <input className={input} value={reasons[d.id] ?? d.reason ?? ""}
              onChange={(e) => setReasons((r) => ({ ...r, [d.id]: e.target.value }))} />
            <button type="button" className={btn} disabled={state.busy || !(reasons[d.id] ?? "").trim()}
              onClick={() => act(() => explainZaParallelDifference(d.id, reasons[d.id]))}>Explain</button>
            {d.status === "EXPLAINED" && (
              <button type="button" className={btn} disabled={state.busy}
                onClick={() => act(() => acceptZaParallelDifference(d.id))}>Accept</button>
            )}
          </div>
        ) : (d.reason || "—")) },
      ]} />
      {open && (
        <div className="flex gap-2">
          <button type="button" className={btnPrimary} disabled={state.busy || !data.clean}
            onClick={() => act(() => acceptZaParallelImport(importId))}>Accept cycle</button>
          <button type="button" className={btn} disabled={state.busy}
            onClick={() => act(() => withdrawZaParallelImport(importId))}>Withdraw</button>
        </div>
      )}
      {state.error && <p role="alert" className="text-[12px] text-error">{state.error}</p>}
    </div>
  );
}

export default function ZAParallelCyclesSection() {
  const [rows, error, , reload] = useLoad(() => listZaParallelImports());
  const [selected, setSelected] = useState(null);
  return (
    <section className={card} data-testid="za-parallel-cycles">
      <h3 className="text-[14px] font-semibold text-foreground">Parallel payroll cycles (release gate G6)</h3>
      <p className="mb-3 text-[12px] text-foreground-muted">
        Two accepted cycles in different pay months are required before South Africa can go live. Each difference
        is explained by one person and accepted by another; a cycle is accepted by someone other than its importer.
      </p>
      <ImportForm onImported={(out) => { reload(); if (out?.id) setSelected(out.id); }} />
      {error && <p role="alert" className="mt-2 text-[12px] text-error">{error}</p>}
      <div className="mt-3">
        <Table rows={rows || []} empty="No parallel cycles imported." columns={[
          { label: "Import", render: (r) => `#${r.id}` },
          { label: "Run", render: (r) => `#${r.payrollRunId}` },
          { label: "Source", key: "sourceLabel" },
          { label: "Status", key: "status" },
          { label: "Rows", render: (r) => `${r.matchedCount}/${r.rowCount}` },
          { label: "", render: (r) => (
            <button type="button" className={btn} onClick={() => setSelected(r.id)}>Open</button>
          ) },
        ]} />
      </div>
      {selected && <ImportDetail key={selected} importId={selected} onChanged={reload} />}
    </section>
  );
}
