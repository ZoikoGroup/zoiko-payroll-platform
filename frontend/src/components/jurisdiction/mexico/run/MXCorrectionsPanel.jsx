import { useCallback, useEffect, useState } from "react";
import { getMxRunCorrections, openMxRunCorrection, voidMxRunCorrection } from "../../../../service/payrollService";

// Mexico correction runs (ZP-MX-ENG-001 Phase 9a). On a COMMITTED run: open a
// CORRECTION run for chosen payslips — it recalculates the same period with the
// corrected inputs; the original payslip, its CFDI and its ledgers are never
// edited, and its commit posts only the differences. On a correction run: what
// it corrects, the posted differences, and "Void" while it is uncommitted.
const btn = "rounded-[10px] border border-border px-3 py-1.5 text-[12px] font-semibold disabled:opacity-40";
const input = "rounded-[8px] border border-border bg-background px-2 py-1 text-[12px]";
const money = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("es-MX", { minimumFractionDigits: 2 }));

function Deltas({ d }) {
  if (!d) return <span className="text-foreground-muted">posted on approval</span>;
  return <span>gross {money(d.gross)} · ISR {money(d.isr_withheld)} · net {money(d.net_pay)} · ISN {money(d.isn)}</span>;
}

export default function MXCorrectionsPanel({ runId, items }) {
  const [view, setView] = useState(null);
  const [refused, setRefused] = useState(false);
  const [chosen, setChosen] = useState({});
  const [reason, setReason] = useState("");
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [tick, setTick] = useState(0);
  const [removed, setRemoved] = useState(false);
  const reload = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    let active = true;
    getMxRunCorrections(runId)
      .then((d) => { if (active) setView(d); })
      .catch((err) => {
        if (!active) return;
        if (err?.status === 403) setRefused(true);
        else setError(err?.message || "Corrections could not be loaded.");
      });
    return () => { active = false; };
  }, [runId, tick]);

  if (removed) {
    return (
      <p className="mb-5 rounded-[12px] border border-border px-3 py-2 text-[12px] text-foreground-muted" data-testid="mx-corrections">
        Correction voided — this uncommitted run was removed; its record is kept on the original run. Close this run.
      </p>
    );
  }
  if (refused || !view) return error ? <p className="mb-3 text-[12px] text-error" role="alert">{error}</p> : null;
  const corrected = new Set(view.corrections.filter((c) => c.status !== "VOIDED").map((c) => c.originalItemId));
  const mxItems = (items || []).filter((i) => (i.country || i.countryCode) === "MX");

  async function act(fn, ok, after = reload) {
    setError(null);
    setNotice(null);
    try {
      await fn();
      setNotice(ok);
      after();
    } catch (err) {
      setError(err?.message || "Refused.");
    }
  }

  const isCorrection = view.runType === "CORRECTION";
  if (!isCorrection && !view.correctable && view.corrections.length === 0) return null;
  return (
    <section className="mb-5 rounded-[18px] border border-border p-5" data-testid="mx-corrections">
      <h4 className="mb-2 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
        {isCorrection ? "Mexico correction run" : "Mexico corrections"}
      </h4>
      {error && <p className="mb-2 text-[12px] text-error" role="alert">{error}</p>}
      {notice && <p className="mb-2 text-[12px] text-success">{notice}</p>}
      {isCorrection && (
        <>
          <p className="mb-2 text-[12px] text-foreground-muted">
            Recalculates committed payslips of run #{view.corrects[0]?.originalRunId} for the same period. The originals,
            their CFDI and their ledgers are never edited — approving this run posts only the differences, and its CFDI
            replaces the original&apos;s.
          </p>
          <ul className="mb-2 space-y-1 text-[12px]">
            {view.corrects.map((c) => (
              <li key={c.id} data-testid="mx-correction-row">
                Payslip #{c.originalItemId} → #{c.correctedItemId ?? "—"} · <strong>{c.status}</strong> · {c.reason} · <Deltas d={c.deltas} />
              </li>
            ))}
          </ul>
          {!view.committed && (
            <span className="flex flex-wrap items-center gap-2">
              <input className={`${input} min-w-[240px]`} aria-label="Void reason" placeholder="Why this correction is voided"
                value={reason} onChange={(e) => setReason(e.target.value)} />
              <button type="button" className={btn} disabled={!reason.trim()}
                onClick={() => act(() => voidMxRunCorrection(runId, reason.trim()), "Correction voided.", () => setRemoved(true))}>
                Void correction
              </button>
            </span>
          )}
        </>
      )}
      {(!isCorrection || view.committed) && (
        <>
          {isCorrection && view.committed && (
            <p className="mb-2 mt-3 text-[11px] font-bold uppercase tracking-widest text-foreground-muted">Corrections of this correction</p>
          )}
          {view.corrections.length > 0 && (
            <ul className="mb-3 space-y-1 text-[12px]">
              {view.corrections.map((c) => (
                <li key={c.id} data-testid="mx-correction-row">
                  Payslip #{c.originalItemId} · <strong>{c.status}</strong>
                  {c.correctionRunId ? ` · correction run #${c.correctionRunId}` : ""} · {c.reason}
                  {c.status === "COMMITTED" && <> · <Deltas d={c.deltas} /></>}
                  {c.status === "VOIDED" && c.voidReason ? ` · voided: ${c.voidReason}` : ""}
                </li>
              ))}
            </ul>
          )}
          {view.correctable && (
            <div className="flex flex-col gap-2">
              <p className="text-[12px] text-foreground-muted">
                Fix the inputs first (profile, hours, policy), then choose the payslips to recalculate for this period.
              </p>
              <div className="flex flex-wrap gap-3 text-[12px]">
                {mxItems.map((i) => (
                  <label key={i.id} className={`flex items-center gap-1 ${corrected.has(i.id) ? "opacity-40" : ""}`}>
                    <input type="checkbox" aria-label={`Correct ${i.employee || i.id}`} disabled={corrected.has(i.id)}
                      checked={Boolean(chosen[i.id])} onChange={(e) => setChosen((s) => ({ ...s, [i.id]: e.target.checked }))} />
                    {i.employee || `Payslip #${i.id}`}{corrected.has(i.id) ? " (already corrected)" : ""}
                  </label>
                ))}
              </div>
              <span className="flex flex-wrap items-center gap-2">
                <input className={`${input} min-w-[260px]`} aria-label="Correction reason" placeholder="Reason for the correction"
                  value={reason} onChange={(e) => setReason(e.target.value)} />
                <button type="button" className={btn} data-testid="mx-open-correction"
                  disabled={!reason.trim() || !Object.values(chosen).some(Boolean)}
                  onClick={() => act(async () => {
                    const ids = Object.keys(chosen).filter((k) => chosen[k]).map(Number);
                    const out = await openMxRunCorrection(runId, ids, reason.trim());
                    setChosen({});
                    setReason("");
                    return out;
                  }, "Correction run created — open it from Payroll Runs to review and approve it.")}>
                  Open correction run
                </button>
              </span>
            </div>
          )}
        </>
      )}
    </section>
  );
}
