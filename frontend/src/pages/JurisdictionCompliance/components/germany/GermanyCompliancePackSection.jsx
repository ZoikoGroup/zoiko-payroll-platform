import { useCallback, useEffect, useState } from "react";
import { Plus, ChevronDown, ChevronRight } from "lucide-react";
import {
  getCompliancePolicies, getCompliancePolicyVersions, setCompliancePolicyStatus, approveCompliancePolicy,
  getCompliancePolicyOrganizations, getCompliancePolicyEligibleOrganizations, assignCompliancePolicy,
  getTaxConfigurationAudit,
} from "../../../../service/superAdminService";
import { describeLoadError } from "../../../../service/errorClassification";
import StatusPill from "../../../../components/StatusPill";
import NewPackModal from "../../../../components/jurisdiction/NewPackModal";
import EditOverviewModal from "../../../../components/jurisdiction/EditOverviewModal";
import AssignOrgsModal from "../../../../components/jurisdiction/AssignOrgsModal";
import OrgsTab from "../../../../components/jurisdiction/OrgsTab";
import { STATUS_PILL_MAP, STATUS_OPTIONS } from "../../../../components/jurisdiction/constants";
import { useToast } from "../../../../context/ToastContext";

// Germany's top-level, versioned COMPLIANCE PACK (Phase 8CH) — e.g.
// "DE-PAYROLL-CY2026-V1" Active, "DE-PAYROLL-CY2027-V1" Draft,
// "DE-PAYROLL-CY2025-V1" historical. This reuses the EXACT SAME generic
// JurisdictionPack framework (model, service functions, routes, schemas,
// audit trail, maker-checker Active-transition gate) that USA/UK already
// use for their own tax packs — nothing new was added on the backend for
// this, since JurisdictionPack/upsert_jurisdiction_pack/
// set_jurisdiction_pack_status/assign_pack_to_organizations/
// record_tax_audit are already fully country-agnostic (confirmed: no
// country allowlist excludes "DE" anywhere in that code path).
//
// IMPORTANT — scope: this pack is a governance/visibility record for
// "the Germany 2026 statutory configuration as a whole" (tax year,
// effective period, regulatory authority, owners, source references,
// change summary, approval lifecycle, version history). It does NOT
// replace or gate Germany's own ~15 statutory registries (health funds,
// ceilings, PV, minijob/midijob, church tax, PAP, overtime, etc.) shown
// in the other tabs on this page — those remain independently
// effective-dated, PUBLISHED-gated, and audited exactly as before,
// per this project's explicit "don't duplicate a working registry"
// architecture rule. The one place a DE JurisdictionPack DOES feed the
// payroll engine directly is the narrow, pre-existing RV/ALV/GKV
// canonical-rate override an organization can opt into (unchanged by
// this section — see test_germany_contribution_rate_effective_dating.py).
export default function GermanyCompliancePackSection() {
  const [state, setState] = useState({ loading: true, packs: null, error: null });
  const [expandedId, setExpandedId] = useState(null);
  const [showNewPack, setShowNewPack] = useState(false);

  const load = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const packs = (await getCompliancePolicies({ country: "DE", packType: "tax" })) || [];
      packs.sort((a, b) => (b.taxYear || "").localeCompare(a.taxYear || "") || (b.effectiveFrom || "").localeCompare(a.effectiveFrom || ""));
      setState({ loading: false, packs, error: null });
    } catch (err) {
      setState({ loading: false, packs: null, error: describeLoadError(err) });
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  function onCreated() {
    setShowNewPack(false);
    load();
  }

  return (
    <div className="space-y-4">
      <div className="rounded-xl border border-border bg-surface p-5">
        <div className="mb-1 flex items-center justify-between gap-3">
          <h3 className="text-sm font-bold text-foreground">Germany Compliance Pack (Tax Year Version)</h3>
          <button
            onClick={() => setShowNewPack(true)}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover"
          >
            <Plus size={13} /> New Tax Pack
          </button>
        </div>
        <p className="text-xs text-foreground-muted">
          The versioned, governed record of Germany's payroll compliance configuration for a given tax year (e.g.
          "DE-PAYROLL-CY2026-V1") — regulatory authority, effective period, source references, change summary, and
          Draft → In Review → QA → Approved → Active lifecycle, using the same framework and maker-checker approval
          gate as the USA/UK compliance packs. Historical and future tax years are preserved as separate, independently
          effective-dated pack versions rather than overwritten.
        </p>
      </div>

      {state.loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading…</p>
      ) : state.error ? (
        <p className="rounded-xl border border-dashed border-warning/40 bg-surface-muted px-4 py-8 text-center text-xs text-warning">
          {state.error.schemaUnavailable ? "Not available — migration pending." : state.error.networkError ? "Backend unreachable." : state.error.message}
        </p>
      ) : state.packs.length === 0 ? (
        <p className="rounded-xl border border-dashed border-border bg-surface-muted py-8 text-center text-xs text-foreground-disabled">
          No Germany compliance pack configured yet — create one with "New Tax Pack" above (e.g. pack ID
          "DE-PAYROLL-CY2026-V1").
        </p>
      ) : (
        <div className="space-y-2">
          {state.packs.map((pack) => (
            <PackRow
              key={pack.id}
              pack={pack}
              expanded={expandedId === pack.id}
              onToggle={() => setExpandedId((id) => (id === pack.id ? null : pack.id))}
              onChanged={load}
            />
          ))}
        </div>
      )}

      {showNewPack && (
        <NewPackModal country="DE" packType="tax" onClose={() => setShowNewPack(false)} onCreated={onCreated} />
      )}
    </div>
  );
}

function PackRow({ pack, expanded, onToggle, onChanged }) {
  const { addToast } = useToast() || {};
  const [showEdit, setShowEdit] = useState(false);

  async function changeStatus(newStatus) {
    try {
      await setCompliancePolicyStatus(pack.id, newStatus);
      addToast?.(`Status updated to ${newStatus}.`, "success");
      onChanged();
    } catch (err) {
      addToast?.(err.message || "Failed to update status.", "error");
    }
  }

  async function handleApprove() {
    try {
      await approveCompliancePolicy(pack.id);
      addToast?.("Pack approved.", "success");
      onChanged();
    } catch (err) {
      addToast?.(err.message || "Failed to approve.", "error");
    }
  }

  return (
    <div className="rounded-xl border border-border bg-surface">
      <button
        onClick={onToggle}
        className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left"
      >
        <div className="flex min-w-0 items-center gap-2">
          {expanded ? <ChevronDown size={14} className="shrink-0 text-foreground-disabled" /> : <ChevronRight size={14} className="shrink-0 text-foreground-disabled" />}
          <span className="truncate text-sm font-semibold text-foreground">{pack.packId}</span>
          <span className="text-xs text-foreground-disabled">v{pack.version}</span>
        </div>
        <div className="flex shrink-0 items-center gap-3 text-xs text-foreground-muted">
          <span>{pack.taxYear || "—"}</span>
          <span>{pack.effectiveFrom || "?"} → {pack.effectiveTo || "open"}</span>
          <StatusPill status={STATUS_PILL_MAP[pack.status] || "pending"} label={pack.status} />
        </div>
      </button>

      {expanded && (
        <div className="space-y-4 border-t border-border-light px-4 py-4">
          <div className="flex flex-wrap items-center gap-2">
            <button onClick={() => setShowEdit(true)} className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground-secondary hover:bg-surface-muted">
              Edit
            </button>
            <button onClick={handleApprove} className="rounded-lg border border-border px-3 py-1.5 text-xs font-medium text-foreground-secondary hover:bg-surface-muted">
              Approve (maker-checker)
            </button>
            <select
              value={pack.status}
              onChange={(e) => changeStatus(e.target.value)}
              className="rounded-lg border border-border-strong bg-background px-2 py-1.5 text-xs text-foreground"
            >
              {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
            </select>
          </div>

          <div className="grid grid-cols-2 gap-x-4 gap-y-2 text-xs sm:grid-cols-3">
            <Field label="Currency" value={pack.currency} />
            <Field label="Regulatory Authority" value={pack.regulatoryAuthority} />
            <Field label="Compliance Category" value={pack.complianceCategory} />
            <Field label="Compliance Owner" value={pack.complianceOwner} />
            <Field label="Engineering Owner" value={pack.engineeringOwner} />
            <Field label="Next Review Date" value={pack.nextReviewDate} />
            <Field label="Source References" value={pack.sourceReferences} span />
            <Field label="Change Summary" value={pack.changeSummary} span />
          </div>

          <VersionsPanel packId={pack.packId} activeId={pack.id} />
          <OrganizationsPanel pack={pack} />
          <AuditPanel packId={pack.id} />
        </div>
      )}

      {showEdit && <EditOverviewModal pack={pack} onClose={() => setShowEdit(false)} onSaved={() => { setShowEdit(false); onChanged(); }} />}
    </div>
  );
}

function Field({ label, value, span }) {
  return (
    <div className={span ? "col-span-full" : undefined}>
      <p className="text-foreground-disabled">{label}</p>
      <p className="font-medium text-foreground">{value || "NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION"}</p>
    </div>
  );
}

function VersionsPanel({ packId, activeId }) {
  const [versions, setVersions] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getCompliancePolicyVersions(packId).then((v) => !cancelled && setVersions(v || [])).catch(() => !cancelled && setVersions([]));
    return () => { cancelled = true; };
  }, [packId]);

  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-foreground">Versions</p>
      {versions === null ? (
        <p className="text-xs text-foreground-disabled">Loading…</p>
      ) : (
        <div className="space-y-1.5">
          {versions.map((v) => (
            <div key={v.id} className={`flex items-center justify-between rounded-lg border px-3 py-1.5 text-xs ${v.id === activeId ? "border-primary bg-primary/5" : "border-border-light"}`}>
              <span className="font-medium text-foreground">v{v.version}</span>
              <span className="flex items-center gap-2 text-foreground-muted">
                {v.effectiveFrom} → {v.effectiveTo || "open"}
                <StatusPill status={STATUS_PILL_MAP[v.status] || "pending"} label={v.status} />
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function OrganizationsPanel({ pack }) {
  const { addToast } = useToast() || {};
  const [orgs, setOrgs] = useState([]);
  const [eligibleOrgs, setEligibleOrgs] = useState([]);
  const [showAssign, setShowAssign] = useState(false);
  const [assignIds, setAssignIds] = useState(new Set());
  const [loading, setLoading] = useState(true);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [assigned, eligible] = await Promise.all([
        getCompliancePolicyOrganizations(pack.id),
        getCompliancePolicyEligibleOrganizations(pack.id),
      ]);
      setOrgs(assigned || []);
      setEligibleOrgs(eligible || []);
    } finally {
      setLoading(false);
    }
  }, [pack.id]);

  useEffect(() => { load(); }, [load]);

  async function handleAssign() {
    try {
      await assignCompliancePolicy(pack.id, Array.from(assignIds));
      addToast?.("Organizations assigned.", "success");
      setShowAssign(false);
      setAssignIds(new Set());
      load();
    } catch (err) {
      addToast?.(err.message || "Failed to assign organizations.", "error");
    }
  }

  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-foreground">Organizations</p>
      {loading ? <p className="text-xs text-foreground-disabled">Loading…</p> : <OrgsTab orgs={orgs} onAssign={() => setShowAssign(true)} />}
      {showAssign && (
        <AssignOrgsModal
          eligibleOrgs={eligibleOrgs}
          assignedIds={new Set(orgs.map((o) => o.id))}
          selected={assignIds}
          setSelected={setAssignIds}
          onClose={() => { setShowAssign(false); setAssignIds(new Set()); }}
          onSave={handleAssign}
        />
      )}
    </div>
  );
}

function AuditPanel({ packId }) {
  const [entries, setEntries] = useState(null);

  useEffect(() => {
    let cancelled = false;
    getTaxConfigurationAudit({ jurisdictionPackId: packId }).then((rows) => !cancelled && setEntries(rows || [])).catch(() => !cancelled && setEntries([]));
    return () => { cancelled = true; };
  }, [packId]);

  return (
    <div>
      <p className="mb-2 text-xs font-semibold text-foreground">Audit / History</p>
      {entries === null ? (
        <p className="text-xs text-foreground-disabled">Loading…</p>
      ) : entries.length === 0 ? (
        <p className="text-xs text-foreground-disabled">No audit entries yet.</p>
      ) : (
        <div className="max-h-64 space-y-1 overflow-y-auto">
          {entries.map((e) => (
            <div key={e.id} className="rounded-lg border border-border-light px-3 py-1.5 text-xs">
              <span className="font-medium text-foreground">{e.action}</span>
              <span className="text-foreground-muted"> — {e.entityType} #{e.entityId}</span>
              {e.reason && <span className="text-foreground-disabled"> ({e.reason})</span>}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
