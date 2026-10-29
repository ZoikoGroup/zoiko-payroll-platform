import { useState } from "react";
import { getBrSaEmployerReadiness, listBrSaEmployers } from "../../../service/superAdminService";
import { Messages, NeedOrg, useLoad } from "./brShared";
import BREmployerReadiness from "./employer/BREmployerReadiness";
import { BRCprbPanel, BRCredentialsPanel, BREstablishmentsPanel, BRLegalEmployerPanel } from "./employer/BREmployerPanels";
import { ReadinessDateBar } from "./employer/brEmployerShared";
import { localToday } from "./employer/brEmployerUtils";

// Super Admin — one organisation's Brazil employers, READ ONLY (the tenant owns
// its employer facts; identifiers masked). The organisation comes from the
// page's own picker; there is no default organisation.
export default function BREmployerProfileTab({ orgId }) {
  const [on, setOn] = useState(localToday);
  const [employers, error] = useLoad(() => (orgId ? listBrSaEmployers(orgId) : Promise.resolve(null)), [orgId]);
  const [readiness, readinessError] = useLoad(
    () => (orgId ? getBrSaEmployerReadiness(orgId, on) : Promise.resolve(null)), [orgId, on]);
  if (!orgId) return <NeedOrg />;
  const noop = () => {};
  return (
    <div className="flex flex-col gap-4" data-testid="br-sa-employer">
      <Messages error={error || readinessError} />
      {(employers || []).length === 0 && <p className="text-[12px] text-foreground-muted">This organisation has no Brazil legal employer yet.</p>}
      {(employers || []).map((e) => (
        <div key={e.employerId} className="flex flex-col gap-3">
          <h3 className="text-[14px] font-semibold text-foreground">{e.legalName} — CNPJ root {e.cnpjRoot}</h3>
          <BRLegalEmployerPanel detail={e.detail} reload={noop} readOnly />
          <BREstablishmentsPanel detail={e.detail} reload={noop} readOnly />
          <BRCprbPanel detail={e.detail} reload={noop} readOnly />
          <BRCredentialsPanel detail={e.detail} reload={noop} readOnly />
        </div>
      ))}
      <ReadinessDateBar on={on} onChange={setOn} />
      {(readiness?.employers || []).map((r) => <BREmployerReadiness key={r.employerId} readiness={r} gates={readiness.gates} />)}
    </div>
  );
}
