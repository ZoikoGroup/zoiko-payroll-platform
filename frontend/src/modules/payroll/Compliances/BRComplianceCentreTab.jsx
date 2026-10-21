import { useState } from "react";
import { createBrEmployer } from "../../../service/payrollService";
import { input, Messages, useAction } from "../../../components/jurisdiction/brazil/brShared";
import { MiniForm, Panel } from "../../../components/jurisdiction/brazil/employer/brEmployerShared";
import { blankToNull, localToday } from "../../../components/jurisdiction/brazil/employer/brEmployerUtils";
import {
  BRCprbPanel, BRCredentialsPanel, BREstablishmentsPanel, BRLegalEmployerPanel, EMPLOYER_FIELDS,
} from "../../../components/jurisdiction/brazil/employer/BREmployerPanels";
import useBrazilOrgData from "../../../components/jurisdiction/brazil/employer/useBrazilOrgData";
import BRReadinessPanel from "./BRReadinessPanel";

// Brazil Compliance Centre (ZP-BR-ENG-001 Phase 3) — Payroll → Compliances →
// Brazil Compliance Centre, where every country's organisation set-up lives in
// this repo. Acts on YOUR organisation only. No secret is ever typed here:
// credentials are Secret Manager references.
export default function BRComplianceCentreTab() {
  const [chosen, setChosen] = useState(null);
  const [on, setOn] = useState(localToday);
  const data = useBrazilOrgData(chosen, on);
  const { employerId, detail } = data;
  const { run, error, notice, busy } = useAction(data.reloadAll);

  return (
    <div className="flex flex-col gap-4" data-testid="br-compliance-centre">
      <div>
        <h2 className="text-[16px] font-semibold text-foreground">Employer & Establishments</h2>
        <p className="text-[12px] text-foreground-muted">
          Brazilian payroll stays blocked until the platform gates G1–G8 are signed; this is where your legal employers,
          establishments, RAT/FAP by year, CPRB option and credential references are set up.
        </p>
      </div>
      <Messages error={data.error} />
      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[12px] font-semibold text-foreground">Legal employer</span>
        <select className={input} aria-label="Legal employer" value={employerId ?? ""}
          onChange={(e) => setChosen(e.target.value ? Number(e.target.value) : null)}>
          {data.employers.length === 0 && <option value="">No legal employer yet</option>}
          {data.employers.map((e) => <option key={e.employerId} value={e.employerId}>{e.legalName} ({e.cnpjRoot})</option>)}
        </select>
      </div>
      <Panel title="Record a legal employer (CNPJ root)" testId="br-new-employer"
        hint="One organisation may hold several legal employers, one per CNPJ root. The contact CPF is checked and then shown masked.">
        <MiniForm
          submitLabel="Record employer" busy={busy} error={error} notice={notice}
          initial={{ esocialEnvironment: "RESTRICTED_PRODUCTION" }}
          fields={EMPLOYER_FIELDS}
          onSubmit={(s) => run(async () => {
            const created = await createBrEmployer(blankToNull(Object.fromEntries(EMPLOYER_FIELDS.map((f) => [f.key, s[f.key] ?? ""]))));
            setChosen(created.id);
          }, "Legal employer recorded.")}
        />
      </Panel>
      {detail && (
        <>
          <BRLegalEmployerPanel detail={detail} reload={data.reloadAll} />
          <BREstablishmentsPanel detail={detail} reload={data.reloadAll} />
          <BRCprbPanel detail={detail} reload={data.reloadAll} />
          <BRCredentialsPanel detail={detail} reload={data.reloadAll} />
        </>
      )}
      <BRReadinessPanel on={on} setOn={setOn} readiness={data.readiness} employerId={employerId} />
    </div>
  );
}
