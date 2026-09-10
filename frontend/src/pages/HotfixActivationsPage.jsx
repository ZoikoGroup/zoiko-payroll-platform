import { useState, useEffect } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft, Zap } from "lucide-react";
import { useToast } from "../context/ToastContext";
import { getHotfixActivations, reviewHotfixActivation } from "../service/superAdminService";

// Super Admin > Compliance > Hotfix Activations (§19 gap-closure
// Part 11, 2026-09-09) — every emergency pack activation is
// permanently recorded here and MUST be reviewed after the fact; this
// page is that mandatory retrospective-review queue, not an optional
// audit log.
export default function HotfixActivationsPage() {
  const { addToast } = useToast() || {};
  const [activations, setActivations] = useState([]);
  const [loading, setLoading] = useState(true);
  const [filter, setFilter] = useState("unreviewed");
  const [reviewingId, setReviewingId] = useState(null);
  const [notes, setNotes] = useState("");

  function load() {
    const params = filter === "all" ? {} : { reviewed: filter === "reviewed" };
    getHotfixActivations(params).then(setActivations).finally(() => setLoading(false));
  }
  useEffect(load, [filter]);

  async function submitReview(id) {
    try {
      await reviewHotfixActivation(id, { review_notes: notes });
      addToast?.("Marked as reviewed.", "success");
      setReviewingId(null);
      setNotes("");
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to record review.", "error");
    }
  }

  return (
    <div>
      <Link to="/super-admin/compliance" className="mb-2 flex items-center gap-1 text-xs font-semibold text-foreground-muted hover:text-foreground">
        <ArrowLeft size={14} /> Back to Compliance
      </Link>
      <div className="mb-6 flex items-center gap-2">
        <Zap size={20} className="text-error" />
        <div>
          <h1 className="text-2xl font-bold text-foreground">Emergency Hotfix Activations</h1>
          <p className="text-sm text-foreground-muted mt-0.5">Every pack activated via hotfix mode bypassed the normal distinct-approver requirement — each one requires a mandatory retrospective review.</p>
        </div>
      </div>

      <div className="mb-4 flex items-center gap-1 rounded-lg border border-border bg-surface-muted p-1 w-fit">
        {[{ key: "unreviewed", label: "Needs Review" }, { key: "reviewed", label: "Reviewed" }, { key: "all", label: "All" }].map((t) => (
          <button
            key={t.key} onClick={() => setFilter(t.key)}
            className={`rounded-md px-3 py-1.5 text-xs font-semibold ${filter === t.key ? "bg-surface text-primary shadow-sm" : "text-foreground-muted hover:text-foreground"}`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading ? (
        <p className="py-12 text-center text-sm text-foreground-disabled">Loading…</p>
      ) : activations.length === 0 ? (
        <div className="rounded-xl border border-border bg-surface p-8 text-center text-sm text-foreground-disabled">Nothing here.</div>
      ) : (
        <div className="space-y-3">
          {activations.map((a) => (
            <div key={a.id} className="rounded-xl border border-border bg-surface p-4">
              <div className="flex items-start justify-between flex-wrap gap-2">
                <div>
                  <p className="text-sm font-bold text-foreground">Pack #{a.jurisdictionPackId} — Incident {a.incidentId}</p>
                  <p className="text-xs text-foreground-muted mt-1">{a.justification}</p>
                  <p className="text-[11px] text-foreground-disabled mt-1">
                    Activated {a.activatedAt ? new Date(a.activatedAt).toLocaleString() : "—"} by user #{a.activatedById}
                  </p>
                </div>
                {a.reviewed ? (
                  <span className="rounded-full bg-success/10 px-2 py-0.5 text-xs font-semibold text-success h-fit">Reviewed</span>
                ) : (
                  <span className="rounded-full bg-warning/10 px-2 py-0.5 text-xs font-semibold text-warning h-fit">Needs review</span>
                )}
              </div>
              {a.reviewed && a.reviewNotes && (
                <p className="mt-2 text-xs text-foreground-secondary border-t border-border pt-2">Review notes: {a.reviewNotes}</p>
              )}
              {!a.reviewed && (
                reviewingId === a.id ? (
                  <div className="mt-3 flex flex-col gap-2">
                    <textarea
                      className="w-full rounded-lg border border-border bg-background px-3 py-2 text-xs"
                      rows={2} value={notes} onChange={(e) => setNotes(e.target.value)}
                      placeholder="What did you confirm during review?"
                    />
                    <div className="flex gap-2">
                      <button onClick={() => submitReview(a.id)} className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white">Submit Review</button>
                      <button onClick={() => { setReviewingId(null); setNotes(""); }} className="rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary">Cancel</button>
                    </div>
                  </div>
                ) : (
                  <button onClick={() => setReviewingId(a.id)} className="mt-3 text-xs font-semibold text-primary hover:underline">
                    Mark as Reviewed
                  </button>
                )
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
