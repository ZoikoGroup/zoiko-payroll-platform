import { useState } from "react";
import {
  downloadBeContentWorkbook, downloadBeImportTemplate, getBeSigningStatus,
  importBeContentWorkbook,
} from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";

// Missing content of the selected Belgium pack, straight from the backend
// (be_super_admin.signing_status): rows with no value, NOT_SUPPORTED decisions
// and earning classes still REVIEW. There is no signing step since the gate
// removal (owner decision 2026-11-25): a saved value is in force.
// Block D3: export the content workbook for the Belgian specialist and import it
// back (dry-run preview of every changed cell, then confirm; Draft packs only).

const btnCls = "rounded-lg border border-border px-3 py-1.5 text-[12px] disabled:opacity-50";

function WorkbookPanel({ pack }) {
  const [file, setFile] = useState(null);
  const [reason, setReason] = useState("");
  const [report, setReport] = useState(null);
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  const run = async (fn, notice) => {
    setState({ busy: true, error: null, notice: null });
    try {
      const out = await fn();
      setState({ busy: false, error: null, notice: typeof notice === "function" ? notice(out) : notice });
      return out;
    } catch (err) {
      setState({ busy: false, error: err.message || "Refused.", notice: null });
      return null;
    }
  };
  const preview = async () => {
    const out = await run(() => importBeContentWorkbook(pack.id, file, reason.trim(), true),
      (o) => `Dry run: ${o.changes} change(s), ${o.errors} error(s). Nothing was written.`);
    if (out) setReport(out);
  };
  const confirm = async () => {
    const out = await run(() => importBeContentWorkbook(pack.id, file, reason.trim(), false),
      (o) => (o.written ? `Imported ${o.changes} change(s) as UNSIGNED rows.` : `Nothing written: ${o.errors} error(s).`));
    if (out) setReport(out);
  };
  const draft = pack.status === "Draft";
  return (
    <div className={`${card} space-y-2`} data-testid="be-content-workbook">
      <h3 className="text-[14px] font-semibold text-foreground">Content workbook (specialist intake)</h3>
      <p className="text-[12px] text-foreground-secondary">
        Export every key, slab, earning class, schema version, tolerance, calendar template, decision and source to
        XLSX. Import it back — or rate / slab rows as CSV or JSON (see the template) — into a Draft pack: the dry
        run lists every changed cell and every problem (missing columns, a rate above 100 %, overlapping brackets,
        a row without a source); nothing is written unless every row passes, and importing never signs.
      </p>
      <button type="button" className={btnCls} disabled={state.busy}
        onClick={() => run(() => downloadBeContentWorkbook(pack.id), "Workbook downloaded.")}>Export workbook</button>
      <span className="ml-2 text-[12px] text-foreground-muted">or a blank file to fill in:</span>
      <button type="button" className={`${btnCls} ml-2`} disabled={state.busy} data-testid="be-template-csv"
        onClick={() => run(() => downloadBeImportTemplate("csv"), "CSV template downloaded.")}>CSV template</button>
      <button type="button" className={`${btnCls} ml-2`} disabled={state.busy} data-testid="be-template-json"
        onClick={() => run(() => downloadBeImportTemplate("json"), "JSON template downloaded.")}>JSON template</button>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        <label className={labelClass}>Workbook (.xlsx)
          <input type="file" accept=".xlsx,.csv,.json" onChange={(e) => { setFile(e.target.files?.[0] || null); setReport(null); }} />
        </label>
        <label className={labelClass}>Reason *
          <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
        </label>
        <div className="flex items-end gap-2">
          <button type="button" className={btnCls} disabled={state.busy || !draft || !file || !reason.trim()}
            onClick={preview}>Dry run</button>
          <button type="button" className={btnCls}
            disabled={state.busy || !report || !report.dryRun || report.errors > 0 || report.changes === 0}
            onClick={confirm} data-testid="be-workbook-confirm">Confirm import</button>
        </div>
      </div>
      {!draft && <p className="text-[12px] text-warning">Imports go into a Draft pack only.</p>}
      <ErrorNote message={state.error} />
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
      {report && report.items.length > 0 && (
        <table className="w-full text-[11px]" data-testid="be-workbook-report">
          <thead><tr className="text-left text-foreground-muted"><th>Cell</th><th>Key</th><th>Status</th><th>Detail</th></tr></thead>
          <tbody>
            {report.items.map((i, n) => (
              <tr key={`${i.cell}-${n}`} className={i.status === "ERROR" ? "text-error" : "text-foreground"}>
                <td className="font-mono">{i.cell}</td><td>{i.key || ""}</td><td>{i.status}</td><td>{i.reason}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}


function KeyList({ title, keys, tone = "text-foreground" }) {
  return (
    <div>
      <h4 className="mb-1 text-[12px] font-semibold text-foreground">{title} ({keys.length})</h4>
      {keys.length === 0 ? <p className="text-[11px] text-foreground-muted">None.</p> : (
        <p className={`font-mono text-[11px] ${tone}`}>{keys.join(", ")}</p>
      )}
    </div>
  );
}

function Loaded({ pack }) {
  const [status, error] = useLoad(() => getBeSigningStatus(pack.id));
  if (error) return <ErrorNote message={error} />;
  if (!status) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  return (
    <div className={`${card} space-y-3`} data-testid="be-signing-status">
      <h3 className="text-[14px] font-semibold text-foreground">{status.packId} v{status.version} — {status.status}</h3>
      {status.activationRefusal
        ? <p className="rounded-lg border border-warning/40 bg-warning/10 p-2 text-[12px] text-warning">{status.activationRefusal}</p>
        : <p className="rounded-lg border border-success/40 bg-success/10 p-2 text-[12px] text-success">Nothing blocks activation: approve (a Super Admin other than its last editor), then Activate.</p>}
      <p className="text-[12px] text-foreground-muted">
        Each missing value blocks only the calculation that needs it, with a named reason.
      </p>
      <KeyList title="No value yet" keys={status.emptyValues} tone="text-warning" />
      <KeyList title="Set NOT_SUPPORTED (feature blocked)" keys={status.notSupported} />
      <p className="text-[12px] text-foreground">Earning classes still REVIEW: <strong>{status.reviewClasses}</strong></p>
    </div>
  );
}

export default function BESigningStatusTab({ pack }) {
  if (!pack) return <p className="text-[12px] text-foreground-muted">Select a Belgium pack.</p>;
  return (
    <div className="space-y-4">
      <Loaded key={pack.id} pack={pack} />
      <WorkbookPanel key={`w${pack.id}`} pack={pack} />
    </div>
  );
}
