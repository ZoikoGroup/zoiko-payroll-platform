import { useState } from "react";
import {
  createSourceArtifact, downloadSourceArtifactFile, reviewHkEvidence, supersedeSourceArtifact, uploadSourceArtifactFile,
} from "../../../service/superAdminService";
import { getStoredUser } from "../../../service/api";
import { hkLabel } from "./hkLabels";

// Hong Kong governed evidence for ONE tag (HK-GATE-Gn / HK-DECISION-D-n /
// HK-PRODUCTION-VERIFICATION). `items` comes from the statutory summary as
// returned (current, not-superseded artifacts with a server-computed status).
// Register → upload (server computes the SHA-256) → a different Super Admin
// accepts or rejects (notes) → corrections are a new artifact + supersession.
// Every rule is enforced by the server; the UI only routes the actions.
const btn = "rounded-lg border border-border px-2 py-1 text-[11px] font-semibold text-foreground hover:bg-surface-muted disabled:opacity-40";
const input = "rounded-lg border border-border bg-surface px-2 py-1 text-[12px] text-foreground";
const STATUS_CLS = { ACCEPTED: "text-success", REJECTED: "text-error", AWAITING_REVIEW: "text-warning", AWAITING_UPLOAD: "text-warning" };

export default function HKEvidencePanel({ tag, items = [], onChanged }) {
  const me = getStoredUser()?.id;
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [form, setForm] = useState({ title: "", agency: "", file: null });
  const [notes, setNotes] = useState({});
  const [replacement, setReplacement] = useState({});

  async function run(action, done) {
    setError(null); setNotice(null); setBusy(true);
    try {
      await action();
      setNotice(done);
      onChanged?.();
    } catch (e) {
      setError(e?.message || "The action was refused.");
    } finally {
      setBusy(false);
    }
  }

  const register = () => run(async () => {
    const row = await createSourceArtifact({ agency: form.agency.trim(), title: form.title.trim(), formNumber: tag });
    if (form.file) await uploadSourceArtifactFile(row.id, form.file);
    setForm({ title: "", agency: "", file: null });
  }, form.file ? `${tag} evidence registered and uploaded — a different Super Admin must review it.`
    : `${tag} evidence registered — upload the signed document next.`);

  const review = (id, outcome) => run(() => reviewHkEvidence(id, { outcome, notes: notes[id] }),
    `${tag} evidence #${id} ${outcome === "ACCEPTED" ? "accepted" : "rejected"}.`);

  return (
    <div className="space-y-2 rounded-lg border border-border bg-surface-muted/40 p-3" aria-label={`Evidence for ${tag}`}>
      {error && <p role="alert" className="text-[12px] text-error">{error}</p>}
      {notice && <p role="status" className="text-[12px] text-success">{notice}</p>}
      {items.length === 0 && <p className="text-[12px] text-foreground-muted">No evidence registered for <code>{tag}</code>.</p>}
      {items.map((it) => {
        const others = items.filter((o) => o.id !== it.id);
        const ownItem = me != null && it.createdById === me;
        return (
          <div key={it.id} className="space-y-1 border-t border-border pt-2 first:border-t-0 first:pt-0">
            <div className="flex flex-wrap items-center gap-2 text-[12px] text-foreground">
              <span>#{it.id} {it.title}</span>
              <span className={`font-bold ${STATUS_CLS[it.status] || ""}`}>{hkLabel(it.status)}</span>
              {it.sha256 && <span className="font-mono text-[11px] text-foreground-muted">SHA-256 {it.sha256.slice(0, 12)}…</span>}
              {it.hasFile && <button type="button" className={btn} disabled={busy} onClick={() => run(() => downloadSourceArtifactFile(it.id), null)}>Download</button>}
            </div>
            {it.status === "REJECTED" && <p className="text-[12px] text-error">Rejection reason: {it.rejectionNotes}</p>}
            {it.status === "AWAITING_UPLOAD" && (
              <label className="text-[12px] text-foreground-secondary">Upload signed document{" "}
                <input type="file" aria-label={`Upload document for evidence #${it.id}`} disabled={busy}
                  onChange={(e) => e.target.files?.[0] && run(() => uploadSourceArtifactFile(it.id, e.target.files[0]),
                    `Document uploaded to #${it.id} — the server computed its SHA-256.`)} />
              </label>
            )}
            {it.status === "AWAITING_REVIEW" && (ownItem ? (
              <p className="text-[12px] text-foreground-muted">You registered this evidence — a different Super Admin must review it.</p>
            ) : (
              <div className="flex flex-wrap items-center gap-2">
                <input className={`${input} min-w-[260px]`} aria-label={`Review notes for evidence #${it.id}`} placeholder="Review notes (required to reject)"
                  value={notes[it.id] || ""} onChange={(e) => setNotes({ ...notes, [it.id]: e.target.value })} />
                <button type="button" className={btn} disabled={busy} onClick={() => review(it.id, "ACCEPTED")}>Accept</button>
                <button type="button" className={btn} disabled={busy || !(notes[it.id] || "").trim()} onClick={() => review(it.id, "REJECTED")}>Reject</button>
              </div>
            ))}
            {others.length > 0 && (
              <div className="flex flex-wrap items-center gap-2">
                <select className={input} aria-label={`Replacement for evidence #${it.id}`} value={replacement[it.id] || ""}
                  onChange={(e) => setReplacement({ ...replacement, [it.id]: e.target.value })}>
                  <option value="">Supersede with…</option>
                  {others.map((o) => <option key={o.id} value={o.id}>#{o.id} {o.title}</option>)}
                </select>
                <button type="button" className={btn} disabled={busy || !replacement[it.id]}
                  onClick={() => run(() => supersedeSourceArtifact(it.id, Number(replacement[it.id])),
                    `#${it.id} superseded by #${replacement[it.id]} — the old artifact and its review are kept.`)}>Supersede</button>
              </div>
            )}
          </div>
        );
      })}
      <div className="flex flex-wrap items-end gap-2 border-t border-border pt-2">
        <input className={input} aria-label={`Evidence title for ${tag}`} placeholder="Document title" value={form.title}
          onChange={(e) => setForm({ ...form, title: e.target.value })} />
        <input className={input} aria-label={`Issuer for ${tag}`} placeholder="Issued / signed by" value={form.agency}
          onChange={(e) => setForm({ ...form, agency: e.target.value })} />
        <input type="file" aria-label={`Document for ${tag}`} onChange={(e) => setForm({ ...form, file: e.target.files?.[0] || null })} />
        <button type="button" className={btn} disabled={busy || !form.title.trim() || !form.agency.trim()} onClick={register}>
          Submit evidence ({tag})
        </button>
      </div>
    </div>
  );
}
