import React, { useEffect, useState } from "react";
import { ShieldAlert, Plus, Check } from "lucide-react";
import {
  listPapAssets, ingestPapAsset, approvePapAsset, setPapAssetStatus,
  listPapReleases, getPapReleaseGateStatus, createPapRelease,
  recordPapReleaseSourceIdentity, recordPapReleaseSourceHash, recordPapReleaseSourceFinality,
  recordPapReleaseLicensing, recordPapReleaseGoldenVectors, recordPapReleaseSecurityCertification,
  markPapReleaseReady, approvePapRelease, rejectPapRelease, activatePapRelease,
  requestPapRollback, rejectPapRollback, approvePapRollback,
  listHealthFunds, createHealthFund, approveHealthFund, setHealthFundStatus,
  listU1Tariffs, createU1Tariff, approveU1Tariff, setU1TariffStatus,
  listContributionCeilings, createContributionCeiling, approveContributionCeiling, setContributionCeilingStatus,
  listPvConfigurations, createPvConfiguration, approvePvConfiguration, setPvConfigurationStatus,
  getChurchTaxMatrix, getSourceArtifacts, createSourceArtifact, reviewSourceArtifact,
  getTaxConfigurationAudit,
  listGermanyChurchTaxExceptions, createGermanyChurchTaxException,
  approveGermanyChurchTaxException, setGermanyChurchTaxExceptionStatus,
  listEarningTaxabilityRules, createEarningTaxabilityRule, approveEarningTaxabilityRule, setEarningTaxabilityRuleStatus,
  listOvertimePremiumCategories, createOvertimePremiumCategory, approveOvertimePremiumCategory, setOvertimePremiumCategoryStatus,
  listOvertimeGrundlohnCaps, createOvertimeGrundlohnCap, approveOvertimeGrundlohnCap, setOvertimeGrundlohnCapStatus,
  listOrganizationsForPicker,
  listGermanyAccidentInsuranceProfiles, createGermanyAccidentInsuranceProfile,
  approveGermanyAccidentInsuranceProfile, setGermanyAccidentInsuranceProfileStatus,
} from "../../service/superAdminService";
import {
  createElstamChangeListBatch, listElstamChangeListBatches, updateElstamChangeListBatchStatus,
} from "../../service/payrollService";
import { describeLoadError } from "../../service/errorClassification";

export const TABS = [
  { key: "pap", label: "PAP / Releases" },
  { key: "health-funds", label: "Health Funds" },
  { key: "ceilings", label: "Contribution Ceilings" },
  { key: "pv", label: "PV Configuration" },
  { key: "earning-taxability", label: "Earning Taxability" },
  { key: "overtime-premium-categories", label: "Overtime Premium Categories" },
  { key: "overtime-grundlohn-caps", label: "Overtime Grundlohn Caps" },
  { key: "employer-levies", label: "Employer Levies (Accident Insurance)" },
  { key: "church-tax", label: "Church Tax" },
  { key: "elstam-batches", label: "ELStAM Change-List Batches" },
  { key: "source-evidence", label: "Source Evidence" },
  { key: "audit", label: "Audit / History" },
];

// ── Shared UI primitives ──────────────────────────────────────────────────

function Card({ title, action, children }) {
  return (
    <div className="rounded-[16px] border border-border bg-surface p-5 mb-5">
      <div className="flex items-center justify-between mb-3">
        <h3 className="text-[13px] font-bold text-foreground">{title}</h3>
        {action}
      </div>
      {children}
    </div>
  );
}

export function StatusPill({ value }) {
  const tone =
    value === "PUBLISHED" || value === "ACTIVE" || value === "APPROVED" || value === "APPLIED"
      ? "bg-primary/10 text-primary"
      : value === "REJECTED" || value === "SUPERSEDED"
      ? "bg-error/10 text-error"
      : "bg-warning/10 text-warning";
  return <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold ${tone}`}>{value || "—"}</span>;
}

const inputCls = "w-full rounded-[10px] border border-border bg-surface px-3 py-2 text-[12px] text-foreground outline-none focus:border-primary";
const btnPrimary = "rounded-[10px] bg-primary px-3 py-1.5 text-[12px] font-bold text-white transition-colors hover:bg-primary-hover disabled:opacity-50";
const btnSecondary = "rounded-[10px] border border-border bg-surface-muted px-3 py-1.5 text-[12px] font-semibold text-foreground-muted transition-colors hover:border-primary disabled:opacity-50";

function Th({ children }) {
  return <th className="px-3 py-2 text-left font-semibold text-foreground-muted">{children}</th>;
}
function Td({ children, className = "" }) {
  return <td className={`px-3 py-2 text-foreground ${className}`}>{children}</td>;
}

// `message` may be a plain string (write-action errors) or the
// `{message, schemaUnavailable}` shape useLoader below produces for a
// failed list load — a 503 SCHEMA_UNAVAILABLE (a required migration has
// not been applied to this environment yet, found during the Super
// Admin stabilization audit) renders as a distinct, honest "deployment
// required" notice rather than a generic red error, so it is never
// confused with "configured but empty" or an ordinary application error.
function ErrorBanner({ message }) {
  if (!message) return null;
  if (typeof message === "object" && message.schemaUnavailable) {
    return (
      <div className="mb-3 rounded-[10px] bg-warning/10 px-3 py-2 text-[12px] text-warning border border-warning/20">
        <span className="font-bold">Configuration unavailable — </span>
        {message.message}
      </div>
    );
  }
  // Phase 8AW: a genuine network-level failure (backend unreachable —
  // down, wrong host/port, or blocked by CORS) previously fell through to
  // this same generic red banner showing the browser's own raw
  // "Failed to fetch" string — indistinguishable from an application
  // defect and unactionable for an operator. Rendered distinctly here
  // (same tone as the schema-unavailable notice — an environment/
  // deployment condition, not a bug in this page).
  if (typeof message === "object" && message.networkError) {
    return (
      <div className="mb-3 rounded-[10px] bg-warning/10 px-3 py-2 text-[12px] text-warning border border-warning/20">
        <span className="font-bold">Backend unreachable — </span>
        {message.message}
      </div>
    );
  }
  const text = typeof message === "object" ? message.message : message;
  return <div className="mb-3 rounded-[10px] bg-error/10 px-3 py-2 text-[12px] text-error border border-error/20">{text}</div>;
}

function useLoader(fn, deps) {
  const [data, setData] = useState(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [nonce, setNonce] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError("");
    fn()
      .then((res) => !cancelled && setData(res))
      .catch((err) => !cancelled && setError(describeLoadError(err)))
      .finally(() => !cancelled && setLoading(false));
    return () => { cancelled = true; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, nonce]);
  return [data, error, loading, () => setNonce((n) => n + 1)];
}

// ── PAP / Releases tab ────────────────────────────────────────────────────

export function PapTab() {
  const [assets, assetsError, assetsLoading, reloadAssets] = useLoader(() => listPapAssets(), []);
  const [releases, releasesError, releasesLoading, reloadReleases] = useLoader(() => listPapReleases(), []);
  const [gateStatuses, setGateStatuses] = useState({});
  const [actionError, setActionError] = useState("");
  const [showIngest, setShowIngest] = useState(false);
  const [ingestForm, setIngestForm] = useState({
    taxYear: "2026", papVersion: "", effectiveFrom: "2026-01-01", effectiveTo: "",
    sourceAgency: "", sourceTitle: "", sourceUrl: "", sourcePublicationDate: "", file: null,
  });
  const [ingesting, setIngesting] = useState(false);

  useEffect(() => {
    if (!releases) return;
    releases.forEach((r) => {
      getPapReleaseGateStatus(r.id).then((g) => setGateStatuses((prev) => ({ ...prev, [r.id]: g }))).catch(() => {});
    });
  }, [releases]);

  async function runAction(fn) {
    setActionError("");
    try {
      await fn();
      reloadAssets();
      reloadReleases();
    } catch (err) {
      setActionError(err.message || "Action failed.");
    }
  }

  async function handleIngest(e) {
    e.preventDefault();
    setIngesting(true);
    setActionError("");
    try {
      await ingestPapAsset(ingestForm);
      setShowIngest(false);
      reloadAssets();
    } catch (err) {
      setActionError(err.message || "Ingest failed.");
    } finally {
      setIngesting(false);
    }
  }

  return (
    <>
      <ErrorBanner message={actionError} />

      <Card
        title="BMF PAP algorithm assets"
        action={
          <button className={btnSecondary} onClick={() => setShowIngest((v) => !v)}>
            <Plus size={12} className="inline -mt-0.5 mr-1" /> Ingest new asset
          </button>
        }
      >
        {showIngest && (
          <form onSubmit={handleIngest} className="mb-4 grid grid-cols-2 gap-2 rounded-[10px] border border-border p-3">
            <input className={inputCls} placeholder="Tax year (2026)" required value={ingestForm.taxYear} onChange={(e) => setIngestForm((f) => ({ ...f, taxYear: e.target.value }))} />
            <input className={inputCls} placeholder="PAP version" required value={ingestForm.papVersion} onChange={(e) => setIngestForm((f) => ({ ...f, papVersion: e.target.value }))} />
            <input type="date" className={inputCls} required value={ingestForm.effectiveFrom} onChange={(e) => setIngestForm((f) => ({ ...f, effectiveFrom: e.target.value }))} />
            <input type="date" className={inputCls} placeholder="Effective to" value={ingestForm.effectiveTo} onChange={(e) => setIngestForm((f) => ({ ...f, effectiveTo: e.target.value }))} />
            <input className={inputCls} placeholder="Source agency (e.g. BMF/ITZBund)" required value={ingestForm.sourceAgency} onChange={(e) => setIngestForm((f) => ({ ...f, sourceAgency: e.target.value }))} />
            <input className={inputCls} placeholder="Source title" required value={ingestForm.sourceTitle} onChange={(e) => setIngestForm((f) => ({ ...f, sourceTitle: e.target.value }))} />
            <input className={inputCls} placeholder="Source URL" value={ingestForm.sourceUrl} onChange={(e) => setIngestForm((f) => ({ ...f, sourceUrl: e.target.value }))} />
            <input type="date" className={inputCls} placeholder="Source publication date" value={ingestForm.sourcePublicationDate} onChange={(e) => setIngestForm((f) => ({ ...f, sourcePublicationDate: e.target.value }))} />
            <input type="file" required className="col-span-2 text-[12px]" onChange={(e) => setIngestForm((f) => ({ ...f, file: e.target.files[0] }))} />
            <button type="submit" disabled={ingesting} className={`${btnPrimary} col-span-2`}>{ingesting ? "Uploading…" : "Ingest DRAFT asset"}</button>
          </form>
        )}
        {assetsLoading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
        <ErrorBanner message={assetsError} />
        {assets && assets.length === 0 && <p className="text-[12px] text-foreground-muted">No PAP asset has ever been ingested in this environment.</p>}
        {assets && assets.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-[12px]">
              <thead><tr><Th>Version</Th><Th>Effective</Th><Th>Status</Th><Th>Hash</Th><Th>Actions</Th></tr></thead>
              <tbody>
                {assets.map((a) => (
                  <tr key={a.id} className="border-t border-border">
                    <Td>{a.papVersion}</Td>
                    <Td>{a.effectiveFrom} → {a.effectiveTo || "open"}</Td>
                    <Td><StatusPill value={a.status} /></Td>
                    <Td className="font-mono">{a.sourceContentSha256 ? `${a.sourceContentSha256.slice(0, 12)}…` : "—"}</Td>
                    <Td>
                      <div className="flex gap-1.5">
                        <button className={btnSecondary} onClick={() => runAction(() => approvePapAsset(a.id))}>Approve</button>
                        <button className={btnSecondary} onClick={() => runAction(() => createPapRelease(a.id))}>Start release</button>
                      </div>
                    </Td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>

      <Card title="Production release governance (8 gate dimensions)">
        {releasesLoading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
        <ErrorBanner message={releasesError} />
        {releases && releases.length === 0 && <p className="text-[12px] text-foreground-muted">No release governance record started yet.</p>}
        {releases && releases.map((r) => {
          const gate = gateStatuses[r.id];
          return (
            <div key={r.id} className="mb-4 rounded-[12px] border border-border p-4">
              <div className="flex items-center justify-between mb-2">
                <span className="text-[12px] font-bold text-foreground">Release #{r.id} — PAP asset #{r.papAssetId}</span>
                <StatusPill value={r.status} />
              </div>

              {gate && (
                <div className="mb-3 grid grid-cols-2 gap-x-4 gap-y-1 text-[11px]">
                  {Object.entries(gate.gates).map(([name, ok]) => (
                    <div key={name} className="flex items-center gap-1.5">
                      <span className={ok ? "text-primary" : "text-error"}>{ok ? "✓" : "✕"}</span>
                      <span className="text-foreground-muted">{name}</span>
                    </div>
                  ))}
                </div>
              )}

              {gate && !gate.isActivationEligible && (
                <div className="mb-3 flex items-start gap-2 rounded-[10px] border border-warning/30 bg-warning/10 px-3 py-2 text-[11px] text-foreground">
                  <ShieldAlert size={13} className="mt-0.5 shrink-0 text-warning" />
                  PAP production activation is blocked pending external authorization/source evidence — failed gates: {gate.failedGates.join(", ")}.
                </div>
              )}

              <div className="flex flex-wrap gap-1.5">
                <button className={btnSecondary} onClick={() => runAction(() => recordPapReleaseSourceIdentity(r.id, "Reviewed."))}>Record source identity</button>
                <button className={btnSecondary} onClick={() => runAction(() => recordPapReleaseSourceHash(r.id))}>Re-verify source hash</button>
                <button className={btnSecondary} onClick={() => runAction(() => recordPapReleaseSourceFinality(r.id, { status: "OPEN" }))}>Record source finality</button>
                <button className={btnSecondary} onClick={() => runAction(() => recordPapReleaseLicensing(r.id, { status: "PENDING" }))}>Record licensing</button>
                <button className={btnSecondary} onClick={() => runAction(() => recordPapReleaseGoldenVectors(r.id, { sourceSha256: r.boundSourceContentSha256 || "" }))}>Record golden vectors</button>
                <button className={btnSecondary} onClick={() => runAction(() => recordPapReleaseSecurityCertification(r.id, "Reviewed."))}>Record security certification</button>
                <button className={btnSecondary} onClick={() => runAction(() => markPapReleaseReady(r.id))}>Mark ready</button>
                <button className={btnSecondary} onClick={() => runAction(() => approvePapRelease(r.id))}>Approve</button>
                <button className={btnSecondary} onClick={() => runAction(() => rejectPapRelease(r.id, "Rejected via Super Admin UI."))}>Reject</button>
                <button
                  className={btnPrimary}
                  disabled={!gate || !gate.isActivationEligible}
                  title={!gate || !gate.isActivationEligible ? "Blocked — every gate must be satisfied first" : "Activate"}
                  onClick={() => runAction(() => activatePapRelease(r.id))}
                >
                  Activate
                </button>
                {r.status === "ACTIVE" && (
                  <button className={btnSecondary} onClick={() => runAction(() => requestPapRollback(r.id, "Requested via Super Admin UI."))}>Request rollback</button>
                )}
              </div>
            </div>
          );
        })}
      </Card>
    </>
  );
}

// ── Generic effective-dated registry tab (Health Fund / Ceiling / PV) ────

function LifecycleRegistryTab({
  title, list, create, approve, setStatus, columns, formFields, defaultForm,
}) {
  const [rows, error, loading, reload] = useLoader(list, []);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState(defaultForm);
  const [actionError, setActionError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleCreate(e) {
    e.preventDefault();
    setSaving(true);
    setActionError("");
    try {
      await create(form);
      setShowForm(false);
      setForm(defaultForm);
      reload();
    } catch (err) {
      setActionError(err.message || "Could not save.");
    } finally {
      setSaving(false);
    }
  }

  async function runAction(fn) {
    setActionError("");
    try {
      await fn();
      reload();
    } catch (err) {
      setActionError(err.message || "Action failed.");
    }
  }

  return (
    <Card
      title={title}
      action={<button className={btnSecondary} onClick={() => setShowForm((v) => !v)}><Plus size={12} className="inline -mt-0.5 mr-1" /> New draft version</button>}
    >
      <ErrorBanner message={actionError} />
      {showForm && (
        <form onSubmit={handleCreate} className="mb-4 grid grid-cols-2 gap-2 rounded-[10px] border border-border p-3">
          {formFields.map((f) => (
            <label key={f.key} className={f.span2 ? "col-span-2" : ""}>
              <span className="mb-1 block text-[11px] font-semibold text-foreground-muted">{f.label}</span>
              {f.type === "select" ? (
                <select className={inputCls} value={form[f.key]} onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}>
                  {f.options.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
              ) : f.type === "checkbox" ? (
                <input type="checkbox" checked={!!form[f.key]} onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.checked }))} />
              ) : (
                <input
                  className={inputCls} type={f.type || "text"} required={f.required}
                  value={form[f.key]} onChange={(e) => setForm((s) => ({ ...s, [f.key]: e.target.value }))}
                />
              )}
            </label>
          ))}
          <button type="submit" disabled={saving} className={`${btnPrimary} col-span-2`}>{saving ? "Saving…" : "Save DRAFT"}</button>
        </form>
      )}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      <ErrorBanner message={error} />
      {rows && rows.length === 0 && <p className="text-[12px] text-foreground-muted">No records yet.</p>}
      {rows && rows.length > 0 && (
        <div className="overflow-x-auto">
          <table className="w-full text-[12px]">
            <thead><tr>{columns.map((c) => <Th key={c.key}>{c.label}</Th>)}<Th>Status</Th><Th>Source</Th><Th>Actions</Th></tr></thead>
            <tbody>
              {rows.map((row) => (
                <tr key={row.id} className="border-t border-border">
                  {columns.map((c) => <Td key={c.key}>{c.render ? c.render(row) : row[c.key]}</Td>)}
                  <Td><StatusPill value={row.status} /></Td>
                  <Td>{row.authoritySourceId ? `#${row.authoritySourceId}` : <span className="text-warning">missing</span>}</Td>
                  <Td>
                    <div className="flex gap-1.5">
                      <button className={btnSecondary} onClick={() => runAction(() => approve(row.id))}>Approve</button>
                      <button className={btnSecondary} onClick={() => runAction(() => setStatus(row.id, "VERIFIED"))}>Verify</button>
                      <button
                        className={btnPrimary}
                        title={!row.authoritySourceId ? "Blocked — no linked source evidence artifact" : "Publish"}
                        onClick={() => runAction(() => setStatus(row.id, "PUBLISHED"))}
                      >
                        Publish
                      </button>
                    </div>
                  </Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function U1TariffsTab() {
  return (
    <LifecycleRegistryTab
      title="U1 tariffs (employer-elected sickness reimbursement)"
      list={() => listU1Tariffs()}
      create={(f) => createU1Tariff({
        healthFundId: f.healthFundId, tariffIdentifier: f.tariffIdentifier, tariffName: f.tariffName || undefined,
        reimbursementPct: f.reimbursementPct, levyRatePct: f.levyRatePct,
        effectiveFrom: f.effectiveFrom, effectiveTo: f.effectiveTo || undefined,
        authoritySourceId: f.authoritySourceId || undefined,
      })}
      approve={approveU1Tariff}
      setStatus={setU1TariffStatus}
      columns={[
        { key: "healthFundId", label: "Fund code" },
        { key: "tariffIdentifier", label: "Tariff" },
        { key: "reimbursementPct", label: "Reimbursement %" },
        { key: "levyRatePct", label: "Levy %" },
        { key: "effectiveFrom", label: "Effective from" },
        { key: "effectiveTo", label: "Effective to", render: (r) => r.effectiveTo || "open" },
      ]}
      formFields={[
        { key: "healthFundId", label: "Fund code", required: true },
        { key: "tariffIdentifier", label: "Tariff identifier (e.g. U1_50)", required: true },
        { key: "tariffName", label: "Tariff name" },
        { key: "reimbursementPct", label: "Reimbursement % (e.g. 50)", type: "number", required: true },
        { key: "levyRatePct", label: "Levy rate % (e.g. 1.3)", type: "number", required: true },
        { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
        { key: "effectiveTo", label: "Effective to (leave blank if open-ended)", type: "date" },
        { key: "authoritySourceId", label: "Source evidence artifact ID" },
      ]}
      defaultForm={{
        healthFundId: "TK", tariffIdentifier: "U1_50", tariffName: "", reimbursementPct: "", levyRatePct: "",
        effectiveFrom: "2026-01-01", effectiveTo: "", authoritySourceId: "",
      }}
    />
  );
}

export function HealthFundsTab() {
  return (
    <>
      <Card title="U1 / U2 (health-fund-specific) &amp; accident insurance">
        <p className="text-[11px] text-foreground-muted">
          U1 (sickness reimbursement) and U2 (maternity levy) are set per Krankenkasse, right here on each fund's own
          row (spec DE-D06) — never a national rate. U1 is <strong>employer-elected per tariff</strong>: each fund
          publishes multiple U1 tariff options (different reimbursement % and corresponding levy %), and the employer
          selects one. Manage those tariffs in the "U1 Tariffs" tab below — once a tariff is published, an employer
          references it via the employee's statutory profile (<code>de_u1_tariff_id</code>). <strong>Accident
          insurance</strong> (Berufsgenossenschaft carrier/risk-class assessment) is a per-employer statutory fact, not a
          fund rate — it reuses the existing Employer Tax Profile mechanism (the same one US SUI uses): Super Admin &gt;
          Compliance &gt; Employer Tax Profiles, jurisdiction "DE", component "DE_ACCIDENT_INSURANCE". No dedicated
          Germany UI panel for it yet — the API and calculation-trace visibility are complete; a Germany-labeled panel is
          a follow-up item.
        </p>
      </Card>
      <LifecycleRegistryTab
      title="Krankenkasse (health fund) supplementary-rate registry"
      list={() => listHealthFunds()}
      create={(f) => createHealthFund({
        healthFundId: f.healthFundId, fundName: f.fundName, supplementaryRatePct: f.supplementaryRatePct,
        isAverageRate: f.isAverageRate, u1RatePct: f.u1RatePct || undefined, u2RatePct: f.u2RatePct || undefined,
        effectiveFrom: f.effectiveFrom, authoritySourceId: f.authoritySourceId || undefined,
      })}
      approve={approveHealthFund}
      setStatus={setHealthFundStatus}
      columns={[
        { key: "healthFundId", label: "Fund code" },
        { key: "fundName", label: "Fund name" },
        { key: "supplementaryRatePct", label: "Zusatzbeitrag %" },
        { key: "u1RatePct", label: "U1 % (deprecated)", render: (r) => r.u1RatePct ?? "NOT_CONFIGURED" },
        { key: "u2RatePct", label: "U2 %", render: (r) => r.u2RatePct ?? "NOT_CONFIGURED" },
        { key: "effectiveFrom", label: "Effective from" },
      ]}
      formFields={[
        { key: "healthFundId", label: "Fund code", required: true },
        { key: "fundName", label: "Fund name", required: true },
        { key: "supplementaryRatePct", label: "Supplementary rate %", type: "number", required: true },
        { key: "u1RatePct", label: "U1 rate % (deprecated — use U1 Tariffs tab)", type: "number" },
        { key: "u2RatePct", label: "U2 rate % (maternity levy, optional)", type: "number" },
        { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
        { key: "authoritySourceId", label: "Source evidence artifact ID" },
        { key: "isAverageRate", label: "Statutory average-rate case only", type: "checkbox" },
      ]}
      defaultForm={{
        healthFundId: "", fundName: "", supplementaryRatePct: "", u1RatePct: "", u2RatePct: "",
        effectiveFrom: "2026-01-01", authoritySourceId: "", isAverageRate: false,
      }}
      />
      <U1TariffsTab />
    </>
  );
}

export function ContributionCeilingsTab() {
  return (
    <LifecycleRegistryTab
      title="Contribution ceilings (RV/ALV and GKV/PV branches)"
      list={() => listContributionCeilings()}
      create={(f) => createContributionCeiling({
        branch: f.branch, monthlyCeiling: f.monthlyCeiling, annualCeiling: f.annualCeiling,
        effectiveFrom: f.effectiveFrom, authoritySourceId: f.authoritySourceId || undefined,
      })}
      approve={approveContributionCeiling}
      setStatus={setContributionCeilingStatus}
      columns={[
        { key: "branch", label: "Branch" },
        { key: "monthlyCeiling", label: "Monthly ceiling (€)" },
        { key: "annualCeiling", label: "Annual ceiling (€)" },
        { key: "effectiveFrom", label: "Effective from" },
      ]}
      formFields={[
        { key: "branch", label: "Branch", type: "select", options: [{ value: "RV_ALV", label: "RV_ALV" }, { value: "GKV_PV", label: "GKV_PV" }] },
        { key: "monthlyCeiling", label: "Monthly ceiling (€)", type: "number", required: true },
        { key: "annualCeiling", label: "Annual ceiling (€)", type: "number", required: true },
        { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
        { key: "authoritySourceId", label: "Source evidence artifact ID" },
      ]}
      defaultForm={{ branch: "RV_ALV", monthlyCeiling: "", annualCeiling: "", effectiveFrom: "2026-01-01", authoritySourceId: "" }}
    />
  );
}

export function PvConfigTab() {
  return (
    <LifecycleRegistryTab
      title="PV (long-term care) child/Saxony rate configuration"
      list={() => listPvConfigurations()}
      create={(f) => createPvConfiguration({
        childCategory: f.childCategory, isSaxony: f.isSaxony === "true" || f.isSaxony === true,
        totalRatePct: f.totalRatePct, standardEmployeeRatePct: f.standardEmployeeRatePct,
        employerRatePct: f.employerRatePct, saxonyEmployeeRatePct: f.saxonyEmployeeRatePct,
        saxonyEmployerRatePct: f.saxonyEmployerRatePct, effectiveFrom: f.effectiveFrom,
        authoritySourceId: f.authoritySourceId || undefined,
      })}
      approve={approvePvConfiguration}
      setStatus={setPvConfigurationStatus}
      columns={[
        { key: "childCategory", label: "Child category" },
        { key: "isSaxony", label: "Saxony?", render: (r) => (r.isSaxony ? "Yes" : "No") },
        { key: "totalRatePct", label: "Total %" },
        { key: "standardEmployeeRatePct", label: "Employee % (standard)" },
        { key: "saxonyEmployeeRatePct", label: "Employee % (Saxony)" },
      ]}
      formFields={[
        { key: "childCategory", label: "Child category", type: "select", options: ["CHILDLESS", "1", "2", "3", "4", "5_PLUS"].map((v) => ({ value: v, label: v })) },
        { key: "isSaxony", label: "Applies to Saxony", type: "select", options: [{ value: "false", label: "Standard (non-Saxony)" }, { value: "true", label: "Saxony" }] },
        { key: "totalRatePct", label: "Total rate %", type: "number", required: true },
        { key: "standardEmployeeRatePct", label: "Employee % (standard)", type: "number", required: true },
        { key: "employerRatePct", label: "Employer %", type: "number", required: true },
        { key: "saxonyEmployeeRatePct", label: "Employee % (Saxony)", type: "number", required: true },
        { key: "saxonyEmployerRatePct", label: "Employer % (Saxony)", type: "number", required: true },
        { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
        { key: "authoritySourceId", label: "Source evidence artifact ID", span2: true },
      ]}
      defaultForm={{
        childCategory: "CHILDLESS", isSaxony: "false", totalRatePct: "", standardEmployeeRatePct: "",
        employerRatePct: "", saxonyEmployeeRatePct: "", saxonyEmployerRatePct: "", effectiveFrom: "2026-01-01", authoritySourceId: "",
      }}
    />
  );
}

// ── Earning/deduction taxability (Phase 8T, four-dimension model) ───────

const EARNING_TYPES = [
  "REGULAR_SALARY", "OVERTIME_SHIFT_PREMIUM", "BONUS_ANNUAL_BONUS", "PENSION_VERSORGUNGSBEZUG",
  "EQUITY_BENEFIT_19A", "EXPENSE_REIMBURSEMENT", "OCCUPATIONAL_PENSION_CONTRIBUTION",
  "GARNISHMENT_ATTACHMENT", "EMPLOYEE_VOLUNTARY_DEDUCTION",
];
const WAGE_TAX_TREATMENTS = [
  "TAXABLE_REGULAR", "OTHER_REMUNERATION_SONSTB", "SPECIAL_PAP_HANDLING",
  "CONDITIONALLY_EXEMPT", "POST_TAX_NO_TAX_IMPACT", "SCHEME_LIMIT_SPECIFIC", "NOT_SPECIFIED",
];
const SI_TREATMENTS = [
  "CONTRIBUTORY", "CONTRIBUTORY_SUBJECT_TO_ALLOCATION", "MAY_DIFFER", "OFTEN_NON_CONTRIBUTORY",
  "NO_CHANGE_TO_BASE", "COVERAGE_SPECIFIC", "CLASSIFICATION_SPECIFIC", "SCHEME_LIMIT_SPECIFIC", "NOT_SPECIFIED",
];

export function EarningTaxabilityTab() {
  return (
    <>
      <Card title="Four-dimension taxability model">
        <p className="text-[11px] text-foreground-muted">
          Every Germany earning/deduction type independently declares wage-tax treatment, GKV/PV treatment, RV/ALV
          treatment, and a free-text reporting classification (spec §15 gives no enumerated set for the fourth
          dimension) — never a single "Taxable" checkbox.
        </p>
      </Card>
      <LifecycleRegistryTab
        title="Earning/deduction taxability rules"
        list={() => listEarningTaxabilityRules()}
        create={(f) => createEarningTaxabilityRule({
          earningType: f.earningType, wageTaxTreatment: f.wageTaxTreatment,
          gkvPvTreatment: f.gkvPvTreatment, rvAlvTreatment: f.rvAlvTreatment,
          reportingClassification: f.reportingClassification || undefined,
          effectiveFrom: f.effectiveFrom, authoritySourceId: f.authoritySourceId || undefined,
        })}
        approve={approveEarningTaxabilityRule}
        setStatus={setEarningTaxabilityRuleStatus}
        columns={[
          { key: "earningType", label: "Earning type" },
          { key: "wageTaxTreatment", label: "Wage tax" },
          { key: "gkvPvTreatment", label: "GKV/PV" },
          { key: "rvAlvTreatment", label: "RV/ALV" },
        ]}
        formFields={[
          { key: "earningType", label: "Earning type", type: "select", options: EARNING_TYPES.map((v) => ({ value: v, label: v })) },
          { key: "wageTaxTreatment", label: "Wage tax treatment", type: "select", options: WAGE_TAX_TREATMENTS.map((v) => ({ value: v, label: v })) },
          { key: "gkvPvTreatment", label: "GKV/PV treatment", type: "select", options: SI_TREATMENTS.map((v) => ({ value: v, label: v })) },
          { key: "rvAlvTreatment", label: "RV/ALV treatment", type: "select", options: SI_TREATMENTS.map((v) => ({ value: v, label: v })) },
          { key: "reportingClassification", label: "Reporting classification (free text)", span2: true },
          { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
          { key: "authoritySourceId", label: "Source evidence artifact ID", span2: true },
        ]}
        defaultForm={{
          earningType: "REGULAR_SALARY", wageTaxTreatment: "TAXABLE_REGULAR", gkvPvTreatment: "CONTRIBUTORY",
          rvAlvTreatment: "CONTRIBUTORY", reportingClassification: "", effectiveFrom: "2026-01-01", authoritySourceId: "",
        }}
      />
    </>
  );
}

// ── Overtime/shift-premium statutory registries (Phase 8AD) ─────────────
// Configuration only — see the Phase 8AD report. Neither registry
// calculates a premium, classifies a work period, or is consumed by the
// Germany calculation engine yet.

const OVERTIME_PREMIUM_CATEGORIES = ["NIGHT_STANDARD", "NIGHT_EXTENDED", "SUNDAY", "HOLIDAY_STANDARD", "HOLIDAY_SPECIAL"];
const OVERTIME_GRUNDLOHN_DIMENSIONS = ["WAGE_TAX", "SOCIAL_INSURANCE"];

export function OvertimePremiumCategoriesTab() {
  return (
    <>
      <Card title="Statutory overtime/shift-premium categories (§3b EStG)">
        <p className="text-[11px] text-foreground-muted">
          The wage-tax-free percentage of a night/Sunday/holiday surcharge, computed on an hourly Grundlohn — see
          the separate "Overtime Grundlohn Caps" tab for the €/hour caps this percentage applies against. This
          registry does not calculate a premium amount, classify a work period as night/Sunday/holiday, or feed
          the payroll engine yet.
        </p>
      </Card>
      <LifecycleRegistryTab
        title="Overtime premium categories"
        list={() => listOvertimePremiumCategories()}
        create={(f) => createOvertimePremiumCategory({
          categoryCode: f.categoryCode, wageTaxFreePct: f.wageTaxFreePct,
          effectiveFrom: f.effectiveFrom, authoritySourceId: f.authoritySourceId || undefined,
        })}
        approve={approveOvertimePremiumCategory}
        setStatus={setOvertimePremiumCategoryStatus}
        columns={[
          { key: "categoryCode", label: "Category" },
          { key: "wageTaxFreePct", label: "Wage-tax-free %" },
          { key: "effectiveFrom", label: "Effective from" },
          { key: "effectiveTo", label: "Effective to" },
        ]}
        formFields={[
          { key: "categoryCode", label: "Category", type: "select", options: OVERTIME_PREMIUM_CATEGORIES.map((v) => ({ value: v, label: v })) },
          { key: "wageTaxFreePct", label: "Wage-tax-free %", type: "number", required: true },
          { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
          { key: "authoritySourceId", label: "Source evidence artifact ID", span2: true },
        ]}
        defaultForm={{ categoryCode: "NIGHT_STANDARD", wageTaxFreePct: "", effectiveFrom: "2026-01-01", authoritySourceId: "" }}
      />
    </>
  );
}

export function OvertimeGrundlohnCapsTab() {
  return (
    <>
      <Card title="Statutory Grundlohn caps (§3b EStG / §1 SvEV)">
        <p className="text-[11px] text-foreground-muted">
          The hourly Grundlohn ceiling used to compute overtime/shift-premium exemptions — WAGE_TAX (§3b EStG) and
          SOCIAL_INSURANCE (§1 Abs. 1 Satz 1 Nr. 1 SvEV) caps are genuinely different amounts and must never be
          confused. This is a <strong>statutory Grundlohn cap</strong>, not an employee's hourly pay rate — see the
          employee's Germany statutory profile ("Overtime / Premium Basis") for that separate, per-employee value.
        </p>
      </Card>
      <LifecycleRegistryTab
        title="Overtime Grundlohn caps"
        list={() => listOvertimeGrundlohnCaps()}
        create={(f) => createOvertimeGrundlohnCap({
          dimension: f.dimension, hourlyCapAmount: f.hourlyCapAmount,
          effectiveFrom: f.effectiveFrom, authoritySourceId: f.authoritySourceId || undefined,
        })}
        approve={approveOvertimeGrundlohnCap}
        setStatus={setOvertimeGrundlohnCapStatus}
        columns={[
          { key: "dimension", label: "Dimension" },
          { key: "hourlyCapAmount", label: "Statutory Grundlohn cap (€/hour)" },
          { key: "effectiveFrom", label: "Effective from" },
          { key: "effectiveTo", label: "Effective to" },
        ]}
        formFields={[
          { key: "dimension", label: "Dimension", type: "select", options: OVERTIME_GRUNDLOHN_DIMENSIONS.map((v) => ({ value: v, label: v })) },
          { key: "hourlyCapAmount", label: "Statutory Grundlohn cap (€/hour)", type: "number", required: true },
          { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
          { key: "authoritySourceId", label: "Source evidence artifact ID", span2: true },
        ]}
        defaultForm={{ dimension: "WAGE_TAX", hourlyCapAmount: "", effectiveFrom: "2026-01-01", authoritySourceId: "" }}
      />
    </>
  );
}

// ── Church tax (read-only) ────────────────────────────────────────────────

export function ChurchTaxTab() {
  const [matrix, error, loading] = useLoader(() => getChurchTaxMatrix(), []);
  return (
    <>
      <Card title="Church tax (Kirchensteuer) — 16-Land matrix">
        {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
        <ErrorBanner message={error} />
        {matrix && (
          <>
            <div className="mb-3 flex items-start gap-2 rounded-[10px] border border-border bg-surface-muted px-3 py-2 text-[11px] text-foreground-muted">
              {matrix.sourceStatus}
            </div>
            <div className="grid grid-cols-4 gap-2 mb-4">
              {matrix.laender.map((l) => (
                <div key={l.code} className="rounded-[10px] border border-border p-2.5 text-center">
                  <div className="text-[11px] font-bold text-foreground">{l.code}</div>
                  <div className="text-[13px] font-bold text-primary">{l.ratePct}%</div>
                </div>
              ))}
            </div>
            {matrix.knownGaps.map((gap, i) => (
              <div key={i} className="flex items-start gap-2 rounded-[10px] border border-warning/30 bg-warning/10 px-3 py-2 text-[11px] text-foreground">
                <ShieldAlert size={13} className="mt-0.5 shrink-0 text-warning" /> {gap}
              </div>
            ))}
          </>
        )}
      </Card>
      <ChurchTaxExceptionsTab />
    </>
  );
}

// ── Phase 8AM — Church-tax exceptions (sub-Land denomination/location) ───
// Maker-checker, source-evidence-linked, effective-dated overrides on top
// of the 16-Land matrix above — see models.GermanyChurchTaxException.
// An employee resolves an exception rate ONLY when a matching PUBLISHED
// row exists for their (Land, denomination, postal code) as of the payroll
// date; every other employee keeps the ordinary Land rate.

function ChurchTaxExceptionsTab() {
  return (
    <LifecycleRegistryTab
      title="Church-tax exceptions (sub-Land rate overrides, e.g. Bad Wimpfen RC 9%)"
      list={() => listGermanyChurchTaxExceptions()}
      create={(f) => createGermanyChurchTaxException({
        landCode: f.landCode, denomination: f.denomination, municipalityPostalCode: f.municipalityPostalCode,
        scopeDescription: f.scopeDescription || undefined, exceptionRatePct: f.exceptionRatePct,
        effectiveFrom: f.effectiveFrom, effectiveTo: f.effectiveTo || undefined,
        authoritySourceId: f.authoritySourceId || undefined,
      })}
      approve={approveGermanyChurchTaxException}
      setStatus={setGermanyChurchTaxExceptionStatus}
      columns={[
        { key: "landCode", label: "Land" },
        { key: "denomination", label: "Denomination" },
        { key: "municipalityPostalCode", label: "Postal code" },
        { key: "exceptionRatePct", label: "Exception rate %" },
        { key: "effectiveFrom", label: "Effective from" },
        { key: "effectiveTo", label: "Effective to", render: (r) => r.effectiveTo || "open" },
        { key: "scopeDescription", label: "Scope", render: (r) => (r.scopeDescription ? <span title={r.scopeDescription}>{r.scopeDescription.length > 60 ? `${r.scopeDescription.slice(0, 60)}…` : r.scopeDescription}</span> : "—") },
      ]}
      formFields={[
        { key: "landCode", label: "Land code (e.g. DE-BW)", required: true },
        { key: "denomination", label: "Denomination (e.g. ROMAN_CATHOLIC)", required: true },
        { key: "municipalityPostalCode", label: "Municipality postal code (e.g. 74206)", required: true },
        { key: "exceptionRatePct", label: "Exception rate % (e.g. 9)", type: "number", required: true },
        { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
        { key: "effectiveTo", label: "Effective to (blank = open-ended)", type: "date" },
        { key: "scopeDescription", label: "Legal/administrative scope description", span2: true },
        { key: "authoritySourceId", label: "Source evidence artifact ID" },
      ]}
      defaultForm={{
        landCode: "DE-BW", denomination: "ROMAN_CATHOLIC", municipalityPostalCode: "",
        exceptionRatePct: "", effectiveFrom: "2026-01-01", effectiveTo: "",
        scopeDescription: "", authoritySourceId: "",
      }}
    />
  );
}

// ── ELStAM change-list batches ────────────────────────────────────────────

export function ElstamBatchesTab() {
  const [batches, error, loading, reload] = useLoader(() => listElstamChangeListBatches(), []);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ batchReference: "", receivedAt: "", effectiveDate: "2026-01-01", scopeDescription: "" });
  const [actionError, setActionError] = useState("");

  async function handleCreate(e) {
    e.preventDefault();
    setActionError("");
    try {
      await createElstamChangeListBatch({ ...form, receivedAt: new Date(form.receivedAt || Date.now()).toISOString() });
      setShowForm(false);
      reload();
    } catch (err) {
      setActionError(err.message || "Could not save.");
    }
  }

  async function transition(id, status) {
    setActionError("");
    try {
      await updateElstamChangeListBatchStatus(id, { status });
      reload();
    } catch (err) {
      setActionError(err.message || "Transition failed.");
    }
  }

  return (
    <Card
      title="ELStAM change-list batches (received — never live-polled)"
      action={<button className={btnSecondary} onClick={() => setShowForm((v) => !v)}><Plus size={12} className="inline -mt-0.5 mr-1" /> Record received batch</button>}
    >
      <ErrorBanner message={actionError} />
      <div className="mb-3 flex items-start gap-2 rounded-[10px] border border-border bg-surface-muted px-3 py-2 text-[11px] text-foreground-muted">
        This is an operations/review surface only — it records that a batch was received and its review status.
        Nothing here polls ELSTER/BZSt or auto-applies attribute changes; each employee's actual change is entered
        separately via the employee statutory-profile screen's "Structured ELStAM import" mode.
      </div>
      {showForm && (
        <form onSubmit={handleCreate} className="mb-4 grid grid-cols-2 gap-2 rounded-[10px] border border-border p-3">
          <input className={inputCls} placeholder="Batch reference (e.g. 2026-07)" required value={form.batchReference} onChange={(e) => setForm((f) => ({ ...f, batchReference: e.target.value }))} />
          <input type="date" className={inputCls} required value={form.effectiveDate} onChange={(e) => setForm((f) => ({ ...f, effectiveDate: e.target.value }))} />
          <input type="datetime-local" className={inputCls} placeholder="Received at" value={form.receivedAt} onChange={(e) => setForm((f) => ({ ...f, receivedAt: e.target.value }))} />
          <input className={inputCls} placeholder="Scope (e.g. all active DE employees)" value={form.scopeDescription} onChange={(e) => setForm((f) => ({ ...f, scopeDescription: e.target.value }))} />
          <button type="submit" className={`${btnPrimary} col-span-2`}>Record batch</button>
        </form>
      )}
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      <ErrorBanner message={error} />
      {batches && batches.length === 0 && <p className="text-[12px] text-foreground-muted">No change-list batches recorded yet.</p>}
      {batches && batches.length > 0 && (
        <table className="w-full text-[12px]">
          <thead><tr><Th>Reference</Th><Th>Effective date</Th><Th>Status</Th><Th>Actions</Th></tr></thead>
          <tbody>
            {batches.map((b) => (
              <tr key={b.id} className="border-t border-border">
                <Td>{b.batchReference}</Td>
                <Td>{b.effectiveDate}</Td>
                <Td><StatusPill value={b.processingStatus} /></Td>
                <Td>
                  <div className="flex gap-1.5">
                    {b.processingStatus === "RECEIVED" && <button className={btnSecondary} onClick={() => transition(b.id, "VALIDATED")}>Mark validated</button>}
                    {b.processingStatus === "VALIDATED" && <button className={btnPrimary} onClick={() => transition(b.id, "APPLIED")}>Mark applied</button>}
                    {["RECEIVED", "VALIDATED"].includes(b.processingStatus) && <button className={btnSecondary} onClick={() => transition(b.id, "REJECTED")}>Reject</button>}
                  </div>
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}

// ── Source evidence ───────────────────────────────────────────────────────

const DE_SRC_REFERENCE = [
  ["DE-SRC-001/002", "BMF — Programmablaufplan / machine PAP 2026", "Lohnsteuer2026.xml"],
  ["DE-SRC-003", "BMF — Lohnsteuer-Handbuch 2026 §32a", null],
  ["DE-SRC-004", "BMF — Solidaritätszuschlaggesetz 2026", null],
  ["DE-SRC-005", "BMAS — 2026 social-insurance calculation values", null],
  ["DE-SRC-006", "BMG — GKV contributions 2026", null],
  ["DE-SRC-007", "BMG — Long-term-care financing", "SGB XI §55"],
  ["DE-SRC-008", "Deutsche Rentenversicherung — values 2026", null],
  ["DE-SRC-009", "Deutsche Rentenversicherung — transitional-zone factor 2026", "Faktor F"],
  ["DE-SRC-010", "Minijob-Zentrale — 2026 marginal-employment guidelines", null],
  ["DE-SRC-011", "ELSTER — ELStAM for employers", null],
  ["DE-SRC-012", "Bundesportal — church-tax calculation", null],
  ["DE-SRC-013", "BMAS — statutory minimum wage 2026", null],
  ["DE-SRC-014", "Bundesagentur für Arbeit — 2026 budget/contribution basis", null],
];

export function SourceEvidenceTab() {
  const [artifacts, error, loading, reload] = useLoader(() => getSourceArtifacts(), []);
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({ agency: "", title: "", formNumber: "", sourceUrl: "", publicationDate: "", checksumSha256: "" });
  const [actionError, setActionError] = useState("");

  async function handleCreate(e) {
    e.preventDefault();
    setActionError("");
    try {
      await createSourceArtifact(form);
      setShowForm(false);
      reload();
    } catch (err) {
      setActionError(err.message || "Could not save.");
    }
  }

  async function review(id) {
    setActionError("");
    try {
      await reviewSourceArtifact(id);
      reload();
    } catch (err) {
      setActionError(err.message || "Review failed.");
    }
  }

  const foundFor = (matchHint) =>
    !!matchHint && (artifacts || []).some((a) => (a.title || "").toLowerCase().includes(matchHint.toLowerCase()));

  return (
    <>
      <Card title="DE-SRC-001 … 014 backfill status (spec §24 Source Register)">
        <p className="mb-3 text-[11px] text-foreground-muted">
          A checkmark means a source-artifact row citing that evidence exists below — never inferred from the
          document's own reference table alone. An unchecked row is genuinely <strong>SOURCE_REQUIRED</strong>.
        </p>
        <table className="w-full text-[12px]">
          <thead><tr><Th>ID</Th><Th>Requirement</Th><Th>Status</Th></tr></thead>
          <tbody>
            {DE_SRC_REFERENCE.map(([id, label, hint]) => (
              <tr key={id} className="border-t border-border">
                <Td>{id}</Td>
                <Td>{label}</Td>
                <Td>
                  {foundFor(hint) ? (
                    <span className="inline-flex items-center gap-1 text-primary font-semibold"><Check size={13} /> Evidence recorded</span>
                  ) : (
                    <span className="font-semibold text-warning">SOURCE_REQUIRED</span>
                  )}
                </Td>
              </tr>
            ))}
          </tbody>
        </table>
      </Card>

      <Card
        title="Source evidence artifacts (platform-wide)"
        action={<button className={btnSecondary} onClick={() => setShowForm((v) => !v)}><Plus size={12} className="inline -mt-0.5 mr-1" /> Record new evidence</button>}
      >
        <ErrorBanner message={actionError} />
        {showForm && (
          <form onSubmit={handleCreate} className="mb-4 grid grid-cols-2 gap-2 rounded-[10px] border border-border p-3">
            <input className={inputCls} placeholder="Agency" required value={form.agency} onChange={(e) => setForm((f) => ({ ...f, agency: e.target.value }))} />
            <input className={inputCls} placeholder="Title" required value={form.title} onChange={(e) => setForm((f) => ({ ...f, title: e.target.value }))} />
            <input className={inputCls} placeholder="Form number" value={form.formNumber} onChange={(e) => setForm((f) => ({ ...f, formNumber: e.target.value }))} />
            <input className={inputCls} placeholder="Source URL" value={form.sourceUrl} onChange={(e) => setForm((f) => ({ ...f, sourceUrl: e.target.value }))} />
            <input type="date" className={inputCls} placeholder="Publication date" value={form.publicationDate} onChange={(e) => setForm((f) => ({ ...f, publicationDate: e.target.value }))} />
            <input className={inputCls} placeholder="Checksum SHA-256 (if applicable)" value={form.checksumSha256} onChange={(e) => setForm((f) => ({ ...f, checksumSha256: e.target.value }))} />
            <button type="submit" className={`${btnPrimary} col-span-2`}>Save</button>
          </form>
        )}
        {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
        <ErrorBanner message={error} />
        {artifacts && (
          <table className="w-full text-[12px]">
            <thead><tr><Th>Agency</Th><Th>Title</Th><Th>Reviewed</Th><Th>Actions</Th></tr></thead>
            <tbody>
              {artifacts.map((a) => (
                <tr key={a.id} className="border-t border-border">
                  <Td>{a.agency}</Td>
                  <Td className="max-w-md truncate">{a.title}</Td>
                  <Td>{a.reviewerApprovedAt ? new Date(a.reviewerApprovedAt).toLocaleDateString() : "—"}</Td>
                  <Td>{!a.reviewerApprovedAt && <button className={btnSecondary} onClick={() => review(a.id)}>Mark reviewed</button>}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </>
  );
}

// ── Audit / history ────────────────────────────────────────────────────────

const AUDIT_ENTITY_TYPES = [
  "pap_algorithm_asset", "germany_pap_release", "germany_health_fund", "germany_contribution_ceiling",
  "germany_pv_configuration", "germany_elstam_change_list_batch", "germany_elstam_import_attempt",
  "source_artifact", "employee_statutory_profile",
];

export function AuditTab() {
  const [entityType, setEntityType] = useState("");
  const [rows, error, loading] = useLoader(() => getTaxConfigurationAudit(entityType ? { entityType } : {}), [entityType]);
  return (
    <Card
      title="Audit / history"
      action={
        <select className={inputCls} style={{ width: 260 }} value={entityType} onChange={(e) => setEntityType(e.target.value)}>
          <option value="">All Germany-related entity types</option>
          {AUDIT_ENTITY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
        </select>
      }
    >
      {loading && <p className="text-[12px] text-foreground-muted">Loading…</p>}
      <ErrorBanner message={error} />
      {rows && rows.length === 0 && <p className="text-[12px] text-foreground-muted">No audit events for this filter.</p>}
      {rows && rows.length > 0 && (
        <div className="max-h-[32rem] overflow-y-auto">
          <table className="w-full text-[12px]">
            <thead><tr><Th>When</Th><Th>Actor</Th><Th>Action</Th><Th>Entity</Th><Th>Reason</Th></tr></thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.id} className="border-t border-border">
                  <Td>{r.createdAt ? new Date(r.createdAt).toLocaleString() : "—"}</Td>
                  <Td>{r.actorId ?? "system"}</Td>
                  <Td>{r.action}</Td>
                  <Td>{r.entityType} #{r.entityId}</Td>
                  <Td>{r.reason || "—"}</Td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

// ── Employer Levies / Accident Insurance (Phase 8AJ) ────────────────────
// Unlike every other tab on this page, accident insurance is
// organization-scoped, not global (spec DE-D06/Table 35: accident
// insurance is a carrier/employer-specific statutory fact, not a
// broadly-published national rate). This tab is therefore the one place
// on this page that requires an explicit organization picker before
// showing any data. Reuses the SAME LifecycleRegistryTab component every
// other maker-checker registry on this page uses (health funds, PV,
// ceilings, ...) — full DRAFT -> VERIFIED -> APPROVED -> PUBLISHED
// workflow, not a shortcut save-and-publish. Publishing materializes the
// values into the existing EmployerTaxProfile mechanism the Germany
// engine already reads (jurisdiction "DE", component
// "DE_ACCIDENT_INSURANCE") — a real backend action, never a
// frontend-only status flip. No monthly deduction is ever computed from
// this data anywhere in this platform (German accident insurance is an
// ANNUAL Berufsgenossenschaft assessment, not a per-payslip withholding)
// — this tab is configuration + audit visibility only, never a calculator.

export function EmployerLeviesTab() {
  const [orgs, setOrgs] = useState(null);
  const [orgsError, setOrgsError] = useState("");
  const [selectedOrgId, setSelectedOrgId] = useState("");

  useEffect(() => {
    listOrganizationsForPicker()
      .then(setOrgs)
      .catch((err) => setOrgsError(err.message || "Could not load organizations."));
  }, []);

  return (
    <>
      <Card title="Germany accident insurance (Unfallversicherung) — employer-specific">
        <p className="text-[11px] text-foreground-muted">
          Statutory accident insurance is <strong>carrier/industry/employer specific</strong> (spec DE-D06) — there
          is no national rate to publish. Each profile below is one employer's own Berufsgenossenschaft-assigned
          rate, carried through the same DRAFT → VERIFIED → APPROVED → PUBLISHED maker-checker workflow as every
          other Germany registry on this page. Publishing a profile records it for configuration and
          calculation-trace audit visibility only — German accident insurance is assessed <strong>annually</strong>
          {" "}against reported wage totals, so no monthly payslip deduction is ever computed from it. U1 (sickness
          reimbursement), U2 (maternity levy) and U3 (insolvency levy) each have their own dedicated tab/mechanism
          elsewhere and are not managed here.
        </p>
      </Card>

      <Card title="Select employer">
        <ErrorBanner message={orgsError} />
        {orgs === null && !orgsError && <p className="text-[12px] text-foreground-muted">Loading organizations…</p>}
        {orgs && (
          <select className={inputCls} value={selectedOrgId} onChange={(e) => setSelectedOrgId(e.target.value)}>
            <option value="">Select an organization…</option>
            {orgs.map((o) => (
              <option key={o.id} value={o.id}>{o.organizationName || o.name || `Org #${o.id}`}</option>
            ))}
          </select>
        )}
      </Card>

      {selectedOrgId ? (
        // key={selectedOrgId} forces a clean remount (and therefore a
        // fresh useLoader fetch) whenever the selected employer changes —
        // LifecycleRegistryTab's own list() call has a fixed, empty
        // dependency array, exactly like every other tab that reuses it.
        <LifecycleRegistryTab
          key={selectedOrgId}
          title={`Accident-insurance profiles for this employer (org #${selectedOrgId})`}
          list={() => listGermanyAccidentInsuranceProfiles(selectedOrgId)}
          create={(f) => createGermanyAccidentInsuranceProfile({
            organizationId: Number(selectedOrgId), carrierName: f.carrierName,
            agencyAccountId: f.agencyAccountId || undefined, riskClassDescription: f.riskClassDescription || undefined,
            employerRatePct: f.employerRatePct, effectiveFrom: f.effectiveFrom, effectiveTo: f.effectiveTo || undefined,
            authoritySourceId: f.authoritySourceId || undefined,
          })}
          approve={approveGermanyAccidentInsuranceProfile}
          setStatus={setGermanyAccidentInsuranceProfileStatus}
          columns={[
            { key: "carrierName", label: "Carrier (Berufsgenossenschaft)" },
            { key: "agencyAccountId", label: "Member/account no.", render: (r) => r.agencyAccountId || "—" },
            { key: "riskClassDescription", label: "Risk class", render: (r) => r.riskClassDescription || "—" },
            { key: "employerRatePct", label: "Rate %" },
            { key: "effectiveFrom", label: "Effective from" },
            { key: "effectiveTo", label: "Effective to", render: (r) => r.effectiveTo || "open" },
          ]}
          formFields={[
            { key: "carrierName", label: "Carrier (Berufsgenossenschaft) name", required: true },
            { key: "agencyAccountId", label: "Member/account number (Mitgliedsnummer)" },
            { key: "riskClassDescription", label: "Risk class (Gefahrtarifstelle), if disclosed on the notice" },
            { key: "employerRatePct", label: "Employer rate % (from the annual notice)", type: "number", required: true },
            { key: "effectiveFrom", label: "Effective from", type: "date", required: true },
            { key: "effectiveTo", label: "Effective to (leave blank if open-ended)", type: "date" },
            { key: "authoritySourceId", label: "Source evidence artifact ID (the employer's own Beitragsbescheid)" },
          ]}
          defaultForm={{
            carrierName: "", agencyAccountId: "", riskClassDescription: "", employerRatePct: "",
            effectiveFrom: "2026-01-01", effectiveTo: "", authoritySourceId: "",
          }}
        />
      ) : (
        <p className="text-[12px] text-foreground-muted">Select an employer above to view or configure its accident-insurance profiles.</p>
      )}
    </>
  );
}

// ── Page shell ─────────────────────────────────────────────────────────────

export default function GermanyStatutoryRegistriesPage() {
  const [tab, setTab] = useState("pap");

  return (
    <div className="p-6">
      <div className="mb-5">
        <h1 className="text-[18px] font-bold text-foreground">Germany statutory registries</h1>
        <p className="mt-1 text-[13px] text-foreground-muted">
          Operational management for the Germany 2026 statutory configuration Zoiko's payroll engine reads from —
          PAP, health funds, contribution ceilings, PV configuration, church tax, ELStAM change-list batches and
          source evidence. Every action here calls a real backend operation; nothing is simulated.
        </p>
      </div>

      <div className="mb-5 flex flex-wrap gap-2 border-b border-border pb-3">
        {TABS.map((t) => (
          <button
            key={t.key}
            onClick={() => setTab(t.key)}
            className={`rounded-[10px] px-3 py-1.5 text-[12px] font-semibold transition-colors ${
              tab === t.key ? "bg-primary text-white" : "bg-surface-muted text-foreground-muted hover:text-foreground"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === "pap" && <PapTab />}
      {tab === "health-funds" && <HealthFundsTab />}
      {tab === "ceilings" && <ContributionCeilingsTab />}
      {tab === "pv" && <PvConfigTab />}
      {tab === "earning-taxability" && <EarningTaxabilityTab />}
      {tab === "overtime-premium-categories" && <OvertimePremiumCategoriesTab />}
      {tab === "overtime-grundlohn-caps" && <OvertimeGrundlohnCapsTab />}
      {tab === "employer-levies" && <EmployerLeviesTab />}
      {tab === "church-tax" && <ChurchTaxTab />}
      {tab === "elstam-batches" && <ElstamBatchesTab />}
      {tab === "source-evidence" && <SourceEvidenceTab />}
      {tab === "audit" && <AuditTab />}
    </div>
  );
}
