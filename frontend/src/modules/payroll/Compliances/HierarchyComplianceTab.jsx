import { useState, useEffect } from "react";
import { Info, MapPin, ShieldCheck, AlertTriangle } from "lucide-react";
import StatusPill from "../../../components/StatusPill";
import { useOrganization } from "../../../context/OrganizationContext";
import {
  getApplicableComplianceConfiguration,
  getOrgJurisdictionAssignments,
  upsertOrgJurisdictionAssignment,
  getCountries,
  getJurisdictionChildren,
} from "../../../service/hierarchyService";

const ACTIVE_ASSIGNMENT_STATUSES = ["configured", "verified", "active"];

function formatAmount(v) {
  if (v === null || v === undefined) return "—";
  return Number(v).toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function RuleBody({ rule }) {
  if (rule.slabs?.length) {
    return (
      <div className="overflow-x-auto">
        <table className="w-full text-[12px]">
          <thead>
            <tr className="text-left text-foreground-muted">
              <th className="py-1 pr-3 font-semibold">Range</th>
              <th className="py-1 pr-3 font-semibold">Rate</th>
              <th className="py-1 font-semibold">Flat fee</th>
            </tr>
          </thead>
          <tbody>
            {rule.slabs.map((s) => (
              <tr key={s.id} className="border-t border-border">
                <td className="py-1 pr-3 text-foreground">
                  {formatAmount(s.min_amount)} – {s.max_amount != null ? formatAmount(s.max_amount) : "∞"}
                </td>
                <td className="py-1 pr-3 text-foreground">{s.rate_pct != null ? `${s.rate_pct}%` : "—"}</td>
                <td className="py-1 text-foreground">{s.flat_fee_amount != null ? formatAmount(s.flat_fee_amount) : "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    );
  }
  if (rule.rates?.length) {
    return (
      <div className="space-y-1">
        {rule.rates.map((r) => (
          <p key={r.id} className="text-[12px] text-foreground">
            Employee: {r.employee_rate_pct != null ? `${r.employee_rate_pct}%` : formatAmount(r.employee_flat_amount)} · Employer:{" "}
            {r.employer_rate_pct != null ? `${r.employer_rate_pct}%` : formatAmount(r.employer_flat_amount)}
          </p>
        ))}
      </div>
    );
  }
  if (rule.formula_expression) {
    return <p className="text-[12px] text-foreground-muted font-mono">{rule.formula_expression}</p>;
  }
  return <p className="text-[12px] text-foreground-muted">No rate data configured.</p>;
}

function TaxCard({ tax }) {
  const isOverridden = tax.configuration_source === "organization_override";
  return (
    <div className="border border-border rounded-[14px] p-4 space-y-3">
      <div className="flex items-start justify-between flex-wrap gap-2">
        <div>
          <p className="text-[13px] font-bold text-foreground">{tax.tax_name}</p>
          <p className="text-[11px] text-foreground-muted">
            {tax.category} · Resolved from {tax.resolved_from?.jurisdiction_name || "—"}
          </p>
        </div>
        <span
          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-1 text-[11px] font-bold ${
            isOverridden ? "bg-warning/10 text-warning" : "bg-info/10 text-info"
          }`}
        >
          {isOverridden ? "Organization Override" : "Platform Managed"}
        </span>
      </div>
      <div className="flex flex-wrap items-center gap-2 text-[11px] text-foreground-muted">
        <StatusPill status={tax.tax_version?.status?.toLowerCase()} label={tax.tax_version?.status} />
        <span>{tax.tax_version?.version_label}</span>
        <span>
          · Effective {tax.tax_version?.effective_from}
          {tax.tax_version?.effective_to ? ` – ${tax.tax_version.effective_to}` : ""}
        </span>
      </div>
      {tax.rules?.map((rule) => (
        <div key={rule.id}>
          {rule.label && <p className="text-[11px] font-semibold text-foreground-muted mb-1">{rule.label}</p>}
          <RuleBody rule={rule} />
        </div>
      ))}
      {tax.parameters?.length > 0 && (
        <div className="grid grid-cols-2 sm:grid-cols-3 gap-2 pt-2 border-t border-border">
          {tax.parameters.map((p) => (
            <div key={p.id} className="text-[11px]">
              <p className="text-foreground-muted">{p.label}</p>
              <p className="font-semibold text-foreground">
                {p.effective_value != null ? formatAmount(p.effective_value) : p.value_text || "—"}
                {p.unit ? ` ${p.unit}` : ""}
                {p.overridden && <span className="ml-1 text-warning">(overridden)</span>}
              </p>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AssignmentSetupCard({ organizationId, onAssigned, addToast }) {
  const [countries, setCountries] = useState([]);
  const [countryId, setCountryId] = useState("");
  const [rootJurisdiction, setRootJurisdiction] = useState(null);
  const [states, setStates] = useState([]);
  const [jurisdictionId, setJurisdictionId] = useState("");
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    getCountries().then(setCountries).catch(() => {});
  }, []);

  useEffect(() => {
    setRootJurisdiction(null);
    setStates([]);
    setJurisdictionId("");
    if (!countryId) return;
    getJurisdictionChildren({ countryId })
      .then((nodes) => {
        const root = nodes?.[0] || null;
        setRootJurisdiction(root);
        if (root) {
          getJurisdictionChildren({ parentId: root.id }).then(setStates).catch(() => {});
        }
      })
      .catch(() => {});
  }, [countryId]);

  const handleSave = async () => {
    const targetId = jurisdictionId || rootJurisdiction?.id;
    if (!targetId) return;
    setSaving(true);
    try {
      await upsertOrgJurisdictionAssignment(organizationId, {
        jurisdiction_id: Number(targetId),
        assignment_type: "primary",
        status: "active",
      });
      addToast?.("Jurisdiction assignment saved.", "success");
      onAssigned();
    } catch (err) {
      addToast?.(err?.message || "Failed to save jurisdiction assignment.", "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="bg-surface border border-border rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)] space-y-4">
      <div className="flex items-center gap-2">
        <MapPin size={16} className="text-primary" />
        <h3 className="text-[15px] font-bold text-foreground">Set Up Jurisdiction Assignment</h3>
      </div>
      <p className="text-[12px] text-foreground-muted max-w-2xl">
        This organization has not been assigned a jurisdiction in the new tax hierarchy engine yet. Select your
        country and, if applicable, state/province — the applicable statutory taxes will resolve automatically.
      </p>
      <div className="flex flex-wrap gap-3">
        <select
          value={countryId}
          onChange={(e) => setCountryId(e.target.value)}
          className="rounded-[10px] border border-border bg-background px-3 py-2 text-[13px] text-foreground"
        >
          <option value="">Select country…</option>
          {countries.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </select>
        {states.length > 0 && (
          <select
            value={jurisdictionId}
            onChange={(e) => setJurisdictionId(e.target.value)}
            className="rounded-[10px] border border-border bg-background px-3 py-2 text-[13px] text-foreground"
          >
            <option value="">National level only</option>
            {states.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        )}
        <button
          onClick={handleSave}
          disabled={!countryId || saving}
          className="rounded-[10px] bg-primary px-4 py-2 text-[12px] font-bold text-white disabled:opacity-40 disabled:cursor-not-allowed hover:bg-primary-hover transition-colors"
        >
          {saving ? "Saving…" : "Save Assignment"}
        </button>
      </div>
    </div>
  );
}

export default function HierarchyComplianceTab({ addToast }) {
  const { organization } = useOrganization();
  const organizationId = organization?.id;
  const [loading, setLoading] = useState(true);
  const [assignments, setAssignments] = useState([]);
  const [config, setConfig] = useState(null);
  const [error, setError] = useState(null);

  const load = () => {
    if (!organizationId) return;
    setLoading(true);
    Promise.all([getOrgJurisdictionAssignments(organizationId), getApplicableComplianceConfiguration(organizationId)])
      .then(([a, c]) => {
        setAssignments(a || []);
        setConfig(c);
        setError(null);
      })
      .catch((err) => setError(err?.message || "Failed to load compliance configuration."))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [organizationId]);

  if (!organizationId) return null;

  if (loading) {
    return (
      <div className="bg-surface border border-border rounded-[18px] p-8 text-center text-[13px] text-foreground-muted">
        Loading jurisdiction hierarchy configuration…
      </div>
    );
  }

  if (error) {
    return (
      <div className="bg-error/5 border border-error/15 rounded-[18px] p-6 text-[13px] text-error">{error}</div>
    );
  }

  const activeAssignments = assignments.filter((a) => ACTIVE_ASSIGNMENT_STATUSES.includes(a.status));

  return (
    <div className="space-y-6">
      <div className="bg-info/5 border border-info/15 rounded-[14px] px-4 py-3 text-[13px] text-foreground-muted flex items-center gap-2">
        <Info size={14} className="text-info shrink-0" />
        <span>
          Preview of the new Jurisdiction Tax Hierarchy engine. The Contribution Rates / Tax Slabs tabs remain the
          source of truth for actual payroll runs until this organization is switched over.
        </span>
      </div>

      {activeAssignments.length === 0 ? (
        <AssignmentSetupCard organizationId={organizationId} onAssigned={load} addToast={addToast} />
      ) : (
        <>
          <div className="bg-surface border border-border rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <h3 className="text-[15px] font-bold text-foreground mb-4">Jurisdiction Assignments</h3>
            <div className="space-y-2">
              {activeAssignments.map((a) => (
                <div
                  key={a.id}
                  className="flex items-center justify-between border border-border rounded-[12px] px-4 py-2.5"
                >
                  <div>
                    <p className="text-[13px] font-semibold text-foreground">{a.jurisdiction_name || `Jurisdiction #${a.jurisdiction_id}`}</p>
                    <p className="text-[11px] text-foreground-muted">
                      {a.assignment_type} · effective from {a.effective_from}
                    </p>
                  </div>
                  <StatusPill status={a.status} />
                </div>
              ))}
            </div>
          </div>

          <div className="bg-surface border border-border rounded-[18px] p-6 shadow-[0_1px_3px_rgba(0,0,0,0.04)]">
            <div className="flex items-center justify-between mb-4 flex-wrap gap-2">
              <h3 className="text-[15px] font-bold text-foreground">Applicable Taxes</h3>
              <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-foreground-muted rounded-full bg-info/10 px-2.5 py-1">
                <ShieldCheck size={12} /> As of {config?.payroll_date}
              </span>
            </div>
            {config?.applicable_taxes?.length ? (
              <div className="space-y-3">
                {config.applicable_taxes.map((t) => (
                  <TaxCard key={t.tax_version?.id || t.tax_code} tax={t} />
                ))}
              </div>
            ) : (
              <div className="text-center py-8">
                <AlertTriangle size={20} className="mx-auto text-warning mb-2" />
                <p className="text-[13px] text-foreground-muted max-w-md mx-auto">
                  No applicable taxes could be resolved for this jurisdiction and date yet. This jurisdiction may not
                  have any active tax versions configured in the new engine — contact your Super Admin.
                </p>
              </div>
            )}
          </div>
        </>
      )}
    </div>
  );
}
