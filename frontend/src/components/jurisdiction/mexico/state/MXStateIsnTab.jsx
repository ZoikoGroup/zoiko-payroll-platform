import { Table } from "../../netherlands/nlShared";

// One state ISN pack's rows, read-only: Mexico statutory content changes
// only through the governed pack lifecycle (seeded from mexico_content and
// re-proven at activation), never by a direct row edit here.
export default function MXStateIsnTab({ rates }) {
  return (
    <div className="flex flex-col gap-3">
      <Table rows={rates} empty="Awaiting transcription — no ISN rate configured yet (S22, current CDMX Fiscal Code)."
             columns={[
               { key: "label", label: "Parameter" }, { key: "componentKey", label: "Key" },
               { key: "rate", label: "Employer %", render: (r) => (r.employerRatePct != null ? `${r.employerRatePct}%` : "—") },
               { key: "window", label: "In force", render: (r) => `${r.effectiveFrom || "pack start"} → ${r.effectiveTo || "pack end"}` },
             ]} />
      <p className="text-[11px] text-foreground-muted">
        Read-only. The state ISN base is independent of federal ISR and IMSS SBC (§15); unsupported states are hard-blocked.
      </p>
    </div>
  );
}
