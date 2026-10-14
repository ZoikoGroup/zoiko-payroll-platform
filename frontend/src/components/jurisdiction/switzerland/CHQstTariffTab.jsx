import { useEffect, useState } from "react";
import { Download, Eye, FileUp, ShieldCheck, Zap, FileSearch } from "lucide-react";
import {
  importSwissQstTariffFile, listSwissQstTariffFiles, validateSwissQstTariffFile,
  approveSwissQstTariffFile, activateSwissQstTariffFile, getSwissQstTariffFile,
  getSwissQstTariffAffectedPayslips,
} from "../../../service/superAdminService";
import StatusPill from "../../StatusPill";
import { inputClass, labelClass } from "../constants";
import { CH_CANTONS, CH_QST_FORMAT_VERSIONS } from "./chComponentConfig";

const QST_STATUS_PILL = { ACTIVE: "active", APPROVED: "approved", REJECTED: "rejected" };
const STATUS_ORDER = ["IMPORTED", "VALIDATED", "APPROVED", "ACTIVE"];

// The Quellensteuer (QST) tariff-file registry — ZP-CH-PAYROLL-001 Step 4.
// An authority tariff file is imported byte-for-byte, then validated,
// approved (not by its importer) and activated (not by its approver).
// Tariff rows are never edited or deleted here — a changed tariff is a new
// file. The action each status offers is exactly the next lifecycle step;
// SHAs make an identical re-import impossible.
const EMPTY_FORM = {
  canton: "", formatVersion: CH_QST_FORMAT_VERSIONS[0], effectiveFrom: "", effectiveTo: "",
  taxYear: "", publicationDate: "", sourceDocumentId: "", fileName: "",
};

export default function CHQstTariffTab({ addToast }) {
  const [files, setFiles] = useState([]);
  const [form, setForm] = useState(EMPTY_FORM);
  const [importing, setImporting] = useState(false);
  const [error, setError] = useState(null);
  const [detail, setDetail] = useState(null);
  const [affected, setAffected] = useState(null);
  // The lifecycle action in flight; its optional reason is entered inline.
  const [confirming, setConfirming] = useState(null);
  const [reason, setReason] = useState("");

  const load = () => {
    listSwissQstTariffFiles()
      .then(setFiles)
      .catch((e) => setError(e?.message || "Failed to load tariff files."));
  };
  useEffect(() => { load(); }, []);

  async function runImport() {
    if (!form.canton || !form.effectiveFrom || !form.fileName) {
      setError("Canton, effective-from and a file are required."); return;
    }
    setImporting(true); setError(null);
    try {
      await importSwissQstTariffFile({
        canton: form.canton, formatVersion: form.formatVersion, effectiveFrom: form.effectiveFrom,
        effectiveTo: form.effectiveTo || undefined, taxYear: form.taxYear || undefined,
        publicationDate: form.publicationDate || undefined,
        sourceDocumentId: form.sourceDocumentId || undefined, file: form.file,
      });
      addToast?.("Tariff file imported.", "success");
      setForm(EMPTY_FORM);
      load();
    } catch (e) {
      setError(e?.message || "Import failed.");
    } finally {
      setImporting(false);
    }
  }

  async function runAction(file) {
    const { action } = confirming;
    setError(null);
    try {
      let text = "";
      if (action === "validate") { await validateSwissQstTariffFile(file.id); text = "Tariff validated."; }
      if (action === "approve") { await approveSwissQstTariffFile(file.id, reason || null); text = "Tariff approved."; }
      if (action === "activate") { await activateSwissQstTariffFile(file.id, reason || null); text = "Tariff activated."; }
      addToast?.(text, "success");
      setConfirming(null); setReason("");
      load();
    } catch (e) {
      setError(e?.message || "Action failed.");
    }
  }

  async function openDetail(file) {
    setError(null);
    setAffected(null);
    try {
      if (!detail || detail.id !== file.id) setDetail(await getSwissQstTariffFile(file.id));
      else setDetail(null);
    } catch (e) { setError(e?.message || "Failed to load the tariff file."); }
  }

  async function openAffected(file) {
    setError(null);
    setDetail(null);
    try {
      setAffected(affected?.tariffFileId === file.id ? null : await getSwissQstTariffAffectedPayslips(file.id));
    } catch (e) { setError(e?.message || "Failed to load affected payslips."); }
  }

  const nextStepFor = (file) => {
    if (file.status === "IMPORTED") return { action: "validate", label: "Validate", icon: FileSearch };
    if (file.status === "VALIDATED") return { action: "approve", label: "Approve", icon: ShieldCheck };
    if (file.status === "APPROVED") return { action: "activate", label: "Activate", icon: Zap };
    return null;
  };

  return (
    <section aria-labelledby="ch-qst-heading" className="space-y-6">
      <div>
        <h3 id="ch-qst-heading" className="text-sm font-semibold text-foreground">Quellensteuer tariff files</h3>
        <p className="text-xs text-foreground-muted">
          ESTV source-tax tariffs are imported unmodified (SHA-256 identity — an identical file for a canton is refused)
          and move IMPORTED → VALIDATED → APPROVED → ACTIVE by distinct Super Admins. A canton's overlapping ACTIVE
          files are superseded on activation; nothing here is ever recalculated automatically.
        </p>
      </div>

      <div className="rounded-xl border border-border p-4">
        <p className="mb-3 flex items-center gap-1.5 text-xs font-semibold text-foreground"><FileUp size={13} /> Import a canton&apos;s tariff file</p>
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-4">
          <div>
            <label className={labelClass} htmlFor="ch-qst-canton">Canton</label>
            <select id="ch-qst-canton" className={inputClass} value={form.canton} onChange={(e) => setForm({ ...form, canton: e.target.value })}>
              <option value="">Select…</option>
              {CH_CANTONS.map(([code, name]) => <option key={code} value={code}>{code} — {name}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass} htmlFor="ch-qst-fmt">Format version</label>
            <select id="ch-qst-fmt" className={inputClass} value={form.formatVersion} onChange={(e) => setForm({ ...form, formatVersion: e.target.value })}>
              {CH_QST_FORMAT_VERSIONS.map((v) => <option key={v} value={v}>{v}</option>)}
            </select>
          </div>
          <div>
            <label className={labelClass} htmlFor="ch-qst-from">Effective from</label>
            <input id="ch-qst-from" type="date" className={inputClass} value={form.effectiveFrom} onChange={(e) => setForm({ ...form, effectiveFrom: e.target.value })} />
          </div>
          <div>
            <label className={labelClass} htmlFor="ch-qst-to">Effective to</label>
            <input id="ch-qst-to" type="date" className={inputClass} value={form.effectiveTo} onChange={(e) => setForm({ ...form, effectiveTo: e.target.value })} />
          </div>
          <div>
            <label className={labelClass} htmlFor="ch-qst-year">Tax year</label>
            <input id="ch-qst-year" type="number" className={inputClass} value={form.taxYear} onChange={(e) => setForm({ ...form, taxYear: e.target.value })} />
          </div>
          <div>
            <label className={labelClass} htmlFor="ch-qst-pub">Publication date</label>
            <input id="ch-qst-pub" type="date" className={inputClass} value={form.publicationDate} onChange={(e) => setForm({ ...form, publicationDate: e.target.value })} />
          </div>
          <div>
            <label className={labelClass} htmlFor="ch-qst-src">Source artifact id</label>
            <input id="ch-qst-src" type="number" className={inputClass} value={form.sourceDocumentId} onChange={(e) => setForm({ ...form, sourceDocumentId: e.target.value })} />
          </div>
          <div>
            <label className={labelClass} htmlFor="ch-qst-file">File (unmodified authority copy)</label>
            <input id="ch-qst-file" type="file" className={inputClass + " file:text-xs"} onChange={(e) => setForm({ ...form, file: e.target.files?.[0], fileName: e.target.files?.[0]?.name || "" })} />
          </div>
        </div>
        <button type="button" onClick={runImport} disabled={importing}
          className="mt-3 flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-60">
          <Download size={13} /> {importing ? "Importing…" : "Import tariff file"}
        </button>
      </div>

      {error && <p role="alert" className="text-xs text-error">{error}</p>}

      <div className="overflow-x-auto rounded-xl border border-border">
        <table className="w-full text-xs">
          <thead>
            <tr className="border-b border-border text-left text-foreground-muted">
              <th className="px-3 py-2 font-medium">ID / Canton</th>
              <th className="px-3 py-2 font-medium">Format</th>
              <th className="px-3 py-2 font-medium">Tax year</th>
              <th className="px-3 py-2 font-medium">Effective</th>
              <th className="px-3 py-2 font-medium">Rows / SHA-256</th>
              <th className="px-3 py-2 font-medium">Status</th>
              <th className="px-3 py-2 font-medium">Next step</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border-light">
            {files.length === 0 ? (
              <tr><td colSpan={7} className="px-3 py-6 text-center text-foreground-disabled">No tariff files yet.</td></tr>
            ) : files.map((f) => (
              <tr key={f.id}>
                <td className="px-3 py-2">
                  <span className="font-mono font-semibold text-foreground">#{f.id}</span>
                  <span className="ml-1.5 text-foreground-secondary">{f.canton}</span>
                  <button type="button" onClick={() => openDetail(f)} title="Validation report"
                    className="ml-2 inline-flex items-center gap-1 text-primary hover:underline">
                    <Eye size={12} /> view
                  </button>
                </td>
                <td className="px-3 py-2 font-mono text-foreground-muted">{f.formatVersion}</td>
                <td className="px-3 py-2">{f.taxYear || "—"}</td>
                <td className="px-3 py-2 text-foreground-muted">
                  {f.effectiveFrom}{f.effectiveTo ? ` → ${f.effectiveTo}` : " → open"}
                </td>
                <td className="px-3 py-2">
                  <span className="font-mono">{f.rowCount}</span>
                  <span className="ml-1.5 font-mono text-[10px] text-foreground-disabled">{f.fileSha256?.slice(0, 12)}…</span>
                </td>
                <td className="px-3 py-2">
                  <StatusPill status={QST_STATUS_PILL[f.status] || "pending"} label={f.status} />
                </td>
                <td className="px-3 py-2">
                  <div className="flex items-center gap-1.5">
                    {nextStepFor(f) && (
                      <button type="button"
                        onClick={() => setConfirming({ file: f, action: nextStepFor(f).action })}
                        className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 font-semibold text-foreground-secondary hover:bg-surface-muted">
                        {nextStepFor(f).label}
                      </button>
                    )}
                    <button type="button"
                      onClick={() => openAffected(f)}
                      className="inline-flex items-center gap-1 rounded-lg border border-border px-2 py-1 text-foreground-muted hover:bg-surface-muted"
                      title="Payslips calculated on this tariff — read-only">
                      impacted
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {confirming && (
        <div className="rounded-xl border border-warning/40 bg-warning-light p-4">
          <p className="text-xs font-semibold text-foreground">
            {confirming.action === "validate" && "Validate tariff file"}
            {confirming.action === "approve" && `Approve tariff file #${confirming.file.id} (a Super Admin other than its importer)`}
            {confirming.action === "activate" && `Activate tariff file #${confirming.file.id} (a Super Admin other than its approver)`}
          </p>
          {confirming.action !== "validate" && (
            <textarea className={inputClass + " mt-2"} rows={2} placeholder={"Reason (optional)"}
              value={reason} onChange={(e) => setReason(e.target.value)} />
          )}
          <div className="mt-3 flex items-center gap-2">
            <button type="button" onClick={() => runAction(confirming.file)}
              className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover">
              Confirm {confirming.action}
            </button>
            <button type="button" onClick={() => { setConfirming(null); setReason(""); }}
              className="rounded-lg border border-border px-3 py-1.5 text-xs text-foreground-muted hover:bg-surface-muted">
              Cancel
            </button>
          </div>
        </div>
      )}

      {detail && (
        <div className="rounded-xl border border-border p-4 text-xs">
          <p className="mb-2 font-semibold text-foreground">Validation report — tariff file #{detail.id}</p>
          {["import", "validate", "approve", "activate"].map((stage) => {
            const part = detail.validationReport?.[stage];
            if (!part) return null;
            return (
              <div key={stage}>
                <p className="mt-2 font-medium text-foreground-secondary">{stage}</p>
                <pre className="mt-1 overflow-x-auto rounded-lg bg-surface-muted p-2 font-mono text-[11px] text-foreground-secondary">
                  {typeof part === "string" ? part : JSON.stringify(part, null, 2)}
                </pre>
              </div>
            );
          })}
          {detail.importedBy || detail.approvedBy || detail.activatedBy ? (
            <p className="mt-2 text-foreground-muted">
              {detail.importedById ? `Imported by #${detail.importedById}${detail.importedAt ? ` at ${detail.importedAt}` : ""}. ` : ""}
              {detail.approvedById ? `Approved by #${detail.approvedById}${detail.approvedAt ? ` at ${detail.approvedAt}` : ""}. ` : ""}
              {detail.activatedById ? `Activated by #${detail.activatedById}${detail.activatedAt ? ` at ${detail.activatedAt}` : ""}.` : ""}
            </p>
          ) : null}
        </div>
      )}

      {affected && (
        <div className="rounded-xl border border-border p-4 text-xs">
          <p className="mb-2 font-semibold text-foreground">
            Payslips calculated on tariff file #{affected.tariffFileId} ({affected.payslipCount})
            {affected.months?.length > 0 ? ` — months: ${affected.months.join(", ")}` : ""}
          </p>
          {affected.affected?.length === 0 ? (
            <p className="text-foreground-disabled">No payslips reference this tariff file.</p>
          ) : (
            <ul className="space-y-1">
              {affected.affected.map((a, i) => (
                <li key={i} className="rounded-lg bg-surface-muted px-2 py-1 font-mono text-[11px] text-foreground-secondary">
                  runs/{a.payrollRunId} · employee #{a.employeeId} · payslip #{a.payslipId}
                  {a.rowId ? ` · QST row ${a.rowId}` : ""}
                  {a.isCorrection ? " · correction" : ""}
                </li>
              ))}
            </ul>
          )}
          <p className="mt-2 text-foreground-muted">
            Read-only — a changed tariff never recalculates automatically; each affected payslip is corrected deliberately
            (organisations do this from Payroll).
          </p>
        </div>
      )}
    </section>
  );
}