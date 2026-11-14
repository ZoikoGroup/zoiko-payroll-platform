import { useState } from "react";
import { Download, FileSpreadsheet, Upload } from "lucide-react";
import { applyMyWorkbook, downloadMyWorkbook, previewMyWorkbook } from "../../../service/superAdminService";
import { inputClass, labelClass } from "../constants";
import { card } from "../japan/jpFormat";
import { Table } from "../japan/jpShared";
import { ErrorNote } from "../new_zealand/nzShared";
import { isEditablePack } from "./myContent";

// Import & verify (ZP-MY-ENG-001 decision D-2): download the workbook for this
// pack, fill it from the official documents (EPF Third Schedule, PERKESO / EIS
// schedules, gazetted holidays, ordinances), preview it, then apply it to the
// Draft pack. Applied rows are EXTRACTED (unsigned, "PENDING G1"); a second
// Super Admin signs them against the stored source before the pack can be
// approved. Nothing here can activate a pack.

const STATUS_STYLE = {
  CHANGED: "text-primary", UNCHANGED: "text-foreground-muted", MISSING: "text-warning", INVALID: "text-error",
};

export default function MYWorkbookTab({ pack }) {
  const [file, setFile] = useState(null);
  const [preview, setPreview] = useState(null);
  const [reason, setReason] = useState("");
  const [state, setState] = useState({ busy: false, error: null, applied: null });
  const editable = isEditablePack(pack);

  if (!pack) return <p className="text-[12px] text-foreground-muted">Select (or seed) a Malaysia pack first.</p>;

  const run = async (fn) => {
    setState({ busy: true, error: null, applied: null });
    try {
      await fn();
      setState((s) => ({ ...s, busy: false }));
    } catch (err) {
      setState({ busy: false, error: err.message || "The workbook was refused.", applied: null });
    }
  };

  const doPreview = () => run(async () => { setPreview(await previewMyWorkbook(pack.id, file)); });
  const doApply = () => run(async () => {
    const out = await applyMyWorkbook(pack.id, file, reason.trim());
    setPreview(out);
    setState({ busy: false, error: null, applied: out });
  });

  const summary = preview?.summary || {};
  const canApply = editable && preview && !preview.fatal?.length && !summary.INVALID && summary.CHANGED > 0 && reason.trim();
  return (
    <div className="space-y-4" data-testid="my-workbook">
      <div className={card}>
        <h3 className="mb-1 flex items-center gap-2 text-[14px] font-semibold text-foreground"><FileSpreadsheet size={16} /> Import &amp; verify</h3>
        <ol className="mb-3 list-decimal space-y-1 pl-5 text-[12px] text-foreground-secondary">
          <li>Download the workbook for {pack.packId} v{pack.version} (current values, empty schedules).</li>
          <li>Fill it only from the official documents, citing the source document and page on every row.</li>
          <li>Preview: every row is CHANGED, UNCHANGED, MISSING or INVALID. Nothing is written.</li>
          <li>Apply to the Draft pack (all or nothing). Applied rows are <strong>Extracted</strong> — still PENDING G1.</li>
          <li>A second Super Admin signs each row against its reviewed source (<strong>Verified</strong>).</li>
        </ol>
        <button type="button" onClick={() => run(() => downloadMyWorkbook(pack.id))} disabled={state.busy}
          className="inline-flex items-center gap-1 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
          <Download size={13} /> Download workbook
        </button>
      </div>
      <div className={card}>
        <label className={labelClass}>Filled workbook (.xlsx)</label>
        <input type="file" accept=".xlsx" className={inputClass} data-testid="my-workbook-file"
          onChange={(e) => { setFile(e.target.files?.[0] || null); setPreview(null); }} />
        <button type="button" onClick={doPreview} disabled={!file || state.busy}
          className="mt-2 inline-flex items-center gap-1 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
          <Upload size={13} /> Preview
        </button>
        <ErrorNote message={state.error} />
        {preview && (
          <div className="mt-4 space-y-3">
            {preview.fatal?.length > 0 && (
              <p className="rounded-lg border border-error/30 bg-error/5 p-2 text-[12px] text-error">{preview.fatal.join("; ")}</p>
            )}
            <p className="text-[12px] text-foreground">
              {["CHANGED", "UNCHANGED", "MISSING", "INVALID"].map((s) => (
                <span key={s} className={`mr-3 font-semibold ${STATUS_STYLE[s]}`}>{s}: {summary[s] || 0}</span>
              ))}
            </p>
            <Table rows={(preview.rows || []).filter((r) => r.status !== "UNCHANGED")} rowKey={(r) => `${r.sheet}:${r.ref}`}
              empty="Every row is unchanged." columns={[
                { label: "Sheet", render: (r) => r.sheet },
                { label: "Row", render: (r) => <span className="font-mono text-[11px]">{r.ref}</span> },
                { label: "Status", render: (r) => <span className={`font-semibold ${STATUS_STYLE[r.status]}`}>{r.status}</span> },
                { label: "Detail", render: (r) => r.detail || "—" },
              ]} />
            {editable ? (
              <div>
                <label className={labelClass}>Change reason *</label>
                <input className={inputClass} value={reason} onChange={(e) => setReason(e.target.value)}
                  placeholder="e.g. EPF Third Schedule 2026 loaded from the KWSP PDF" />
                <button type="button" onClick={doApply} disabled={!canApply || state.busy}
                  className="mt-2 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50">
                  Apply to Draft pack (rows stay unsigned)
                </button>
              </div>
            ) : (
              <p className="text-[12px] text-foreground-muted">{pack.status} pack — a workbook applies only to a Draft pack.</p>
            )}
            {state.applied && (
              <p className="text-[12px] text-success" role="status">
                Applied ({JSON.stringify(state.applied.written)}). Rows are Extracted — sign them in the tabs.
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
