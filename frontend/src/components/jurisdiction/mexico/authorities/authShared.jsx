import { useState } from "react";
import { btn, input } from "../mxShared";
import { checkMxAuthorityStatus, confirmMxAuthorityRetry, markMxAuthorityUnknown } from "../../../../service/payrollService";

// Shared pieces of the Mexico Social Security Center (ZP-MX-ENG-001 §14,
// Phase 8). File-export mode: Zoiko never transmits — the operator records
// what the authority answered, and an unknown outcome is UNKNOWN, never failed.

const TONE = {
  ACCEPTED: "bg-success/10 text-success", RECONCILED: "bg-success/10 text-success", PAID: "bg-success/10 text-success",
  FILED: "bg-primary/10 text-primary", EXPORTED: "bg-primary/10 text-primary",
  UNKNOWN: "bg-error/10 text-error", REJECTED: "bg-error/10 text-error", OPEN: "bg-error/10 text-error",
  OVERDUE: "bg-error/10 text-error", DUE_SOON: "bg-warning/10 text-warning",
  DUE_DATE_UNSOURCED: "bg-warning/10 text-warning", EXPLAINED: "bg-warning/10 text-warning",
  WITHDRAWN: "bg-surface-muted text-foreground-muted", VOIDED: "bg-surface-muted text-foreground-muted",
};

export function Status({ value }) {
  return (
    <span className={`rounded px-1.5 py-0.5 text-[10px] font-semibold ${TONE[value] || "bg-surface-muted text-foreground"}`}>
      {String(value || "—").replaceAll("_", " ")}
    </span>
  );
}

export function DueCell({ row }) {
  if (!row.dueDate) {
    return <span title="No sourced deadline is transcribed yet — Zoiko never defaults one"><Status value="DUE_DATE_UNSOURCED" /></span>;
  }
  return (
    <span className="flex flex-col gap-0.5">
      <span>{row.dueDate}</span>
      {row.dueState && row.dueState !== "DONE" && row.dueState !== "OPEN" && <Status value={row.dueState} />}
    </span>
  );
}

// A button that opens a one-field inline form (a reference or a reason).
export function PromptButton({ label, placeholder, onSubmit, disabled, testId, required = true }) {
  const [open, setOpen] = useState(false);
  const [value, setValue] = useState("");
  if (!open) {
    return <button type="button" className={btn} disabled={disabled} data-testid={testId} onClick={() => setOpen(true)}>{label}</button>;
  }
  return (
    <span className="flex flex-wrap items-center gap-1">
      <input className={`${input} min-w-[200px]`} aria-label={placeholder} placeholder={placeholder} value={value}
        onChange={(e) => setValue(e.target.value)} autoFocus />
      <button type="button" className={btn} disabled={required && !value.trim()}
        onClick={async () => { if (await onSubmit(value.trim())) { setOpen(false); setValue(""); } }}>
        Confirm
      </button>
      <button type="button" className="text-[12px] text-foreground-muted underline" onClick={() => setOpen(false)}>Cancel</button>
    </span>
  );
}

// "Outcome unknown" for the one transmission step of each object.
export function MarkUnknownButton({ kind, row, run }) {
  return (
    <PromptButton label="Outcome unknown…" placeholder="What happened (optional)" required={false}
      testId="mx-mark-unknown"
      onSubmit={(note) => run(() => markMxAuthorityUnknown(kind, row.id, note), "Recorded as UNKNOWN — check its status before anything is resent.")} />
  );
}

// The UNKNOWN rule (B7): status check first; a retry only after a NOT FOUND,
// confirmed with a reason, re-using the same record, payload and key.
export function UnknownActions({ kind, row, run }) {
  const u = row.unknown;
  if (!u) return null;
  return (
    <div className="mt-1 flex flex-col gap-1 rounded-lg border border-error/40 p-2 text-[11px]" data-testid="mx-authority-unknown">
      <p className="text-error">
        {u.retryPending
          ? "Retry confirmed and not sent yet — if the authority now shows the original, record it as FOUND (nothing is sent twice)."
          : `Outcome not known — nothing is resent automatically. NOT FOUND checks so far: ${u.notFoundChecks}.`}
        {!u.channelConfig && !u.retryPending && " No rule defines “definitively not found” for this channel, so a retry needs your confirmation."}
      </p>
      <span className="flex flex-wrap gap-1">
        <PromptButton label="Record FOUND…" placeholder="Authority reference (acuse / folio)" testId="mx-status-found"
          onSubmit={(ref) => run(() => checkMxAuthorityStatus(kind, row.id, true, ref), "FOUND recorded.")} />
        {!u.retryPending && (
          <>
            <button type="button" className={btn} data-testid="mx-status-not-found"
              onClick={() => run(() => checkMxAuthorityStatus(kind, row.id, false), "NOT FOUND recorded.")}>
              Record NOT FOUND
            </button>
            <PromptButton label="Confirm retry (same record, payload and key)…" placeholder="Reason for the retry"
              disabled={!u.notFoundChecks} testId="mx-confirm-retry"
              onSubmit={(reason) => run(() => confirmMxAuthorityRetry(kind, row.id, reason), "Retry confirmed — resend exactly the same.")} />
          </>
        )}
      </span>
    </div>
  );
}

export const money = (v) => (v === null || v === undefined ? "—" : Number(v).toLocaleString("es-MX", { minimumFractionDigits: 2, maximumFractionDigits: 4 }));
