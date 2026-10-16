import { useState } from "react";
import { getMxSaEmployer, getMxSaEmployerReadiness, listMxSaEmployers } from "../../../service/superAdminService";
import { card, input, Messages, useLoad } from "./mxShared";
import { ReadinessDateBar } from "./employer/employerShared";
import { localToday } from "./employer/employerUtils";
import {
  MXCredentialRefsPanel, MXIsnRegistrationsPanel, MXLaborPolicyPanel, MXLegalEntityPanel, MXRegistrationsPanel,
} from "./employer/MXEmployerPanels";
import MXEmployerReadiness from "./employer/MXEmployerReadiness";

// Super Admin view of one organisation's Mexico employers (spec §11 A–H) —
// READ-ONLY (Phase 3 Q5): the tenant authors its own employer facts in
// Payroll → Compliances → Mexico Compliance Centre. Identifiers arrive masked.
const noop = () => {};

export default function MXEmployerProfileTab({ orgId }) {
  const [chosen, setChosen] = useState(null);
  const [on, setOn] = useState(localToday);
  const [employers, error] = useLoad(() => (orgId ? listMxSaEmployers(orgId) : Promise.resolve([])), [orgId]);
  const employerId = chosen ?? employers?.[0]?.employerId ?? null;
  const [detail, detailError] = useLoad(
    () => (orgId && employerId ? getMxSaEmployer(orgId, employerId) : Promise.resolve(null)), [orgId, employerId]);
  const [readiness, readinessError] = useLoad(
    () => (orgId ? getMxSaEmployerReadiness(orgId, on) : Promise.resolve(null)), [orgId, on]);
  if (!orgId) {
    return <div className={card}><p className="text-[13px] text-foreground-muted">Select an organisation above to see its Mexico employers.</p></div>;
  }
  const shown = detail && detail.employerId === employerId ? detail : null;
  const mine = readiness?.employers?.find((e) => e.employerId === employerId);
  return (
    <div className="flex flex-col gap-4" data-testid="mx-sa-employer">
      <div className={card}>
        <p className="text-[12px] text-foreground-muted">
          Read-only. The organisation records its legal employers, registrations, labour policy and credential references
          itself; identifiers are masked here.
        </p>
      </div>
      <Messages error={error || detailError || readinessError} />
      {employers && employers.length === 0 && <p className="text-[12px] text-foreground-muted">This organisation has no Mexico legal employer yet.</p>}
      {employers && employers.length > 0 && (
        <select className={input} aria-label="Legal employer" value={employerId ?? ""} onChange={(e) => setChosen(Number(e.target.value))}>
          {employers.map((e) => <option key={e.employerId} value={e.employerId}>{e.legalName} ({e.rfc})</option>)}
        </select>
      )}
      {shown && (
        <>
          <MXLegalEntityPanel detail={shown} readOnly reload={noop} />
          <MXRegistrationsPanel detail={shown} readOnly reload={noop} />
          <MXIsnRegistrationsPanel detail={shown} readOnly reload={noop} />
          <MXLaborPolicyPanel detail={shown} readOnly reload={noop} />
          <MXCredentialRefsPanel detail={shown} readOnly reload={noop} />
        </>
      )}
      <ReadinessDateBar on={on} onChange={setOn} />
      {mine && <MXEmployerReadiness readiness={mine} gates={readiness.gates} />}
    </div>
  );
}
