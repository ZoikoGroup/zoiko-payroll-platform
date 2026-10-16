import { CalendarDays } from "lucide-react";
import { card, Messages, Table, useLoad } from "../netherlands/nlShared";

// Shared building blocks for the Mexico (ZP-MX-ENG-001) Super Admin tabs —
// the Netherlands idiom (re-exported) plus the Mexico-specific pieces:
// a prominent "in force on" date bar (explicit date; empty = the pack's
// own effective-from, never today), an "Awaiting transcription" state, and
// [PENDING G1] / [PENDING G2] / source cells for read-only pack content.
export { btn, btnPrimary, card, Field, input, labelCls, Messages, NeedOrg, Table, td, th, useAction, useLoad, yesNo } from "../netherlands/nlShared";

export function OnDateBar({ on, onChange, view }) {
  const shown = view?.on || on;
  const source = view?.onSource === "packEffectiveFrom" ? "the pack's effective-from (no date chosen)" : "the date you chose";
  return (
    <div className="flex flex-wrap items-center gap-3 rounded-xl border-2 border-primary/40 bg-primary/5 p-3" data-testid="mx-on-date">
      <CalendarDays size={18} className="text-primary" />
      <span className="text-[13px] font-semibold text-foreground">
        Law in force on <span className="text-primary">{shown || "—"}</span>
      </span>
      <input
        type="date" aria-label="In force on"
        className="rounded-lg border border-border bg-surface px-2 py-1 text-[13px] text-foreground"
        value={on || ""} onChange={(e) => onChange(e.target.value || null)}
      />
      {on && (
        <button type="button" className="text-[12px] text-foreground-muted underline" onClick={() => onChange(null)}>
          Use pack effective-from
        </button>
      )}
      {shown && <span className="text-[11px] text-foreground-muted">Date from {source}. The server date is never used.</span>}
    </div>
  );
}

export function AwaitingTranscription({ what }) {
  return (
    <div className={card} data-testid="mx-awaiting">
      <p className="text-[13px] font-semibold text-foreground">Awaiting transcription</p>
      <p className="mt-1 text-[12px] text-foreground-muted">
        No {what} is configured yet. Values are added only from official sources saved under
        docs/mexico/sources/ (SHA-256 recorded), each flagged [PENDING G1] until the human G1 review. Nothing is
        calculated from an empty table — Mexican payroll stays blocked.
      </p>
    </div>
  );
}

export function Flags({ row }) {
  return (
    <span className="flex flex-wrap gap-1">
      {row.pendingG1 && <span className="rounded bg-warning/15 px-1.5 py-0.5 text-[10px] font-semibold text-warning">PENDING G1</span>}
      {row.pendingG2 && <span className="rounded bg-error/10 px-1.5 py-0.5 text-[10px] font-semibold text-error">PENDING G2</span>}
    </span>
  );
}

export function SourceCell({ source }) {
  if (!source) return <span className="text-error">no source</span>;
  return (
    <span className="flex flex-col">
      <a href={source.url} target="_blank" rel="noreferrer" className="text-primary underline">{source.title}</a>
      <span className="font-mono text-[10px] text-foreground-muted">sha256 {String(source.sha256 || "").slice(0, 12)}…</span>
      <span className="text-[10px] text-foreground-muted">{source.reviewed ? "G1-reviewed" : "not yet G1-reviewed"}</span>
    </span>
  );
}

export const inForce = (r) => `${r.effectiveFrom || "pack start"} → ${r.effectiveTo || "pack end"}`;

const rateValue = (r) => r.amount ?? r.employeeRatePct ?? r.employerRatePct ?? r.text ?? "—";

export function RateRows({ rows, empty }) {
  return (
    <Table rows={rows} empty={empty} columns={[
      { key: "label", label: "Parameter" }, { key: "key", label: "Key" },
      { key: "value", label: "Value", render: rateValue },
      { key: "window", label: "In force", render: inForce },
      { key: "flags", label: "Review", render: (r) => <Flags row={r} /> },
      { key: "source", label: "Source", render: (r) => <SourceCell source={r.source} /> },
    ]} />
  );
}

export function SlabRows({ rows, empty, columns }) {
  return (
    <Table rows={rows} empty={empty} columns={[
      ...columns,
      { key: "window", label: "In force", render: inForce },
      { key: "flags", label: "Review", render: (r) => <Flags row={r} /> },
      { key: "source", label: "Source", render: (r) => <SourceCell source={r.source} /> },
    ]} />
  );
}

// One read-only content family: date bar + awaiting state + the caller's body.
export function ContentFamily({ load, on, setOn, what, children }) {
  const [view, error] = useLoad(() => load(on), [on]);
  return (
    <div className="flex flex-col gap-4">
      <OnDateBar on={on} onChange={setOn} view={view} />
      <Messages error={error} />
      {view && !view.pack && <AwaitingTranscription what={what} />}
      {view && view.pack && view.awaitingTranscription && <AwaitingTranscription what={what} />}
      {view && view.pack && !view.awaitingTranscription && children(view)}
      {view?.pack && (
        <p className="text-[11px] text-foreground-muted">
          {view.pack.packId} v{view.pack.version} · {view.pack.status} · read-only — {view.editVia}
        </p>
      )}
    </div>
  );
}
