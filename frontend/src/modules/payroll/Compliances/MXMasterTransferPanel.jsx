import { useCallback, useEffect, useState } from "react";
import {
  approveMxImport, cancelMxImport, getMxTransferStatus, previewMxImport, proposeMxImport, proposeMxRelease,
  releaseMxRelease, revokeMxRelease,
} from "../../../service/payrollService";
import { Messages, Table, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { Badge, MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";

const link = "text-[12px] text-primary underline disabled:opacity-40";

// Phase 10f (option B): the master data a pilot proved moves into the new
// live organisation of the SAME employer (same RFC) by a tenant-run handshake:
// two pilot admins release it once (expires in 7 days, revocable until used);
// two live admins import it after reviewing the diff. Payroll results are
// never copied. Identifiers are masked in the preview and in every audit row.
export default function MXMasterTransferPanel() {
  const [status, setStatus] = useState(null);
  const [loadError, setLoadError] = useState(null);
  const [preview, setPreview] = useState(null);
  const [reason, setReason] = useState("");
  const [tick, setTick] = useState(0);
  const reload = useCallback(() => setTick((t) => t + 1), []);
  const { run, error, notice, busy } = useAction(reload);

  useEffect(() => {
    let active = true;
    getMxTransferStatus()
      .then((s) => { if (active) { setStatus(s); setLoadError(null); } })
      .catch((e) => active && setLoadError(e?.message || "The transfer status could not be loaded."));
    return () => { active = false; };
  }, [tick]);

  if (!status && !loadError) return null;
  return (
    <Panel title="Master data: pilot → live organisation" testId="mx-master-transfer"
      hint="Same employer only (same RFC). Two admins release it once; two admins of the live organisation import it after reviewing the diff. Payroll results are never copied.">
      {loadError && <p className="text-[12px] text-error" role="alert">{loadError}</p>}
      <Messages error={error} notice={notice} />
      {status?.isPilot && (
        <div className="flex flex-col gap-2" data-testid="mx-release-side">
          <p className="text-[12px] font-medium text-foreground">Release to the live organisation (this is the pilot)</p>
          <MiniForm testId="mx-new-release" submitLabel="Propose release" busy={busy}
            fields={[{ key: "targetOrganizationId", label: "Live organisation id", required: true },
                     { key: "reason", label: "Reason", required: true }]}
            onSubmit={(s) => run(() => proposeMxRelease({ targetOrganizationId: Number(s.targetOrganizationId), reason: s.reason }),
              "Release proposed — a different admin releases it.")} />
          <Table rows={status.outgoing} empty="No release." columns={[
            { key: "id", label: "Release", render: (r) => `#${r.id}` },
            { key: "targetOrganizationId", label: "To" },
            { key: "state", label: "State", render: (r) => <Badge value={r.state} /> },
            { key: "expiresAt", label: "Expires", render: (r) => (r.expiresAt ? String(r.expiresAt).slice(0, 10) : "—") },
            { key: "rfc", label: "Employer RFC", render: (r) => (r.plan?.employerRfcs || []).join(", ") },
            { key: "act", label: "", render: (r) => (
              <span className="flex gap-3">
                {r.state === "PROPOSED" && (
                  <button type="button" className={link} disabled={busy}
                    onClick={() => run(() => releaseMxRelease(r.id), "Released for 7 days.")}>Release (another admin)</button>
                )}
                {["PROPOSED", "AVAILABLE"].includes(r.state) && (
                  <button type="button" className={link} disabled={busy}
                    onClick={() => run(() => revokeMxRelease(r.id, "Revoked from the Compliance Centre"), "Revoked.")}>Revoke</button>
                )}
              </span>
            ) },
          ]} />
        </div>
      )}
      {!status?.isPilot && (
        <div className="flex flex-col gap-2" data-testid="mx-import-side">
          <p className="text-[12px] font-medium text-foreground">Released to this organisation</p>
          <Table rows={status?.incoming || []} empty="Nothing has been released to this organisation." columns={[
            { key: "id", label: "Release", render: (r) => `#${r.id}` },
            { key: "sourceOrganizationId", label: "From (pilot)" },
            { key: "state", label: "State", render: (r) => <Badge value={r.state} /> },
            { key: "expiresAt", label: "Expires", render: (r) => (r.expiresAt ? String(r.expiresAt).slice(0, 10) : "—") },
            { key: "act", label: "", render: (r) => (r.state === "AVAILABLE" ? (
              <button type="button" className={link} disabled={busy}
                onClick={() => run(async () => setPreview(await previewMxImport(r.id)), "Review the diff below.")}>Review the diff</button>
            ) : "") },
          ]} />
          {preview && (
            <div className="flex flex-col gap-2 rounded-lg border border-border p-3" data-testid="mx-import-preview">
              <p className="text-[12px] text-foreground">
                Release #{preview.releaseId} · employer {(preview.employerRfcs || []).join(", ")} ({preview.employerProfiles}) · will
                create: {Object.entries(preview.willCreate).map(([k, v]) => `${v} ${k}`).join(", ")}
              </p>
              <Table rows={preview.rows.employees} rowKey={(e) => e.sourceId} empty="No employee." columns={[
                { key: "employeeCode", label: "Code" }, { key: "name", label: "Name" },
                { key: "rfc", label: "RFC" }, { key: "curp", label: "CURP" }, { key: "nss", label: "NSS" },
                { key: "clabeLast4", label: "CLABE", render: (e) => (e.clabeLast4 ? `•••• ${e.clabeLast4}` : "—") },
              ]} />
              <p className="text-[11px] text-foreground-muted">Never copied: {Object.keys(preview.notCopied || {}).join("; ")}</p>
              <span className="flex flex-wrap items-center gap-2">
                <input aria-label="Import reason" placeholder="Reason" className="rounded border border-border px-1 text-[12px]"
                  value={reason} onChange={(e) => setReason(e.target.value)} />
                <button type="button" className={link} disabled={busy}
                  onClick={() => run(() => proposeMxImport(preview.releaseId, { previewSha256: preview.previewSha256, reason }),
                    "Import proposed — a different admin approves it.")}>Propose import (I reviewed this diff)</button>
              </span>
            </div>
          )}
          <Table rows={status?.imports || []} empty="No import." columns={[
            { key: "id", label: "Import", render: (c) => `#${c.id}` },
            { key: "status", label: "Status", render: (c) => <Badge value={c.status} /> },
            { key: "report", label: "Result", render: (c) => (c.report
              ? `${Object.values(c.report.copied).reduce((a, b) => a + b, 0)} rows copied · ${c.report.differences.length} differences`
              : "—") },
            { key: "act", label: "", render: (c) => (c.status === "PROPOSED" ? (
              <span className="flex gap-3">
                <button type="button" className={link} disabled={busy}
                  onClick={() => run(() => approveMxImport(c.id), "Imported.")}>Approve import (another admin)</button>
                <button type="button" className={link} disabled={busy}
                  onClick={() => run(() => cancelMxImport(c.id, "Cancelled"), "Cancelled.")}>Cancel</button>
              </span>
            ) : "") },
          ]} />
        </div>
      )}
    </Panel>
  );
}
