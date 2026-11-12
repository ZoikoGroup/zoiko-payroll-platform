import { getBeSigningStatus } from "../../../service/superAdminService";
import { card, useLoad } from "../japan/jpFormat";
import { ErrorNote } from "../new_zealand/nzShared";

// What still blocks activation of the selected Belgium pack, straight from the
// backend (be_super_admin.signing_status): unsigned, empty and unsourced rows,
// NOT_SUPPORTED decisions, earning classes still REVIEW, and the editors /
// signers — who can never approve or activate this version (four-eyes).

function KeyList({ title, keys, tone = "text-foreground" }) {
  return (
    <div>
      <h4 className="mb-1 text-[12px] font-semibold text-foreground">{title} ({keys.length})</h4>
      {keys.length === 0 ? <p className="text-[11px] text-foreground-muted">None.</p> : (
        <p className={`font-mono text-[11px] ${tone}`}>{keys.join(", ")}</p>
      )}
    </div>
  );
}

function Loaded({ pack }) {
  const [status, error] = useLoad(() => getBeSigningStatus(pack.id));
  if (error) return <ErrorNote message={error} />;
  if (!status) return <p className="text-[12px] text-foreground-muted">Loading…</p>;
  return (
    <div className={`${card} space-y-3`} data-testid="be-signing-status">
      <h3 className="text-[14px] font-semibold text-foreground">{status.packId} v{status.version} — {status.status}</h3>
      {status.activationRefusal
        ? <p className="rounded-lg border border-warning/40 bg-warning/10 p-2 text-[12px] text-warning">{status.activationRefusal}</p>
        : <p className="rounded-lg border border-success/40 bg-success/10 p-2 text-[12px] text-success">No content refusal (four-eyes and the release gates still apply).</p>}
      <KeyList title="Unsigned (PENDING G1)" keys={status.pendingRates} tone="text-warning" />
      <KeyList title="No value" keys={status.emptyValues} tone="text-warning" />
      <KeyList title="No source document" keys={status.unsourced} tone="text-warning" />
      <KeyList title="Signed NOT_SUPPORTED (feature blocked)" keys={status.notSupported} />
      <p className="text-[12px] text-foreground">Earning classes still REVIEW: <strong>{status.reviewClasses}</strong></p>
      <p className="text-[12px] text-foreground">
        Editors / signers of this version (never the approver or activator): {status.editors.length ? status.editors.join(", ") : "none yet"}
      </p>
    </div>
  );
}

export default function BESigningStatusTab({ pack }) {
  if (!pack) return <p className="text-[12px] text-foreground-muted">Select a Belgium pack.</p>;
  return <Loaded key={pack.id} pack={pack} />;
}
