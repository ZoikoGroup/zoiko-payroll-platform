import { useState } from "react";
import { CheckCircle2, Rocket, XCircle } from "lucide-react";
import { getFranceReadiness, setFranceLive } from "./employerStatutoryApi";
import { useAction, useLoad } from "./hooks";
import { btnPrimary, btnSecondary, cardCls, EmptyState, ErrorState, LoadingState, Messages, SectionHeader, StatusBadge } from "./ui";
import { day, display } from "./format";

const STATUS_LABEL = {
  NOT_CONFIGURED: "Not configured", NOT_READY: "Not ready", READY: "Ready", LIVE: "Live",
  LIVE_CHECKS_FAILING: "Live — checks failing",
};

export default function FranceReadinessSection({ readOnly }) {
  const { data, error, initialLoading, loading, reload, setData } = useLoad(() => getFranceReadiness());
  const [confirming, setConfirming] = useState(false);
  const { run, busy, error: actionError, notice } = useAction();

  if (initialLoading) return <LoadingState text="Checking France readiness…" />;
  if (error) return <ErrorState message={error} onRetry={reload} />;
  if (!data || typeof data !== "object") {
    return <EmptyState title="Readiness is not available yet" text="Set up the employer profile and establishments first." />;
  }

  const checks = Array.isArray(data.checks) ? data.checks : [];
  const status = data.readinessStatus || "NOT_CONFIGURED";
  const isLive = status === "LIVE" || status === "LIVE_CHECKS_FAILING";

  async function goLive() {
    const res = await run(() => setFranceLive({ confirmedFrom: "tenant_employer_statutory_page" }), "France payroll is now LIVE.");
    setConfirming(false);
    if (res.ok && res.data && typeof res.data === "object") setData(res.data);
  }

  return (
    <div className={cardCls}>
      <SectionHeader title="Go-live readiness"
        description="Computed from your real records on every check. France payroll can only be marked LIVE when every check passes.">
        <button type="button" className={btnSecondary} onClick={reload} disabled={loading}>{loading ? "Checking…" : "Re-check"}</button>
        {!readOnly && !isLive && (
          <button type="button" className={btnPrimary} disabled={!data.ready || busy}
            title={data.ready ? undefined : "Every readiness check must pass first"} onClick={() => setConfirming(true)}>
            <Rocket size={13} aria-hidden="true" /> Go live
          </button>
        )}
      </SectionHeader>

      <div className="mb-4 flex flex-wrap items-center gap-x-6 gap-y-2 text-[12px]">
        <span className="flex items-center gap-2"><span className="text-foreground-muted">Status</span> <StatusBadge status={STATUS_LABEL[status] || status} tone={data.ready ? "good" : isLive ? "bad" : "warn"} /></span>
        <span><span className="text-foreground-muted">Checked for period </span><span className="font-medium text-foreground">{day(data.forPeriod)}</span></span>
        <span><span className="text-foreground-muted">PAS CRM </span><span className="font-medium text-foreground">{display(data.pasCrmStatus)}</span></span>
        <span><span className="text-foreground-muted">Rate packs in force </span><span className="font-medium text-foreground">{display(data.effectiveRatePacks)}</span></span>
      </div>

      {confirming && (
        <div className="mb-4 rounded-[14px] border border-warning/30 bg-warning/5 p-4 dark:bg-warning/10">
          <p className="text-[13px] font-semibold text-foreground">Mark France payroll LIVE?</p>
          <p className="mt-1 text-[12px] text-foreground-muted">This records the passing checks as evidence on your employer profile and is audited.</p>
          <div className="mt-3 flex gap-2">
            <button type="button" className={btnSecondary} onClick={() => setConfirming(false)} disabled={busy}>Cancel</button>
            <button type="button" className={btnPrimary} onClick={goLive} disabled={busy}>{busy ? "Going live…" : "Confirm go-live"}</button>
          </div>
        </div>
      )}
      <Messages error={actionError} notice={notice} />

      {checks.length === 0 ? (
        <EmptyState title="No readiness checks returned" />
      ) : (
        <ul className="mt-2 divide-y divide-border rounded-[14px] border border-border">
          {checks.map((c, i) => (
            <li key={c?.key || i} className="flex items-start gap-3 px-3 py-2.5">
              {c?.ok
                ? <CheckCircle2 size={16} className="mt-0.5 shrink-0 text-success" aria-label="Passed" />
                : <XCircle size={16} className="mt-0.5 shrink-0 text-error" aria-label="Failing" />}
              <div className="min-w-0">
                <p className="text-[12px] font-semibold text-foreground">{display(c?.label)}</p>
                {!c?.ok && c?.detail && <p className="text-[11px] text-foreground-muted">{display(c.detail)}</p>}
              </div>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
