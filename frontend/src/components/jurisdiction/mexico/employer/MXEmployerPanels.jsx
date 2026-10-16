import { useState } from "react";
import {
  activateMxLaborPolicy, approveMxRiskPremium, createMxCredential, createMxEmployerVersion, createMxEstablishment,
  createMxImssRegistration, createMxIsnRegistration, createMxLaborPolicy, createMxRiskPremium, revokeMxCredential,
  setMxInfonavitModel, uploadMxCertificate,
} from "../../../../service/payrollService";
import { btn, input, Messages, Table, useAction } from "../mxShared";
import { Badge, MiniForm, Panel } from "./employerShared";
import { blankToNull } from "./employerUtils";
import { MX_FEDERAL_ENTITIES } from "./mxStateCodes";

// Spec §11 panels A–G for one legal employer. `detail` is the employer
// detail payload (org: GET /api/payroll/mexico/employers/{id}; Super Admin:
// the read-only, identifier-masked equivalent). With readOnly every write
// control is omitted, not merely disabled.

const STATE_OPTIONS = MX_FEDERAL_ENTITIES.map((s) => ({ value: s.code, label: `${s.code} — ${s.name}` }));

// ── A + B: legal entity and SAT payroll ─────────────────────────────────────
export function MXLegalEntityPanel({ detail, readOnly, reload }) {
  const { run, error, notice, busy } = useAction(reload);
  const latest = detail.versions[detail.versions.length - 1];
  return (
    <>
      <Panel letter="A" title="Legal / tax entity" testId="mx-panel-a"
        hint="RFC format is checked here; the RFC/name match with SAT is the stamp test (Phase 7). The RFC never changes inside an employer's history.">
        <Table rows={detail.versions} columns={[
          { key: "version", label: "v" }, { key: "effectiveFrom", label: "From" },
          { key: "effectiveTo", label: "To", render: (r) => r.effectiveTo || "open" },
          { key: "rfc", label: "RFC" }, { key: "taxpayerType", label: "Type" }, { key: "legalName", label: "Razón social" },
          { key: "fiscalRegimeCode", label: "Regime" }, { key: "fiscalPostalCode", label: "Fiscal CP" },
        ]} />
        {!readOnly && (
          <MiniForm
            testId="mx-new-version" submitLabel="Record new version" busy={busy} error={error} notice={notice}
            initial={{ ...latest, effectiveFrom: "" }}
            fields={[
              { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
              { key: "legalName", label: "Razón social", required: true },
              { key: "fiscalRegimeCode", label: "Fiscal regime (c_RegimenFiscal)", required: true },
              { key: "fiscalPostalCode", label: "Fiscal postal code", required: true },
              { key: "placeOfIssuePostalCode", label: "Place of issue postal code", required: true },
              { key: "pacProvider", label: "PAC provider" },
              { key: "pacEnvironment", label: "PAC environment", type: "select", options: ["SANDBOX", "PRODUCTION"] },
              { key: "withholdingObligationActive", label: "ISR withholding obligation active", type: "checkbox" },
            ]}
            onSubmit={(s) => run(() => createMxEmployerVersion(detail.employerId, blankToNull({
              effectiveFrom: s.effectiveFrom, taxpayerType: latest.taxpayerType, rfc: latest.rfc,
              legalName: s.legalName, fiscalRegimeCode: s.fiscalRegimeCode, fiscalPostalCode: s.fiscalPostalCode,
              placeOfIssuePostalCode: s.placeOfIssuePostalCode, withholdingObligationActive: Boolean(s.withholdingObligationActive),
              pacProvider: s.pacProvider, pacEnvironment: s.pacEnvironment,
            })), "New version recorded; the previous one is closed the day before.")}
          />
        )}
      </Panel>
      <Panel letter="B" title="SAT payroll" testId="mx-panel-b"
        hint="Stamp test is required before LIVE — it is run by the PAC integration (Phase 7), never set by hand.">
        <Table rows={[latest]} columns={[
          { key: "pacProvider", label: "PAC provider" }, { key: "pacEnvironment", label: "Environment" },
          { key: "withholdingObligationActive", label: "Withholding obligation", render: (r) => (r.withholdingObligationActive ? "Active" : "Not active") },
          { key: "placeOfIssuePostalCode", label: "Place of issue" },
          { key: "stampTestStatus", label: "Stamp test", render: (r) => <Badge value={r.stampTestStatus} /> },
        ]} />
      </Panel>
    </>
  );
}

// ── C + D: IMSS registrations, risk premiums, INFONAVIT model ───────────────
export function MXRegistrationsPanel({ detail, readOnly, reload }) {
  const { run, error, notice, busy } = useAction(reload);
  const [premiumFor, setPremiumFor] = useState("");
  const regs = detail.imssRegistrations;
  const premiums = regs.flatMap((r) => r.riskPremiums.map((p) => ({ ...p, registroPatronal: r.registroPatronal })));
  return (
    <Panel letter="C" title="IMSS employer registrations" testId="mx-panel-c"
      hint="An employer may hold several registrations; the work-risk premium belongs to the registration and its premium period (MX-024). A premium is approved by a second org admin, and only once the period rule and legal range are transcribed.">
      <Table rows={regs} empty="No IMSS registration recorded." columns={[
        { key: "registroPatronal", label: "Registro Patronal" }, { key: "riskClass", label: "Class" },
        { key: "fraction", label: "Fraction" }, { key: "subdelegationCode", label: "Subdelegation" },
        { key: "effectiveFrom", label: "From" }, { key: "effectiveTo", label: "To", render: (r) => r.effectiveTo || "open" },
        { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
        {
          key: "infonavit", label: "D · INFONAVIT model", render: (r) => (readOnly ? (r.infonavitOperatingModel || "not set") : (
            <select className={input} aria-label={`INFONAVIT model ${r.registroPatronal}`} value={r.infonavitOperatingModel || ""}
              onChange={(e) => e.target.value && run(() => setMxInfonavitModel(r.id, e.target.value), "INFONAVIT model saved.")}>
              <option value="">—</option><option value="SUA">SUA</option><option value="SIPARE">SIPARE</option>
            </select>
          )),
        },
      ]} />
      <h4 className="text-[12px] font-semibold text-foreground">Work-risk premiums</h4>
      <Table rows={premiums} empty="No premium recorded." columns={[
        { key: "registroPatronal", label: "Registration" }, { key: "determinationYear", label: "Determined" },
        { key: "premiumRatePct", label: "Premium %" }, { key: "periodFrom", label: "Period from" }, { key: "periodTo", label: "Period to" },
        { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
        ...(readOnly ? [] : [{
          key: "approve", label: "", render: (r) => (r.status === "DRAFT" ? (
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => approveMxRiskPremium(r.id), "Premium approved.")}>Approve</button>
          ) : null),
        }]),
      ]} />
      {!readOnly && (
        <>
          <MiniForm
            testId="mx-new-registration" submitLabel="Add registration" busy={busy}
            fields={[
              { key: "registroPatronal", label: "Registro Patronal (11)", required: true },
              { key: "riskClass", label: "Risk class", required: true }, { key: "fraction", label: "Fraction", required: true },
              { key: "subdelegationCode", label: "Subdelegation" },
              { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
              { key: "infonavitOperatingModel", label: "INFONAVIT model", type: "select", options: ["SUA", "SIPARE"] },
            ]}
            onSubmit={(s) => run(() => createMxImssRegistration(detail.employerId, blankToNull(s)), "Registration added.")}
          />
          <div className="flex flex-col gap-2 border-t border-border pt-3">
            <select className={input} aria-label="Premium for registration" value={premiumFor} onChange={(e) => setPremiumFor(e.target.value)}>
              <option value="">Record a premium for registration…</option>
              {regs.map((r) => <option key={r.id} value={r.id}>{r.registroPatronal}</option>)}
            </select>
            {premiumFor && (
              <MiniForm
                testId="mx-new-premium" submitLabel="Record premium (DRAFT)" busy={busy}
                fields={[
                  { key: "determinationYear", label: "Determination year", required: true },
                  { key: "premiumRatePct", label: "Premium %", required: true },
                  { key: "periodFrom", label: "Period from", type: "date", required: true },
                  { key: "periodTo", label: "Period to", type: "date", required: true },
                ]}
                onSubmit={(s) => run(() => createMxRiskPremium(premiumFor, { ...s, determinationYear: Number(s.determinationYear) }),
                  "Premium recorded as DRAFT — a second org admin must approve it.")}
              />
            )}
          </div>
          <Messages error={error} notice={notice} />
        </>
      )}
    </Panel>
  );
}

// ── E: establishments (minimum-wage zone) and state ISN ─────────────────────
export function MXIsnRegistrationsPanel({ detail, readOnly, reload }) {
  const { run, error, notice, busy } = useAction(reload);
  return (
    <Panel letter="E" title="Establishments and state ISN" testId="mx-panel-e"
      hint="The minimum-wage zone is derived from the transcribed ZLFN list, never typed. Only supported states can register for ISN (CDMX); a registration is effective only while that state's ISN pack is Active (MX-045).">
      <Table rows={detail.establishments} empty="No establishment recorded." columns={[
        { key: "name", label: "Establishment" }, { key: "stateCode", label: "State" },
        { key: "municipality", label: "Municipality" }, { key: "postalCode", label: "CP" },
        { key: "zone", label: "Min-wage zone", render: (r) => <span title={r.minWageZone.detail}><Badge value={r.minWageZone.zone} /></span> },
        { key: "isActive", label: "Active", render: (r) => (r.isActive ? "Yes" : "No") },
      ]} />
      <Table rows={detail.isnRegistrations} empty="No ISN registration recorded." columns={[
        { key: "stateCode", label: "State" }, { key: "localAccountNumber", label: "Local account" },
        { key: "packId", label: "Pack" }, { key: "packStatus", label: "Pack status" },
        { key: "returnFrequency", label: "Return frequency", render: (r) => r.returnFrequency || r.returnFrequencySource },
        { key: "effectiveFrom", label: "From" }, { key: "state", label: "State", render: (r) => <Badge value={r.state} /> },
      ]} />
      {!readOnly && (
        <>
          <MiniForm
            testId="mx-new-establishment" submitLabel="Add establishment" busy={busy}
            fields={[
              { key: "name", label: "Name", required: true },
              { key: "stateCode", label: "State", type: "select", options: STATE_OPTIONS, required: true },
              { key: "municipality", label: "Municipality", required: true },
              { key: "postalCode", label: "Postal code", required: true },
            ]}
            onSubmit={(s) => run(() => createMxEstablishment(detail.employerId, blankToNull(s)), "Establishment added.")}
          />
          <MiniForm
            testId="mx-new-isn" submitLabel="Register for ISN" busy={busy}
            fields={[
              { key: "stateCode", label: "State", type: "select", options: STATE_OPTIONS, required: true },
              { key: "localAccountNumber", label: "Local account number", required: true },
              { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
            ]}
            onSubmit={(s) => run(() => createMxIsnRegistration(detail.employerId, blankToNull(s)), "ISN registration recorded.")}
          />
          <Messages error={error} notice={notice} />
        </>
      )}
    </Panel>
  );
}

// ── F + G: workweek and benefits, floor-checked ─────────────────────────────
function FloorDetail({ detail }) {
  const checks = detail?.checks || [];
  return (
    <div className="flex flex-col gap-1 text-[11px] text-foreground-muted" data-testid="mx-floor-detail">
      {checks.map((c) => (
        <div key={c.on}>
          <span className="font-semibold">{c.on}: </span><Badge value={c.status} />
          {c.missing?.map((m) => <div key={m}>• {m}</div>)}
          {c.findings?.filter((f) => f.result === "FAIL").map((f) => (
            <div key={f.label}>• {f.label}: policy {f.policy ?? "none"} vs floor {f.floor} ({f.rule})</div>
          ))}
          <div>• daily limits: {c.dailyLimits}</div>
        </div>
      ))}
      {detail?.notYetCheckable?.map((n) => <div key={n.from}>• from {n.from}: {n.reason}</div>)}
    </div>
  );
}

export function MXLaborPolicyPanel({ detail, readOnly, reload, agreements = [] }) {
  const { run, error, notice, busy } = useAction(reload);
  return (
    <Panel letter="F · G" title="Workweek and benefits" testId="mx-panel-fg"
      hint="Checked against the statutory floors of the Active national content (workweek limit, aguinaldo, vacation days and premium, Sunday premium). A policy may improve on a floor, never go below it; activation needs PASS. While the content is not active the check is BLOCKED_CONTENT.">
      <Table rows={detail.laborPolicies} empty="No labour policy recorded." columns={[
        { key: "version", label: "v" }, { key: "effectiveFrom", label: "From" },
        { key: "effectiveTo", label: "To", render: (r) => r.effectiveTo || "open" },
        { key: "ordinaryWeeklyHours", label: "Weekly h" }, { key: "aguinaldoDays", label: "Aguinaldo days" },
        { key: "vacationPremiumPct", label: "Vac. premium %" }, { key: "sundayPremiumPct", label: "Sunday %" },
        { key: "floor", label: "Floor check", render: (r) => <div><Badge value={r.floorCheckStatus} /><FloorDetail detail={r.floorCheckDetail} /></div> },
        { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
        ...(readOnly ? [] : [{
          key: "activate", label: "", render: (r) => (r.status === "DRAFT" ? (
            <button type="button" className={btn} disabled={busy}
              onClick={() => run(() => activateMxLaborPolicy(r.id), "Policy activated.")}>Activate</button>
          ) : null),
        }]),
      ]} />
      {!readOnly && (
        <>
          <MiniForm
            testId="mx-new-policy" submitLabel="Record policy (DRAFT)" busy={busy}
            fields={[
              { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
              { key: "ordinaryWeeklyHours", label: "Ordinary weekly hours", required: true },
              { key: "aguinaldoDays", label: "Aguinaldo days", required: true },
              { key: "vacationDaysYear1", label: "Vacation days, year 1", required: true },
              { key: "vacationDaysLater", label: "Vacation days, year 2+", required: true },
              { key: "vacationPremiumPct", label: "Vacation premium %", required: true },
              { key: "sundayPremiumPct", label: "Sunday premium %", required: true },
              { key: "collectiveAgreementId", label: "Collective agreement (optional)", type: "select",
                options: agreements.map((a) => ({ value: a.id, label: `${a.code} v${a.version}` })) },
            ]}
            onSubmit={(s) => run(() => createMxLaborPolicy(detail.employerId, {
              effectiveFrom: s.effectiveFrom, ordinaryWeeklyHours: s.ordinaryWeeklyHours, aguinaldoDays: s.aguinaldoDays,
              vacationPolicy: [{ serviceYearFrom: 1, serviceYearTo: 1, days: s.vacationDaysYear1 },
                { serviceYearFrom: 2, serviceYearTo: null, days: s.vacationDaysLater }],
              vacationPremiumPct: s.vacationPremiumPct, sundayPremiumPct: s.sundayPremiumPct,
              collectiveAgreementId: s.collectiveAgreementId ? Number(s.collectiveAgreementId) : null,
            }), "Policy recorded as DRAFT with its floor check.")}
          />
          <Messages error={error} notice={notice} />
        </>
      )}
    </Panel>
  );
}

// ── Credentials (MX-035): references + certificate metadata only ────────────
export function MXCredentialRefsPanel({ detail, readOnly, reload }) {
  const { run, error, notice, busy } = useAction(reload);
  const [certFor, setCertFor] = useState("");
  const regOptions = detail.imssRegistrations.map((r) => ({ value: r.id, label: r.registroPatronal }));
  return (
    <Panel title="Credentials (references only)" testId="mx-panel-credentials"
      hint="CSD keys, PAC, IDSE/SUA and bank credentials live in GCP Secret Manager. Only a gcp-sm:// reference, the public certificate's fingerprint, serial and expiry are kept here — never a key, password or private certificate part.">
      <Table rows={detail.credentials} empty="No credential reference recorded." columns={[
        { key: "kind", label: "Kind" }, { key: "secretRefMasked", label: "Reference" },
        { key: "imssRegistrationId", label: "Registration", render: (r) => regOptions.find((o) => o.value === r.imssRegistrationId)?.label || "employer" },
        { key: "certificateSerial", label: "Serial" },
        { key: "fingerprintSha256", label: "SHA-256", render: (r) => (r.fingerprintSha256 ? `${r.fingerprintSha256.slice(0, 16)}…` : "—") },
        { key: "validTo", label: "Valid to", render: (r) => (r.validTo ? r.validTo.slice(0, 10) : "—") },
        { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
        ...(readOnly ? [] : [{
          key: "revoke", label: "", render: (r) => (r.status === "ACTIVE" ? (
            <button type="button" className={btn} disabled={busy} onClick={() => run(() => revokeMxCredential(r.id), "Reference revoked.")}>Revoke</button>
          ) : null),
        }]),
      ]} />
      {!readOnly && (
        <>
          <MiniForm
            testId="mx-new-credential" submitLabel="Save reference" busy={busy}
            fields={[
              { key: "kind", label: "Kind", type: "select", options: ["CSD", "PAC", "IDSE", "SUA", "BANK"], required: true },
              { key: "secretRef", label: "Secret Manager reference", required: true, placeholder: "gcp-sm://projects/<project>/secrets/<name>/versions/<n>" },
              { key: "imssRegistrationId", label: "IMSS registration (IDSE/SUA)", type: "select", options: regOptions },
            ]}
            onSubmit={(s) => run(() => createMxCredential(detail.employerId, {
              kind: s.kind, secretRef: s.secretRef, imssRegistrationId: s.imssRegistrationId ? Number(s.imssRegistrationId) : null,
            }), "Reference saved — it is shown masked from now on.")}
          />
          <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3" data-testid="mx-cert-upload">
            <select className={input} aria-label="Certificate for credential" value={certFor} onChange={(e) => setCertFor(e.target.value)}>
              <option value="">Attach the PUBLIC certificate (.cer) to…</option>
              {detail.credentials.filter((c) => c.status === "ACTIVE" && ["CSD", "IDSE"].includes(c.kind))
                .map((c) => <option key={c.id} value={c.id}>{c.kind} {c.secretRefMasked}</option>)}
            </select>
            <input type="file" accept=".cer,.crt,.pem" aria-label="Certificate file" disabled={!certFor || busy}
              onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) run(() => uploadMxCertificate(certFor, f), "Certificate read: serial, fingerprint and expiry recorded; the file itself is not kept."); }} />
            <span className="text-[11px] text-foreground-muted">DER or PEM, at most 16 KB. Never upload a .key or .pfx.</span>
          </div>
          <Messages error={error} notice={notice} />
        </>
      )}
    </Panel>
  );
}
