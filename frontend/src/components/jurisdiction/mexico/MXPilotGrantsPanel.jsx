import { useState } from "react";
import { CheckCircle2, XCircle } from "lucide-react";
import {
  approveMxPilotGrant, listMxMasterCopies, listMxPilotGrants, proposeMxPilotGrant, revokeMxPilotGrant,
  withdrawMxPilotGrant,
} from "../../../service/superAdminService";
import { Messages, Table, btn, card, input, useAction, useLoad } from "./mxShared";

// Phase 10e: the PILOT level of Mexico activation. One named EVALUATION
// organisation, proposed by one Super Admin and approved by a different one;
// revocable, expiring (≤ 120 days). Its output is non-binding (PAC sandbox
// only, no payments, no filings, watermarked payslips). The governed
// master-data copy into the live organisation is listed read-only: its
// worker-data routes stay retired until the ZP-PRIV owner decides (D5).
export default function MXPilotGrantsPanel({ level }) {
  const [data, error, , reload] = useLoad(() => listMxPilotGrants(), []);
  const [copies] = useLoad(() => listMxMasterCopies(), []);
  const { run, error: actError, notice, busy } = useAction(reload);
  const [form, setForm] = useState({ organizationId: "", reason: "", expiresOn: "" });
  const [reasons, setReasons] = useState({});

  const unmet = (data?.preconditions || []).filter((p) => !p.met);
  return (
    <div className={card} data-testid="mx-pilot-grants">
      <h3 className="mb-1 text-[14px] font-semibold text-foreground">Pilot (named organisations)</h3>
      <p className="mb-2 text-[12px] text-foreground-muted">
        Level: <span className="font-semibold text-foreground">{level}</span>. A pilot runs the G8 parallel payroll for
        one EVALUATION organisation. Its output is non-binding: CFDI only through the PAC sandbox, no salary payments, no
        authority filings, every payslip watermarked.
      </p>
      <Messages error={error || actError} notice={notice} />
      <ul className="mb-2 flex flex-col gap-1" data-testid="mx-pilot-preconditions">
        {(data?.preconditions || []).map((p) => (
          <li key={p.key} className="flex items-start gap-2 text-[12px] text-foreground">
            {p.met ? <CheckCircle2 size={14} className="mt-0.5 text-success" /> : <XCircle size={14} className="mt-0.5 text-error" />}
            <span><span className="font-semibold">{p.label}:</span> {p.detail}</span>
          </li>
        ))}
      </ul>
      <form className="mb-3 grid grid-cols-1 gap-2 md:grid-cols-4" data-testid="mx-new-pilot-grant"
        onSubmit={(e) => {
          e.preventDefault();
          run(() => proposeMxPilotGrant({ ...form, organizationId: Number(form.organizationId) }),
            "Pilot grant proposed — a different Super Admin approves it.");
        }}>
        <input className={input} aria-label="Organisation id" placeholder="Organisation id" value={form.organizationId}
          onChange={(e) => setForm({ ...form, organizationId: e.target.value })} />
        <input className={input} aria-label="Reason" placeholder="Reason" value={form.reason}
          onChange={(e) => setForm({ ...form, reason: e.target.value })} />
        <input className={input} aria-label="Expires on" type="date" value={form.expiresOn}
          onChange={(e) => setForm({ ...form, expiresOn: e.target.value })} />
        <button type="submit" className={btn} disabled={busy}>Propose pilot grant</button>
      </form>
      {unmet.length > 0 && (
        <p className="mb-2 text-[12px] text-error">A grant cannot be approved until every condition above is met.</p>
      )}
      <Table rows={data?.grants || []} empty="No pilot grant." columns={[
        { key: "id", label: "Grant", render: (g) => `#${g.id}` },
        { key: "organizationId", label: "Organisation" },
        { key: "state", label: "State" },
        { key: "expiresAt", label: "Expires", render: (g) => String(g.expiresAt || "").slice(0, 10) },
        { key: "reason", label: "Reason" },
        { key: "act", label: "", render: (g) => (g.status === "PROPOSED" ? (
          <span className="flex gap-2">
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => approveMxPilotGrant(g.id), "Pilot grant approved.")}>Approve (another Super Admin)</button>
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => withdrawMxPilotGrant(g.id, "Withdrawn"), "Withdrawn.")}>Withdraw</button>
          </span>
        ) : g.state === "ACTIVE" ? (
          <span className="flex items-center gap-2">
            <input className={input} aria-label={`Revoke reason ${g.id}`} placeholder="Reason to revoke"
              value={reasons[g.id] || ""} onChange={(e) => setReasons({ ...reasons, [g.id]: e.target.value })} />
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => revokeMxPilotGrant(g.id, reasons[g.id] || ""), "Pilot grant revoked.")}>Revoke</button>
          </span>
        ) : (g.revokeReason || "")) },
      ]} />
      <h4 className="mb-1 mt-3 text-[13px] font-semibold text-foreground">Master-data copies into the live organisation</h4>
      <p className="mb-1 text-[12px] text-foreground-muted">
        Four-eyes, audited, with a diff report; payroll results are never copied. Proposing and approving a copy stays
        closed until the ZP-PRIV owner decides how a copy between two organisations is authorised.
      </p>
      <Table rows={copies || []} empty="No copy." columns={[
        { key: "id", label: "Copy", render: (c) => `#${c.id}` },
        { key: "sourceOrganizationId", label: "From (pilot)" }, { key: "targetOrganizationId", label: "To (live)" },
        { key: "status", label: "Status" },
        { key: "report", label: "Differences", render: (c) => (c.report ? String(c.report.differences.length) : "—") },
      ]} />
    </div>
  );
}
