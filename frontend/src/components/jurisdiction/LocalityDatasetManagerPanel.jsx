import { useState, useEffect, useCallback } from "react";
import { Upload, ChevronRight, ChevronDown, Trash2, Plus } from "lucide-react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import {
  getLocalityDatasets, getLocalityDatasetRates, importLocalityDataset, diffLocalityDataset,
  stageLocalityDataset, approveLocalityDataset, activateLocalityDataset, rollbackLocalityDataset,
  getSourceArtifacts,
} from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

// The real Draft/Staged/Active/Retired import/diff/stage/approve/activate/
// rollback workflow ZP-TAX-US-2026-001 §10's own "LOCALITY DATASET POLICY"
// box and §11.1's "Locality Dataset Manager" module both require —
// alongside (not replacing) the simpler one-row-at-a-time LocalityRatesPanel
// above, which stays for quick manual edits. Currently only exercised with
// synthetic/test data — no real locality file (Indiana's 92 counties, PA's
// PSD registry, ...) has been supplied yet; this panel is what Tax Ops will
// use to import one once it arrives.

const STATUS_STYLES = {
  Draft: "bg-surface-muted text-foreground-secondary",
  Staged: "bg-warning-light text-warning",
  Active: "bg-success-light text-success",
  Retired: "bg-surface-muted text-foreground-disabled",
};

export default function LocalityDatasetManagerPanel() {
  const { addToast } = useToast() || {};
  const [state, setState] = useState("");
  const [datasets, setDatasets] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showImport, setShowImport] = useState(false);
  const [diffTarget, setDiffTarget] = useState(null);
  const [expandedId, setExpandedId] = useState(null);
  const [busyId, setBusyId] = useState(null);

  const load = useCallback(() => {
    if (!state.trim()) { setDatasets([]); return; }
    setLoading(true);
    getLocalityDatasets({ country: "US", state: state.trim().toUpperCase() })
      .then(setDatasets)
      .finally(() => setLoading(false));
  }, [state]);

  useEffect(() => { load(); }, [load]);

  async function runAction(fn, id, successMsg) {
    setBusyId(id);
    try {
      await fn(id);
      addToast?.(successMsg, "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Action failed.", "error");
    } finally {
      setBusyId(null);
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4">
        <h2 className="text-lg font-bold text-foreground">Locality Dataset Manager</h2>
        <p className="mt-0.5 text-xs text-foreground-muted">
          Import a signed, versioned locality rate file as a Draft, diff it against the currently Active dataset,
          then Stage → Approve (a different Super Admin) → Activate. Only one dataset is ever Active per state —
          activating retires whichever one it replaces, and a Retired dataset can be rolled back. See ZP-TAX-US-2026-001 §10/§11.1.
        </p>
      </div>

      <div className="mb-4 flex flex-wrap items-center gap-3">
        <input
          className={inputClass + " w-auto min-w-[160px]"}
          value={state}
          onChange={(e) => setState(e.target.value.toUpperCase())}
          placeholder="State, e.g. IN"
          maxLength={2}
        />
        <button
          onClick={() => setShowImport(true)}
          disabled={!state.trim()}
          className="ml-auto flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          <Upload size={14} /> Import Dataset
        </button>
      </div>

      {!state.trim() ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Enter a state to view its locality datasets.</p>
      ) : loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : datasets.length === 0 ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">No datasets imported for this state yet.</p>
      ) : (
        <div className="space-y-2">
          {datasets.map((d) => (
            <div key={d.id} className="rounded-lg border border-border-light">
              <div className="flex items-center gap-3 p-3">
                <button onClick={() => setExpandedId(expandedId === d.id ? null : d.id)} className="text-foreground-muted">
                  {expandedId === d.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                </button>
                <div className="flex-1">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-sm font-medium text-foreground">{d.version}</span>
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${STATUS_STYLES[d.status] || "bg-surface-muted text-foreground-secondary"}`}>{d.status}</span>
                  </div>
                  <p className="mt-0.5 text-xs text-foreground-muted">
                    {d.rateCount ?? "?"} rate{d.rateCount === 1 ? "" : "s"} · effective {d.effectiveFrom || "unset"}
                    {d.checksumSha256 && <> · <span className="font-mono">{d.checksumSha256.slice(0, 12)}…</span></>}
                  </p>
                </div>
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setDiffTarget(d)}
                    className="rounded-md border border-border px-2.5 py-1 text-xs text-foreground-secondary hover:bg-surface-muted"
                  >
                    Diff vs. Active
                  </button>
                  {d.status === "Draft" && (
                    <button disabled={busyId === d.id} onClick={() => runAction(stageLocalityDataset, d.id, "Staged.")} className="rounded-md bg-surface-muted px-2.5 py-1 text-xs font-medium text-foreground hover:bg-border-light disabled:opacity-50">Stage</button>
                  )}
                  {d.status === "Staged" && !d.approvedById && (
                    <button disabled={busyId === d.id} onClick={() => runAction(approveLocalityDataset, d.id, "Approved.")} className="rounded-md bg-warning-light px-2.5 py-1 text-xs font-medium text-warning hover:opacity-80 disabled:opacity-50">Approve</button>
                  )}
                  {d.status === "Staged" && (
                    <button disabled={busyId === d.id} onClick={() => runAction(activateLocalityDataset, d.id, "Activated.")} className="rounded-md bg-primary px-2.5 py-1 text-xs font-medium text-white hover:bg-primary-hover disabled:opacity-50">Activate</button>
                  )}
                  {d.status === "Retired" && (
                    <button disabled={busyId === d.id} onClick={() => runAction(rollbackLocalityDataset, d.id, "Rolled back to Active.")} className="rounded-md border border-border px-2.5 py-1 text-xs font-medium text-foreground-secondary hover:bg-surface-muted disabled:opacity-50">Roll Back</button>
                  )}
                </div>
              </div>
              {expandedId === d.id && <DatasetRateList datasetId={d.id} />}
            </div>
          ))}
        </div>
      )}

      {showImport && (
        <ImportDatasetModal
          state={state.trim().toUpperCase()}
          onClose={() => setShowImport(false)}
          onImported={() => { setShowImport(false); load(); }}
        />
      )}
      {diffTarget && <DiffModal dataset={diffTarget} onClose={() => setDiffTarget(null)} />}
    </div>
  );
}

function DatasetRateList({ datasetId }) {
  const [rows, setRows] = useState(null);
  useEffect(() => {
    getLocalityDatasetRates(datasetId).then(setRows).catch(() => setRows([]));
  }, [datasetId]);
  if (rows === null) return <p className="px-4 pb-3 text-xs text-foreground-disabled">Loading rows…</p>;
  if (rows.length === 0) return <p className="px-4 pb-3 text-xs text-foreground-disabled">No rate rows.</p>;
  return (
    <div className="overflow-x-auto border-t border-border-light px-4 py-3">
      <table className="w-full text-xs">
        <thead>
          <tr className="text-left text-foreground-muted">
            <th className="pb-1.5 pr-3">Code</th>
            <th className="pb-1.5 pr-3">Type</th>
            <th className="pb-1.5 pr-3">Resident %</th>
            <th className="pb-1.5 pr-3">Nonresident %</th>
            <th className="pb-1.5 pr-3">Flat Amount</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.id} className="border-t border-border-light">
              <td className="py-1.5 pr-3 font-mono text-foreground">{r.localityCode}</td>
              <td className="py-1.5 pr-3">{r.localityType}</td>
              <td className="py-1.5 pr-3">{r.residentRatePct != null ? `${r.residentRatePct}%` : "—"}</td>
              <td className="py-1.5 pr-3">{r.nonresidentRatePct != null ? `${r.nonresidentRatePct}%` : "—"}</td>
              <td className="py-1.5 pr-3">{r.flatAmount != null ? r.flatAmount : "—"}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DiffModal({ dataset, onClose }) {
  const [diff, setDiff] = useState(null);
  const [error, setError] = useState(null);
  useEffect(() => {
    diffLocalityDataset(dataset.id).then(setDiff).catch((err) => setError(err.message || "Failed to load diff."));
  }, [dataset.id]);
  return (
    <Modal title={`Diff — ${dataset.version}`} onClose={onClose} maxWidth="max-w-lg">
      {error ? (
        <p className="text-xs text-error">{error}</p>
      ) : !diff ? (
        <p className="text-xs text-foreground-disabled">Loading…</p>
      ) : (
        <div className="space-y-3 text-xs">
          <p className="text-foreground-muted">
            Compared against {diff.comparedAgainstVersion ? <span className="font-mono">{diff.comparedAgainstVersion}</span> : "no Active dataset (nothing to compare)"}.
          </p>
          <DiffSection label="Added" items={diff.added} tone="text-success" />
          <DiffSection label="Removed" items={diff.removed} tone="text-error" />
          {diff.changed.length > 0 && (
            <div>
              <p className="mb-1 font-semibold text-foreground">Changed ({diff.changed.length})</p>
              <div className="space-y-1.5">
                {diff.changed.map((c) => (
                  <div key={c.localityCode} className="rounded-md bg-surface-muted p-2">
                    <p className="font-mono font-medium text-foreground">{c.localityCode}</p>
                    {Object.entries(c.changes).map(([field, v]) => (
                      <p key={field} className="text-foreground-muted">
                        {field}: <span className="font-mono">{v.before ?? "—"}</span> → <span className="font-mono">{v.after ?? "—"}</span>
                      </p>
                    ))}
                  </div>
                ))}
              </div>
            </div>
          )}
          {diff.added.length === 0 && diff.removed.length === 0 && diff.changed.length === 0 && (
            <p className="text-foreground-disabled">No differences.</p>
          )}
        </div>
      )}
    </Modal>
  );
}

function DiffSection({ label, items, tone }) {
  if (!items.length) return null;
  return (
    <div>
      <p className={`mb-1 font-semibold ${tone}`}>{label} ({items.length})</p>
      <p className="font-mono text-foreground-muted">{items.join(", ")}</p>
    </div>
  );
}

const EMPTY_ROW = { localityCode: "", localityType: "MUNICIPAL", localityName: "", residentRatePct: "", nonresidentRatePct: "", flatAmount: "" };

function ImportDatasetModal({ state, onClose, onImported }) {
  const { addToast } = useToast() || {};
  const [version, setVersion] = useState("");
  const [effectiveFrom, setEffectiveFrom] = useState("");
  const [sourceDocumentId, setSourceDocumentId] = useState("");
  const [sources, setSources] = useState([]);
  const [rows, setRows] = useState([{ ...EMPTY_ROW }]);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getSourceArtifacts().then(setSources).catch(() => setSources([]));
  }, []);

  function updateRow(i, field, value) {
    setRows((rs) => rs.map((r, idx) => (idx === i ? { ...r, [field]: value } : r)));
  }

  async function save() {
    if (!version.trim()) { addToast?.("Version label is required.", "error"); return; }
    const cleanRows = rows.filter((r) => r.localityCode.trim());
    if (cleanRows.length === 0) { addToast?.("At least one row with a locality code is required.", "error"); return; }
    setSaving(true);
    try {
      await importLocalityDataset({
        jurisdictionCountry: "US", jurisdictionState: state, version: version.trim(),
        effectiveFrom: effectiveFrom || null,
        sourceDocumentId: sourceDocumentId ? Number(sourceDocumentId) : null,
        rows: cleanRows.map((r) => ({
          localityCode: r.localityCode.trim(), localityType: r.localityType,
          localityName: r.localityName || null,
          residentRatePct: r.residentRatePct === "" ? null : r.residentRatePct,
          nonresidentRatePct: r.nonresidentRatePct === "" ? null : r.nonresidentRatePct,
          flatAmount: r.flatAmount === "" ? null : r.flatAmount,
        })),
      });
      addToast?.("Dataset imported as Draft.", "success");
      onImported();
    } catch (err) {
      addToast?.(err.message || "Import failed.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={`Import Locality Dataset — ${state}`} onClose={onClose} maxWidth="max-w-3xl">
      <div className="grid grid-cols-3 gap-3">
        <div><label className={labelClass}>Version Label</label><input className={inputClass} value={version} onChange={(e) => setVersion(e.target.value)} placeholder="e.g. IN-DN1-2026" /></div>
        <div><label className={labelClass}>Effective From (set before Activate)</label><input type="date" className={inputClass} value={effectiveFrom} onChange={(e) => setEffectiveFrom(e.target.value)} /></div>
        <div>
          <label className={labelClass}>Source Evidence (optional)</label>
          <select className={inputClass} value={sourceDocumentId} onChange={(e) => setSourceDocumentId(e.target.value)}>
            <option value="">No source linked</option>
            {sources.map((s) => <option key={s.id} value={s.id}>{s.agency} — {s.title}</option>)}
          </select>
        </div>
      </div>

      <div className="mt-4">
        <div className="mb-2 flex items-center justify-between">
          <label className={labelClass}>Rate Rows</label>
          <button onClick={() => setRows((rs) => [...rs, { ...EMPTY_ROW }])} className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-xs text-foreground-secondary hover:bg-surface-muted">
            <Plus size={12} /> Add Row
          </button>
        </div>
        <div className="max-h-64 space-y-2 overflow-y-auto">
          {rows.map((r, i) => (
            <div key={i} className="grid grid-cols-12 items-center gap-1.5">
              <input className={inputClass + " col-span-3"} placeholder="Locality code" value={r.localityCode} onChange={(e) => updateRow(i, "localityCode", e.target.value)} />
              <select className={inputClass + " col-span-2"} value={r.localityType} onChange={(e) => updateRow(i, "localityType", e.target.value)}>
                <option value="COUNTY">County</option>
                <option value="MUNICIPAL">Municipal</option>
                <option value="SCHOOL_DISTRICT">School Dist.</option>
                <option value="PSD_EIT_LST">PSD EIT/LST</option>
              </select>
              <input className={inputClass + " col-span-2"} placeholder="Name (optional)" value={r.localityName} onChange={(e) => updateRow(i, "localityName", e.target.value)} />
              <input className={inputClass + " col-span-2"} placeholder="Resident %" value={r.residentRatePct} onChange={(e) => updateRow(i, "residentRatePct", e.target.value)} />
              <input className={inputClass + " col-span-2"} placeholder="Nonresident %" value={r.nonresidentRatePct} onChange={(e) => updateRow(i, "nonresidentRatePct", e.target.value)} />
              <button onClick={() => setRows((rs) => rs.filter((_, idx) => idx !== i))} disabled={rows.length === 1} className="col-span-1 rounded-md p-1.5 text-error hover:bg-error-light disabled:opacity-30">
                <Trash2 size={13} />
              </button>
            </div>
          ))}
        </div>
      </div>

      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Importing…" : "Import as Draft"}</button>
      </div>
    </Modal>
  );
}
