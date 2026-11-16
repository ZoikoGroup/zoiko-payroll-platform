import { useEffect, useState } from "react";
import { Activity, ChevronDown, ChevronUp, CircleAlert, CheckCircle2 } from "lucide-react";
import { getCompliancePackHealth } from "../../service/superAdminService";

// Super Admin > Compliance landing page: read-only health check of every tax
// pack (GET /super-admin/compliance/pack-health) - the Active pack each
// country runs on today, plus overlapping Active packs, exact-copy rows and
// countries with no Active pack. Shows counts only; changes nothing.

const fmt = (d) => d || "open";
const packLabel = (p) => `${p.packId} v${p.version}`;

function IssueList({ title, hint, children }) {
  return (
    <div className="rounded-lg border border-warning/30 bg-warning/10 px-3 py-2.5 text-xs">
      <p className="flex items-center gap-1.5 font-semibold text-warning">
        <CircleAlert size={13} aria-hidden="true" /> {title}
      </p>
      {hint ? <p className="mt-0.5 text-foreground-muted">{hint}</p> : null}
      <ul className="mt-1.5 space-y-1 text-foreground">{children}</ul>
    </div>
  );
}

export default function PackHealthPanel() {
  const [data, setData] = useState(null);
  const [error, setError] = useState(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    getCompliancePackHealth()
      .then((d) => { if (!cancelled) setData(d); })
      .catch((e) => { if (!cancelled) setError(e.message || "Could not load the pack health check."); });
    return () => { cancelled = true; };
  }, []);

  if (error) return <p className="mb-4 text-xs text-error">{error}</p>;
  if (!data) return <p className="mb-4 text-xs text-foreground-muted">Checking tax packs…</p>;

  const { overlappingActive, duplicateRows, noActivePack } = data.issues;
  const issueCount = overlappingActive.length + duplicateRows.length + noActivePack.length;

  return (
    <section className="mb-6 rounded-xl border border-border bg-surface">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center justify-between gap-2 px-4 py-3 text-left"
      >
        <span className="flex items-center gap-2 text-sm font-bold text-foreground">
          <Activity size={16} aria-hidden="true" /> Pack health
        </span>
        <span className="flex flex-wrap items-center gap-2 text-[11px] font-semibold">
          {issueCount === 0 ? (
            <span className="inline-flex items-center gap-1 rounded-full bg-success/10 px-2.5 py-1 text-success">
              <CheckCircle2 size={12} aria-hidden="true" /> No problems found
            </span>
          ) : (
            <>
              {overlappingActive.length > 0 && (
                <span className="rounded-full bg-error/10 px-2.5 py-1 text-error">{overlappingActive.length} overlapping Active</span>
              )}
              {duplicateRows.length > 0 && (
                <span className="rounded-full bg-warning/10 px-2.5 py-1 text-warning">{duplicateRows.length} packs with copied rows</span>
              )}
              {noActivePack.length > 0 && (
                <span className="rounded-full bg-warning/10 px-2.5 py-1 text-warning">{noActivePack.length} without an Active pack</span>
              )}
            </>
          )}
          {open ? <ChevronUp size={16} aria-hidden="true" /> : <ChevronDown size={16} aria-hidden="true" />}
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-border px-4 py-4">
          {overlappingActive.length > 0 && (
            <IssueList title="Overlapping Active packs" hint="Two Active packs for the same scope and dates — payroll may use either. Keep one and supersede the other.">
              {overlappingActive.map((o) => (
                <li key={o.packs.map((p) => p.id).join("-")}>
                  <span className="font-semibold">{[o.country, o.state, o.locality].filter(Boolean).join(" / ")}</span>
                  {": "}{o.packs.map((p) => `${packLabel(p)} (${fmt(p.effectiveFrom)} → ${fmt(p.effectiveTo)})`).join(" and ")}
                  {o.bothInForce ? " — both in force today" : ""}
                </li>
              ))}
            </IssueList>
          )}
          {duplicateRows.length > 0 && (
            <IssueList title="Exact-copy rows" hint="Rows identical in every value. A copied tax slab is added in once per copy by bracket sums.">
              {duplicateRows.map((d) => (
                <li key={d.id}>
                  <span className="font-semibold">{d.country}</span> {packLabel(d)} ({d.status}):{" "}
                  {[d.extraSlabRows && `${d.extraSlabRows} slab`, d.extraRateRows && `${d.extraRateRows} rate`].filter(Boolean).join(", ")} extra row(s)
                </li>
              ))}
            </IssueList>
          )}
          {noActivePack.length > 0 && (
            <IssueList title="No Active country tax pack" hint="Paid registration for these countries is blocked until a pack is activated.">
              <li>{noActivePack.join(", ")}</li>
            </IssueList>
          )}

          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[640px] text-left text-xs">
              <thead className="bg-surface-muted text-foreground-muted">
                <tr>
                  {["Country", "Active pack", "Effective", "Rates", "Slabs", "Approved", "Source", "Awaiting sign-off"].map((h) => (
                    <th key={h} className="px-3 py-2 font-semibold">{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.countries.map((c) => {
                  const a = c.activePack;
                  return (
                    <tr key={c.country}>
                      <td className="px-3 py-2 font-semibold text-foreground">{c.country}</td>
                      {a ? (
                        <>
                          <td className="px-3 py-2 text-foreground">
                            {packLabel(a)}
                            {!a.inForceToday && <span className="ml-1 text-warning">(not in force today)</span>}
                          </td>
                          <td className="px-3 py-2 text-foreground-muted">{fmt(a.effectiveFrom)} → {fmt(a.effectiveTo)}</td>
                          <td className="px-3 py-2 text-foreground">{a.rates}</td>
                          <td className="px-3 py-2 text-foreground">{a.slabs}</td>
                          <td className={`px-3 py-2 ${a.approved ? "text-success" : "text-warning"}`}>{a.approved ? "Yes" : "No"}</td>
                          <td className={`px-3 py-2 ${a.sourceDocumentAttached ? "text-success" : "text-warning"}`}>{a.sourceDocumentAttached ? "Yes" : "No"}</td>
                          <td className={`px-3 py-2 ${a.pendingSignOff ? "text-warning" : "text-foreground-muted"}`}>{a.pendingSignOff}</td>
                        </>
                      ) : (
                        <td colSpan={7} className="px-3 py-2 text-warning">
                          No Active country tax pack ({Object.entries(c.statusCounts).map(([s, n]) => `${n} ${s}`).join(", ")})
                        </td>
                      )}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-[11px] text-foreground-muted">Checked {data.generatedOn}. Read-only — nothing here changes a pack.</p>
        </div>
      )}
    </section>
  );
}
