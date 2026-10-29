import {
  activateBrRiskAssignment, createBrCprbOption, createBrCredential, createBrEmployerVersion, createBrEstablishment,
  createBrRiskAssignment, deactivateBrEstablishment, revokeBrCredential, uploadBrCertificate,
} from "../../../../service/payrollService";
import { btn, Messages, Table, useAction } from "../brShared";
import { Badge, MiniForm, Panel } from "./brEmployerShared";
import { blankToNull } from "./brEmployerUtils";

// Brazil employer-onboarding panels (ZP-BR-ENG-001 Phase 3). Editable in the
// organisation's Compliance Centre; `readOnly` in the Super Admin Employer tab
// (the tenant owns its employer facts). No secret is ever typed here.

export const EMPLOYER_FIELDS = [
  { key: "cnpjRoot", label: "CNPJ root (first 8 characters)", required: true },
  { key: "legalName", label: "Razão social", required: true },
  { key: "tradeName", label: "Nome fantasia" },
  { key: "taxClassification", label: "Tax classification (eSocial Tabela 08)", required: true, placeholder: "99" },
  { key: "cnaePreponderant", label: "Principal CNAE (7 digits)", required: true },
  { key: "esocialEnvironment", label: "eSocial environment", type: "select", required: true,
    options: ["RESTRICTED_PRODUCTION", "PRODUCTION"] },
  { key: "contactName", label: "Contact name", required: true },
  { key: "contactCpf", label: "Contact CPF", required: true },
  { key: "contactEmail", label: "Contact email", required: true },
  { key: "contactPhone", label: "Contact phone" },
  { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
];

export function BRLegalEmployerPanel({ detail, reload, readOnly }) {
  const { run, error, notice, busy } = useAction(reload);
  const latest = detail.versions[detail.versions.length - 1];
  return (
    <Panel title="Legal employer (eSocial S-1000)" testId="br-legal-employer"
      hint="Versions are effective-dated: a change is recorded as a new version from its date and the previous one closes the day before. The CNPJ root never changes inside a legal employer.">
      <Table rows={detail.versions} columns={[
        { key: "version", label: "v" }, { key: "effectiveFrom", label: "From" },
        { key: "effectiveTo", label: "To", render: (r) => r.effectiveTo || "open" },
        { key: "cnpjRoot", label: "CNPJ root" }, { key: "legalName", label: "Razão social" },
        { key: "taxClassification", label: "Tabela 08" }, { key: "cnaePreponderant", label: "CNAE" },
        { key: "esocialEnvironment", label: "eSocial" }, { key: "contactCpf", label: "Contact CPF" },
      ]} />
      {!readOnly && (
        <MiniForm
          testId="br-new-version" submitLabel="Record new version" busy={busy} error={error} notice={notice}
          initial={{ ...latest, effectiveFrom: "", contactCpf: "" }}
          fields={EMPLOYER_FIELDS}
          onSubmit={(s) => run(() => createBrEmployerVersion(detail.employerId, blankToNull(pick(s, EMPLOYER_FIELDS))),
            "New version recorded.")}
        />
      )}
    </Panel>
  );
}

const pick = (state, fields) => Object.fromEntries(fields.map((f) => [f.key, state[f.key] ?? ""]));

const ESTABLISHMENT_FIELDS = [
  { key: "cnpj", label: "CNPJ (14 characters)", required: true },
  { key: "establishmentName", label: "Name", required: true },
  { key: "isHeadquarters", label: "Headquarters (matriz)", type: "checkbox" },
  { key: "cnae", label: "CNAE (7 digits)", required: true },
  { key: "fpasCode", label: "FPAS (Tabela 04)", required: true, placeholder: "515" },
  { key: "thirdPartyCode", label: "Terceiros code", required: true, placeholder: "0115" },
  { key: "thirdPartyPct", label: "Terceiros %", type: "number", required: true },
  { key: "fpasEvidenceRef", label: "FPAS evidence (document reference)", required: true },
  { key: "lotacaoCode", label: "Lotação code", required: true },
  { key: "postalCode", label: "CEP", required: true },
  { key: "streetAddress", label: "Street address", required: true },
  { key: "neighborhood", label: "Bairro", required: true },
  { key: "cityIbgeCode", label: "City IBGE code (7 digits)", required: true },
  { key: "stateUf", label: "UF", required: true, placeholder: "SP" },
  { key: "activeFrom", label: "Active from", type: "date", required: true },
];

export function BREstablishmentsPanel({ detail, reload, readOnly }) {
  const { run, error, notice, busy } = useAction(reload);
  const establishments = detail.establishments || [];
  const options = establishments.map((e) => ({ value: String(e.id), label: `${e.establishmentName} (${e.cnpj})` }));
  return (
    <Panel title="Establishments, RAT and FAP (eSocial S-1005)" testId="br-establishments"
      hint="Each establishment's CNPJ must start with the employer's CNPJ root; one active headquarters. FPAS / terceiros stay DECLARED until checked against eSocial Tabela 04. RAT (1/2/3 %) and FAP are recorded per calendar year, with evidence.">
      <Table rows={establishments} empty="No establishment yet." columns={[
        { key: "establishmentName", label: "Name" }, { key: "cnpj", label: "CNPJ" },
        { key: "isHeadquarters", label: "HQ", render: (r) => (r.isHeadquarters ? "Yes" : "No") },
        { key: "cnae", label: "CNAE" },
        { key: "fpas", label: "FPAS / terceiros", render: (r) => `${r.fpasCode} / ${r.thirdPartyCode} · ${r.thirdPartyPct}%` },
        { key: "fpasStatus", label: "FPAS check", render: (r) => <Badge value={r.fpasStatus} /> },
        { key: "stateUf", label: "UF" }, { key: "activeFrom", label: "Active from" },
        { key: "activeTo", label: "Active to", render: (r) => r.activeTo || "active" },
        {
          key: "risk", label: "RAT × FAP by year", render: (r) => (
            <span className="flex flex-col gap-1">
              {(r.riskAssignments || []).map((a) => (
                <span key={a.id} className="flex items-center gap-1">
                  {a.calendarYear}: {a.ratPct}% × {a.fapFactor} <Badge value={a.status} />
                  {!readOnly && a.status === "DRAFT" && (
                    <button type="button" className={btn} disabled={busy}
                      onClick={() => run(() => activateBrRiskAssignment(a.id), "Risk assignment activated.")}>Activate</button>
                  )}
                </span>
              ))}
              {(r.riskAssignments || []).length === 0 && <span className="text-foreground-muted">none</span>}
            </span>
          ),
        },
      ]} />
      {!readOnly && (
        <>
          <MiniForm testId="br-new-establishment" submitLabel="Add establishment" busy={busy} error={error} notice={notice}
            initial={{ isHeadquarters: false }} fields={ESTABLISHMENT_FIELDS}
            onSubmit={(s) => run(() => createBrEstablishment(detail.employerId,
              blankToNull({ ...pick(s, ESTABLISHMENT_FIELDS), isHeadquarters: Boolean(s.isHeadquarters) })),
            "Establishment added.")}
          />
          {establishments.length > 0 && (
            <MiniForm testId="br-new-risk" submitLabel="Record RAT / FAP (DRAFT)" busy={busy}
              fields={[
                { key: "establishmentId", label: "Establishment", type: "select", options, required: true },
                { key: "calendarYear", label: "Calendar year", type: "number", required: true },
                { key: "ratPct", label: "RAT %", type: "select", options: ["1", "2", "3"], required: true },
                { key: "fapFactor", label: "FAP (0.5000–2.0000)", required: true },
                { key: "evidenceRef", label: "Evidence (FAP notice reference)", required: true },
              ]}
              onSubmit={(s) => run(() => createBrRiskAssignment(Number(s.establishmentId), {
                calendarYear: Number(s.calendarYear), ratPct: s.ratPct, fapFactor: s.fapFactor, evidenceRef: s.evidenceRef,
              }), "Risk assignment recorded as DRAFT — activate it to use it.")}
            />
          )}
          {establishments.some((e) => !e.activeTo) && (
            <MiniForm testId="br-deactivate-establishment" submitLabel="Deactivate" busy={busy}
              fields={[
                { key: "establishmentId", label: "Establishment", type: "select", required: true,
                  options: establishments.filter((e) => !e.activeTo).map((e) => ({ value: String(e.id), label: e.establishmentName })) },
                { key: "activeTo", label: "Last active day", type: "date", required: true },
              ]}
              onSubmit={(s) => run(() => deactivateBrEstablishment(Number(s.establishmentId), s.activeTo), "Establishment deactivated.")}
            />
          )}
        </>
      )}
    </Panel>
  );
}

export function BRCprbPanel({ detail, reload, readOnly }) {
  const { run, error, notice, busy } = useAction(reload);
  return (
    <Panel title="CPRB option by year (Lei 14.973/2024)" testId="br-cprb"
      hint="Record the option for every calendar year — 'not opted' means standard CPP. Sector eligibility is not yet checked against a saved source, so an opted year shows as a WARNING in readiness.">
      <Table rows={detail.cprbOptions || []} empty="No CPRB option recorded." columns={[
        { key: "calendarYear", label: "Year" }, { key: "opted", label: "Opted", render: (r) => (r.opted ? "Yes" : "No") },
        { key: "cprbRatePct", label: "CPRB %", render: (r) => r.cprbRatePct ?? "—" },
        { key: "sectorReference", label: "Sector", render: (r) => r.sectorReference ?? "—" },
        { key: "evidenceRef", label: "Evidence" }, { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
      ]} />
      {!readOnly && (
        <MiniForm testId="br-new-cprb" submitLabel="Record option" busy={busy} error={error} notice={notice}
          initial={{ opted: false }}
          fields={[
            { key: "calendarYear", label: "Calendar year", type: "number", required: true },
            { key: "opted", label: "Opted into CPRB", type: "checkbox" },
            { key: "cprbRatePct", label: "CPRB % (if opted)", type: "number" },
            { key: "sectorReference", label: "Sector (if opted)" },
            { key: "evidenceRef", label: "Evidence reference", required: true },
          ]}
          onSubmit={(s) => run(() => createBrCprbOption(detail.employerId, blankToNull({
            calendarYear: Number(s.calendarYear), opted: Boolean(s.opted), cprbRatePct: s.opted ? s.cprbRatePct : "",
            sectorReference: s.opted ? s.sectorReference : "", evidenceRef: s.evidenceRef,
          })), "CPRB option recorded.")}
        />
      )}
    </Panel>
  );
}

export function BRCredentialsPanel({ detail, reload, readOnly }) {
  const { run, error, notice, busy } = useAction(reload);
  return (
    <Panel title="Credentials (references only)" testId="br-credentials"
      hint="The eSocial A1 certificate and bank credentials are stored as Secret Manager references (gcp-sm://…) — never the secret, and never the A1 .pfx/.p12 file (it contains the private key). You may attach the PUBLIC certificate (.cer) so its validity can be checked.">
      <Table rows={detail.credentials || []} empty="No credential reference recorded." columns={[
        { key: "kind", label: "Kind" }, { key: "secretRefMasked", label: "Reference" },
        { key: "status", label: "Status", render: (r) => <Badge value={r.status} /> },
        { key: "validTo", label: "Certificate valid to", render: (r) => (r.validTo ? r.validTo.slice(0, 10) : "—") },
        { key: "fingerprintSha256", label: "Fingerprint", render: (r) => (r.fingerprintSha256 ? `${r.fingerprintSha256.slice(0, 12)}…` : "—") },
        ...(readOnly ? [] : [{
          key: "actions", label: "", render: (r) => (r.status === "ACTIVE" ? (
            <span className="flex flex-wrap items-center gap-2">
              {r.kind === "ESOCIAL_A1" && (
                <label className={`${btn} cursor-pointer`}>
                  Attach public .cer
                  <input type="file" accept=".cer,.crt,.pem" className="hidden" aria-label="Public certificate"
                    onChange={(e) => { const f = e.target.files?.[0]; e.target.value = ""; if (f) run(() => uploadBrCertificate(r.id, f), "Certificate attached."); }} />
                </label>
              )}
              <button type="button" className={btn} disabled={busy} onClick={() => run(() => revokeBrCredential(r.id), "Credential revoked.")}>Revoke</button>
            </span>
          ) : null),
        }]),
      ]} />
      {!readOnly && (
        <MiniForm testId="br-new-credential" submitLabel="Record reference" busy={busy} error={error} notice={notice}
          fields={[
            { key: "kind", label: "Kind", type: "select", options: ["ESOCIAL_A1", "BANK"], required: true },
            { key: "secretRef", label: "Secret Manager reference", required: true,
              placeholder: "gcp-sm://projects/<project>/secrets/<name>/versions/1" },
          ]}
          onSubmit={(s) => run(() => createBrCredential(detail.employerId, { kind: s.kind, secretRef: s.secretRef }),
            "Reference recorded (the full reference is not shown again).")}
        />
      )}
      {readOnly && <Messages error={error} notice={notice} />}
    </Panel>
  );
}
