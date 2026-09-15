import { useState, useEffect, useCallback, useRef } from "react";
import { Plus, CheckCircle2, Upload, Download, FileText } from "lucide-react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import {
  getSourceArtifacts, createSourceArtifact, reviewSourceArtifact,
  uploadSourceArtifactFile, downloadSourceArtifactFile,
} from "../../service/superAdminService";
import { inputClass, labelClass } from "./constants";

// Platform-wide (not US-only) — one row per official publication a
// statutory value was taken from (ZP-TAX-US-2026-001 §14). Kept as its own
// page-level panel, same reasoning as SuiEmployerRatesPanel/
// ReciprocityRulesPanel: this data isn't attached to any single
// JurisdictionPack version. No edit action is offered deliberately —
// a correction should be a new artifact, not a silent rewrite of what was
// actually retrieved (see service.py's create_source_artifact docstring).
export default function SourceEvidencePanel() {
  const { addToast } = useToast() || {};
  const [artifacts, setArtifacts] = useState([]);
  const [loading, setLoading] = useState(false);
  const [showForm, setShowForm] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    getSourceArtifacts().then(setArtifacts).finally(() => setLoading(false));
  }, []);

  useEffect(() => { load(); }, [load]);

  async function markReviewed(id) {
    try {
      await reviewSourceArtifact(id);
      addToast?.("Marked as reviewed.", "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to mark reviewed.", "error");
    }
  }

  async function handleUpload(id, file) {
    try {
      await uploadSourceArtifactFile(id, file);
      addToast?.("File uploaded — SHA-256 checksum computed from the actual bytes.", "success");
      load();
    } catch (err) {
      addToast?.(err.message || "Upload failed.", "error");
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface p-5">
      <div className="mb-4 flex items-start justify-between flex-wrap gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">Source Evidence</h2>
          <p className="mt-0.5 text-xs text-foreground-muted">
            Official publications behind configured rates/slabs — agency, title, URL, publication date, and reviewer.
            Upload the actual preserved document to get a real, server-computed SHA-256 checksum (never hand-typed).
            See ZP-TAX-US-2026-001 §14. A correction is a new artifact, not an edit to an existing one.
          </p>
        </div>
        <button onClick={() => setShowForm(true)} className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-sm font-semibold text-white hover:bg-primary-hover">
          <Plus size={14} /> Add Source
        </button>
      </div>

      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : artifacts.length === 0 ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">No source evidence recorded yet.</p>
      ) : (
        <div className="overflow-x-auto">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-light text-left text-foreground-muted">
                <th className="pb-2 pr-3">Agency</th>
                <th className="pb-2 pr-3">Title</th>
                <th className="pb-2 pr-3">Form #</th>
                <th className="pb-2 pr-3">Publication Date</th>
                <th className="pb-2 pr-3">Retrieved</th>
                <th className="pb-2 pr-3">Reviewed</th>
                <th className="pb-2 pr-3">File / Checksum</th>
                <th className="pb-2" />
              </tr>
            </thead>
            <tbody>
              {artifacts.map((a) => (
                <tr key={a.id} className="border-b border-border-light last:border-0">
                  <td className="py-2 pr-3 font-medium text-foreground">{a.agency}</td>
                  <td className="py-2 pr-3">
                    {a.sourceUrl ? <a href={a.sourceUrl} target="_blank" rel="noreferrer" className="text-primary hover:underline">{a.title}</a> : a.title}
                  </td>
                  <td className="py-2 pr-3 font-mono">{a.formNumber || "—"}</td>
                  <td className="py-2 pr-3 text-foreground-muted">{a.publicationDate || "—"}</td>
                  <td className="py-2 pr-3 text-foreground-muted">{a.retrievedAt ? new Date(a.retrievedAt).toLocaleDateString() : "—"}</td>
                  <td className="py-2 pr-3">
                    {a.reviewerApprovedAt ? (
                      <span className="flex items-center gap-1 text-success"><CheckCircle2 size={13} /> Yes</span>
                    ) : (
                      <button onClick={() => markReviewed(a.id)} className="text-primary hover:underline">Mark reviewed</button>
                    )}
                  </td>
                  <td className="py-2 pr-3">
                    <SourceFileCell artifact={a} onUpload={(file) => handleUpload(a.id, file)} />
                  </td>
                  <td className="py-2" />
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showForm && (
        <SourceArtifactFormModal
          onClose={() => setShowForm(false)}
          onSaved={() => { setShowForm(false); load(); }}
        />
      )}
    </div>
  );
}

function fmtBytes(n) {
  if (n == null) return "";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

// Real preserved-file storage cell (gap-closure Plan Phase 4) — a real,
// server-computed SHA-256 checksum only ever exists once a file is
// actually uploaded here; the create form's own "SHA-256 Checksum
// (optional)" free-text field is legacy/unverified by comparison.
function SourceFileCell({ artifact, onUpload }) {
  const inputRef = useRef(null);
  const [uploading, setUploading] = useState(false);

  async function handleFileChange(e) {
    const file = e.target.files?.[0];
    e.target.value = ""; // allow re-selecting the same file later
    if (!file) return;
    setUploading(true);
    try {
      await onUpload(file);
    } finally {
      setUploading(false);
    }
  }

  if (artifact.hasFile) {
    return (
      <div className="flex flex-col gap-1">
        <button
          onClick={() => downloadSourceArtifactFile(artifact.id, artifact.originalFilename)}
          className="flex items-center gap-1 text-primary hover:underline"
        >
          <Download size={12} /> {artifact.originalFilename || "Download"}
          {artifact.fileSizeBytes != null && <span className="text-foreground-disabled">({fmtBytes(artifact.fileSizeBytes)})</span>}
        </button>
        {artifact.checksumSha256 && (
          <span className="flex items-center gap-1 font-mono text-[11px] text-foreground-disabled" title={artifact.checksumSha256}>
            <FileText size={11} /> {artifact.checksumSha256.slice(0, 16)}…
          </span>
        )}
      </div>
    );
  }

  return (
    <div>
      <input ref={inputRef} type="file" className="hidden" onChange={handleFileChange} />
      <button
        onClick={() => inputRef.current?.click()}
        disabled={uploading}
        className="flex items-center gap-1 text-primary hover:underline disabled:opacity-50"
      >
        <Upload size={12} /> {uploading ? "Uploading…" : "Upload File"}
      </button>
      {artifact.checksumSha256 && (
        <p className="mt-0.5 font-mono text-[11px] text-foreground-disabled" title={artifact.checksumSha256}>
          (hand-typed) {artifact.checksumSha256.slice(0, 16)}…
        </p>
      )}
    </div>
  );
}

function SourceArtifactFormModal({ onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const [form, setForm] = useState({
    agency: "", title: "", formNumber: "", sourceUrl: "", publicationDate: "", checksumSha256: "",
  });
  const [saving, setSaving] = useState(false);
  const set = (field) => (e) => setForm((f) => ({ ...f, [field]: e.target.value }));

  async function save() {
    if (!form.agency.trim() || !form.title.trim()) {
      addToast?.("Agency and title are required.", "error");
      return;
    }
    setSaving(true);
    try {
      await createSourceArtifact({
        agency: form.agency, title: form.title, formNumber: form.formNumber || null,
        sourceUrl: form.sourceUrl || null, publicationDate: form.publicationDate || null,
        checksumSha256: form.checksumSha256 || null,
      });
      addToast?.("Source evidence recorded.", "success");
      onSaved();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title="Add Source Evidence" onClose={onClose} maxWidth="max-w-lg">
      <div className="grid grid-cols-2 gap-3">
        <div><label className={labelClass}>Agency</label><input className={inputClass} value={form.agency} onChange={set("agency")} placeholder="IRS" /></div>
        <div><label className={labelClass}>Form/Publication #</label><input className={inputClass} value={form.formNumber} onChange={set("formNumber")} placeholder="Pub. 15-T" /></div>
        <div className="col-span-2"><label className={labelClass}>Title</label><input className={inputClass} value={form.title} onChange={set("title")} placeholder="Publication 15-T (2026), Federal Income Tax Withholding Methods" /></div>
        <div className="col-span-2"><label className={labelClass}>Source URL</label><input className={inputClass} value={form.sourceUrl} onChange={set("sourceUrl")} placeholder="https://www.irs.gov/pub/irs-pdf/p15t.pdf" /></div>
        <div><label className={labelClass}>Publication Date</label><input type="date" className={inputClass} value={form.publicationDate} onChange={set("publicationDate")} /></div>
        <div><label className={labelClass}>SHA-256 Checksum (optional)</label><input className={inputClass} value={form.checksumSha256} onChange={set("checksumSha256")} /></div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save"}</button>
      </div>
    </Modal>
  );
}
