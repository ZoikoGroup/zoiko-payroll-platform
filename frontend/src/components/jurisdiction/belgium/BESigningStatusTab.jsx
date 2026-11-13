import { useState } from "react";
import {
  bulkSignBeRows, downloadBeContentWorkbook, getBeConfiguration, getBeSigningStatus, importBeContentWorkbook,
} from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";

// What still blocks activation of the selected Belgium pack, straight from the
// backend (be_super_admin.signing_status): unsigned, empty and unsourced rows,
// NOT_SUPPORTED decisions, earning classes still REVIEW, and the editors /
// signers — who can never approve or activate this version (four-eyes).
// Block D3: export the content workbook for the Belgian specialist, import it
// back (dry-run preview of every changed cell, then confirm; Draft packs only;
// never signs), and bulk-sign selected pending rows (refused for the importer or
// any editor of those rows; each row audited on its own).

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
        XLSX. Import it back into a Draft pack: the dry run lists every changed cell; importing never signs.
      </p>
      <button type="button" className={btnCls} disabled={state.busy}
        onClick={() => run(() => downloadBeContentWorkbook(pack.id), "Workbook downloaded.")}>Export workbook</button>
      <div className="grid grid-cols-1 gap-2 md:grid-cols-3">
        <label className={labelClass}>Workbook (.xlsx)
          <input type="file" accept=".xlsx" onChange={(e) => { setFile(e.target.files?.[0] || null); setReport(null); }} />
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

function BulkSign({ pack }) {
  const [config, error, loading, reload] = useLoad(() => getBeConfiguration(pack.id));
  const [selected, setSelected] = useState({});
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ busy: false, error: null, notice: null });
  if (error) return <ErrorNote message={error} />;
  if (loading || !config) return null;
  const pending = [
    ...Object.values(config.groups).flatMap((g) => g.rows).filter((r) => !r.signed)
      .map((r) => ({ kind: "rate", id: r.id, label: r.componentKey })),
    ...Object.values(config.slabRows).flat().concat(config.earningClasses).filter((r) => !r.signed)
      .map((r) => ({ kind: "slab", id: r.id, label: `${r.ruleType} ${r.component || r.taxFormula || ""}`.trim() })),
  ];
  const chosen = pending.filter((r) => selected[`${r.kind}:${r.id}`]);
  const sign = async () => {
    setState({ busy: true, error: null, notice: null });
    try {
      const out = await bulkSignBeRows(pack.id, chosen.map(({ kind, id }) => ({ kind, id })), reason.trim());
      setState({ busy: false, error: null, notice: `Signed ${out.signed.length} row(s).` });
      setSelected({});
      reload();
    } catch (err) {
      setState({ busy: false, error: err.message || "Refused.", notice: null });
    }
  };
  return (
    <div className={`${card} space-y-2`} data-testid="be-bulk-sign">
      <h3 className="text-[14px] font-semibold text-foreground">Bulk sign ({pending.length} pending)</h3>
      <p className="text-[12px] text-foreground-secondary">
        Only a Super Admin who neither imported nor edited the selected rows can sign them; each row is signed with its
        own reviewed, archived source and audited on its own.
      </p>
      <div className="max-h-64 overflow-auto rounded-lg border border-border p-2">
        {pending.map((r) => (
          <label key={`${r.kind}:${r.id}`} className="flex items-center gap-2 text-[11px] text-foreground">
            <input type="checkbox" checked={!!selected[`${r.kind}:${r.id}`]}
              onChange={(e) => setSelected({ ...selected, [`${r.kind}:${r.id}`]: e.target.checked })} />
            <span className="font-mono">{r.kind} #{r.id}</span> {r.label}
          </label>
        ))}
      </div>
      <label className={labelClass}>Reason *
        <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)} />
      </label>
      <button type="button" className={btnCls} disabled={state.busy || !chosen.length || !reason.trim()} onClick={sign}>
        Sign {chosen.length} selected
      </button>
      <ErrorNote message={state.error} />
      {state.notice && <p role="status" className="text-[12px] text-success">{state.notice}</p>}
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
        : <p className="rounded-lg border border-success/40 bg-success/10 p-2 text-[12px] text-success">No content refusal (four-eyes and the release gates still apply).</p>}
      <KeyList title="Unsigned (PENDING G1)" keys={status.pendingRates} tone="text-warning" />
      <KeyList title="No value" keys={status.emptyValues} tone="text-warning" />
      <KeyList title="No source document" keys={status.unsourced} tone="text-warning" />
      <KeyList title="Signed NOT_SUPPORTED (feature blocked)" keys={status.notSupported} />
      <p className="text-[12px] text-foreground">Earning classes still REVIEW: <strong>{status.reviewClasses}</strong></p>
      <p className="text-[12px] text-foreground">
        Editors / signers of this version (never the approver or activator): {status.editors.length ? status.editors.join(", ") : "none yet"}
      </p>
    </div>
  );
}

export default function BESigningStatusTab({ pack }) {
  if (!pack) return <p className="text-[12px] text-foreground-muted">Select a Belgium pack.</p>;
  return (
    <div className="space-y-4">
      <Loaded key={pack.id} pack={pack} />
      <WorkbookPanel key={`w${pack.id}`} pack={pack} />
      <BulkSign key={`b${pack.id}`} pack={pack} />
    </div>
  );
}
