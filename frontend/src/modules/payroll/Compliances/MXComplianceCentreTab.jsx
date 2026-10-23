import { useState } from "react";
import { createMxEmployer } from "../../../service/payrollService";
import { input, Messages, useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";
import { blankToNull, localToday } from "../../../components/jurisdiction/mexico/employer/employerUtils";
import {
  MXCredentialRefsPanel, MXIsnRegistrationsPanel, MXLaborPolicyPanel, MXLegalEntityPanel, MXRegistrationsPanel,
} from "../../../components/jurisdiction/mexico/employer/MXEmployerPanels";
import useMexicoOrgData from "../../../components/jurisdiction/mexico/employer/useMexicoOrgData";
import MXReadinessPanel from "./MXReadinessPanel";
import MXAguinaldoRunPanel from "./MXAguinaldoRunPanel";
import MXPtuCyclePanel from "./MXPtuCyclePanel";
import MXAnnualAdjustmentPanel from "./MXAnnualAdjustmentPanel";
import MXPaymentsPanel from "./MXPaymentsPanel";
import MXJournalPanel from "./MXJournalPanel";
import MXPilotBanner from "./MXPilotBanner";
import MXMasterTransferPanel from "./MXMasterTransferPanel";

// Mexico Compliance Centre (ZP-MX-ENG-001 §11) — the spec's "Settings →
// Countries → Mexico → Employer & Registrations", mounted where every country's
// organisation set-up lives in this repo: Payroll → Compliances → <Country>
// Compliance Centre. Acts on YOUR organisation only. No statutory value is
// typed here, and no secret: credentials are Secret Manager references.
export default function MXComplianceCentreTab() {
  const [chosen, setChosen] = useState(null);
  const [on, setOn] = useState(localToday);
  const data = useMexicoOrgData(chosen, on);
  const { employerId, detail } = data;
  const { run, error, notice, busy } = useAction(data.reloadAll);

  return (
    <div className="flex flex-col gap-4" data-testid="mx-compliance-centre">
      <MXPilotBanner />
      <div>
        <h2 className="text-[16px] font-semibold text-foreground">Employer & Registrations</h2>
        <p className="text-[12px] text-foreground-muted">
          Mexico payroll stays blocked until the platform gates G1–G8 are signed; this is where your legal employers,
          IMSS registrations, state ISN registrations, labour policy and credential references are set up.
        </p>
      </div>
      <Messages error={data.error} />
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] font-semibold text-foreground">Legal employer</span>
        <select className={input} aria-label="Legal employer" value={employerId ?? ""}
          onChange={(e) => setChosen(e.target.value ? Number(e.target.value) : null)}>
          {data.employers.length === 0 && <option value="">No legal employer yet</option>}
          {data.employers.map((e) => <option key={e.employerId} value={e.employerId}>{e.legalName} ({e.rfc})</option>)}
        </select>
      </div>
      <Panel title="Record a legal employer (RFC)" testId="mx-new-employer"
        hint="One organisation may hold several legal employers (MX-002). RFC: 12 characters for a persona moral, 13 for a persona física.">
        <MiniForm
          submitLabel="Record employer" busy={busy} error={error} notice={notice}
          initial={{ taxpayerType: "MORAL", withholdingObligationActive: true }}
          fields={[
            { key: "taxpayerType", label: "Taxpayer type", type: "select", options: ["MORAL", "FISICA"], required: true },
            { key: "rfc", label: "RFC", required: true }, { key: "legalName", label: "Razón social", required: true },
            { key: "fiscalRegimeCode", label: "Fiscal regime (c_RegimenFiscal)", required: true },
            { key: "fiscalPostalCode", label: "Fiscal postal code", required: true },
            { key: "placeOfIssuePostalCode", label: "Place of issue postal code", required: true },
            { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
            { key: "withholdingObligationActive", label: "ISR withholding obligation active", type: "checkbox" },
          ]}
          onSubmit={(s) => run(async () => {
            const created = await createMxEmployer(blankToNull({ ...s, withholdingObligationActive: Boolean(s.withholdingObligationActive) }));
            setChosen(created.id);
          }, "Legal employer recorded.")}
        />
      </Panel>
      {detail && (
        <>
          <MXLegalEntityPanel detail={detail} reload={data.reloadAll} />
          <MXRegistrationsPanel detail={detail} reload={data.reloadAll} />
          <MXIsnRegistrationsPanel detail={detail} reload={data.reloadAll} />
          <MXLaborPolicyPanel detail={detail} reload={data.reloadAll} agreements={data.agreements} />
          <MXCredentialRefsPanel detail={detail} reload={data.reloadAll} />
        </>
      )}
      <MXReadinessPanel on={on} setOn={setOn} readiness={data.readiness} employerId={employerId} />
      <MXAguinaldoRunPanel />
      <MXPtuCyclePanel />
      <MXAnnualAdjustmentPanel />
      <MXPaymentsPanel />
      <MXJournalPanel />
      <MXMasterTransferPanel />
    </div>
  );
}
