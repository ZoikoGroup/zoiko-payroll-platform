import { useCallback, useEffect, useState } from "react";
import {
  acceptMxParallelDifference, createMxParallelImport, explainMxParallelDifference, getMxParallelImport,
  listMxParallelImports, withdrawMxParallelImport,
} from "../../../service/payrollService";
import { input, Messages, Table, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";

const link = "text-[12px] text-primary underline disabled:opacity-40";
const CONCEPTS = ["net", "isr_withheld", "subsidy_applied", "imss_employee", "imss_employer", "retiro", "ceav_employee",
  "ceav_employer", "infonavit_employer", "infonavit_credit", "isn", "employer_total"];

// Parallel payroll (ZP-MX-ENG-001 §22 G8, final mile X4). The legacy payroll's
// results for a committed run are read from a CSV in the browser and sent as
// text with a column mapping; the server keeps only the mapping, the file's
// SHA-256 and the differences — never the file. Employees match by employee
// code: identifier columns or values are refused. Each difference is explained
// and then accepted by a second person; a cycle is "clean" only against the
// release owner's materiality threshold (D-25).
export default function MXParallelPayrollPanel() {
  const [imports, setImports] = useState([]);
  const [loadError, setLoadError] = useState(null);
  const [detail, setDetail] = useState(null);
  const [form, setForm] = useState({ runId: "", sourceLabel: "", csv: "", headers: [], mapping: {} });
  const [reasons, setReasons] = useState({});
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const { run, error, notice, busy } = useAction(reload);

  useEffect(() => {
    let active = true;
    listMxParallelImports()
      .then((d) => { if (active) { setImports(d); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The parallel imports could not be loaded."));
    return () => { active = false; };
  }, [tick]);

  useEffect(() => {
    let active = true;
    if (!detail?.id) return undefined;
    getMxParallelImport(detail.id).then((d) => active && setDetail(d)).catch(() => {});
    return () => { active = false; };
  }, [tick, detail?.id]);

  function readFile(e) {
    const file = e.target.files?.[0];
    if (!file) return;
    file.text().then((text) => {
      const headers = (text.replace(/^\uFEFF/, "").split(/\r?\n/)[0] || "").split(",").map((h) => h.trim());
      setForm((f) => ({ ...f, csv: text, headers, mapping: {} }));
    });
  }

  const setMap = (key) => (e) => setForm((f) => ({ ...f, mapping: { ...f.mapping, [key]: e.target.value } }));
  const mapping = Object.fromEntries(Object.entries(form.mapping).filter(([, v]) => v));

  async function submit(e) {
    e.preventDefault();
    let made = null;
    await run(async () => {
      made = await createMxParallelImport({
        run_id: Number(form.runId), source_label: form.sourceLabel, csv: form.csv, column_mapping: mapping,
      });
    }, "Imported — every difference is listed below.");
    if (made) setDetail(made);
  }

  const summary = detail?.summary;
  const clean = summary ? (summary.clean === null ? "NOT DECIDABLE (D-25 unset)" : summary.clean ? "CLEAN" : "NOT CLEAN") : null;

  return (
    <Panel title="Parallel payroll" testId="mx-parallel"
      hint="Compare a legacy payroll's results with a committed run (G8). Match by employee code only — files with RFC, CURP, NSS or CLABE are refused. The file is never stored.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      <Messages error={error} notice={notice} />

      <form className="flex flex-col gap-2" onSubmit={submit} aria-label="Parallel import" data-testid="mx-parallel-import">
        <div className="grid grid-cols-1 gap-2 sm:grid-cols-3">
          <input aria-label="Committed run id" className={input} placeholder="Committed run id" value={form.runId}
            onChange={(e) => setForm((f) => ({ ...f, runId: e.target.value }))} required />
          <input aria-label="Legacy system" className={input} placeholder="Legacy system (label)" value={form.sourceLabel}
            onChange={(e) => setForm((f) => ({ ...f, sourceLabel: e.target.value }))} required />
          <input aria-label="Legacy results CSV" type="file" accept=".csv,text/csv" className="text-[12px]" onChange={readFile} />
        </div>
        {form.headers.length > 0 && (
          <div className="grid grid-cols-2 gap-2 sm:grid-cols-4" data-testid="mx-parallel-mapping">
            {["employee_code", ...CONCEPTS].map((k) => (
              <label key={k} className="flex flex-col text-[11px] text-foreground-muted">
                {k}
                <select aria-label={`Column for ${k}`} className={input} value={form.mapping[k] || ""} onChange={setMap(k)}>
                  <option value="">— not mapped —</option>
                  {form.headers.map((h) => <option key={h} value={h}>{h}</option>)}
                </select>
              </label>
            ))}
          </div>
        )}
        <button type="submit" className={link} disabled={busy || !form.csv || !mapping.employee_code}>Import and compare</button>
      </form>

      <Table rows={imports} empty="No parallel cycle yet." columns={[
        { key: "id", label: "Import", render: (i) => `#${i.id}` },
        { key: "runId", label: "Run", render: (i) => `#${i.runId}` },
        { key: "sourceLabel", label: "Legacy system" },
        { key: "status", label: "Status", render: (i) => <Badge value={i.status} /> },
        { key: "rowCount", label: "Rows" },
        { key: "open", label: "Unexplained", render: (i) => i.summary.states.UNEXPLAINED },
        { key: "act", label: "", render: (i) => (
          <button type="button" className={link} onClick={() => setDetail({ id: i.id })}>Open</button>
        ) },
      ]} />

      {summary && (
        <div className="flex flex-col gap-2" data-testid="mx-parallel-detail">
          <p className="flex flex-wrap items-center gap-2 text-[12px] text-foreground-muted">
            Import #{detail.id} · run #{detail.runId} · {detail.sourceLabel} · SHA-256 {detail.fileSha256.slice(0, 12)}… ·
            match {summary.states.MATCH} · unexplained {summary.states.UNEXPLAINED} · explained {summary.states.EXPLAINED} ·
            accepted {summary.states.ACCEPTED} · <Badge value={clean} />
          </p>
          {summary.note && <p className="text-[12px] text-warning" data-testid="mx-parallel-note">{summary.note}</p>}
          {(detail.unmatched?.legacyOnly?.length > 0 || detail.unmatched?.zoikoOnly?.length > 0) && (
            <p className="text-[12px] text-error">
              Unmatched — only in the legacy file: {detail.unmatched.legacyOnly.join(", ") || "none"}; only in Zoiko:
              {" "}{detail.unmatched.zoikoOnly.join(", ") || "none"}
            </p>
          )}
          <Table rows={detail.differences} empty="No matched employee." columns={[
            { key: "employee", label: "Employee" }, { key: "concept", label: "Concept" },
            { key: "legacy", label: "Legacy" }, { key: "zoiko", label: "Zoiko" }, { key: "delta", label: "Delta" },
            { key: "state", label: "State", render: (d) => <Badge value={d.state} /> },
            { key: "reason", label: "Reason", render: (d) => d.reason || "" },
            { key: "act", label: "", render: (d) => (detail.status !== "CURRENT" ? "" : d.state === "UNEXPLAINED" ? (
              <span className="flex items-center gap-2">
                <input aria-label={`Reason ${d.id}`} placeholder="why it differs" className="rounded border border-border px-1 text-[12px]"
                  value={reasons[d.id] || ""} onChange={(e) => setReasons((r) => ({ ...r, [d.id]: e.target.value }))} />
                <button type="button" className={link} disabled={busy}
                  onClick={() => run(() => explainMxParallelDifference(d.id, reasons[d.id]), "Explained — a second person accepts it.")}>
                  Explain
                </button>
              </span>
            ) : d.state === "EXPLAINED" ? (
              <button type="button" className={link} disabled={busy}
                onClick={() => run(() => acceptMxParallelDifference(d.id), "Accepted.")}>Accept (another person)</button>
            ) : "") },
          ]} />
          {detail.status === "CURRENT" && (
            <button type="button" className="self-start text-[12px] text-foreground-muted underline" disabled={busy}
              onClick={() => run(() => withdrawMxParallelImport(detail.id), "Import withdrawn.")}>Withdraw this import</button>
          )}
        </div>
      )}
    </Panel>
  );
}
