import { useCallback, useEffect, useMemo, useState } from "react";
import { Layers, RefreshCcw, Plus, Check } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import {
  listPublishedPlans,
  createBillingPlan,
  createBillingPlanVersion,
  transitionPlanVersionStatus,
  addEntitlementFlag,
  listEntitlementOverrides,
  createEntitlementOverride,
} from "../../service/commandCenterService";

// One section-label scale, reused identically across all Command Center
// pages: uppercase, muted, small — distinct from a page title and from a
// data value, so a screen isn't just "rows of same-weight text."
const SECTION_LABEL_CLS = "text-xs font-semibold uppercase tracking-wider text-foreground-muted mb-3";

function SectionCard({ title, children }) {
  return (
    <div className="bg-surface border border-border rounded-xl shadow-sm p-5 mb-6">
      <h2 className={SECTION_LABEL_CLS}>{title}</h2>
      {children}
    </div>
  );
}

// Same feature_key -> label convention as PlanSelectionPage.jsx's
// self-service plan cards, reused here rather than inventing a second one.
function humanizeFeatureKey(key) {
  return key.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

const inputCls = "rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground";
const btnCls = "flex items-center gap-1.5 rounded-lg bg-primary px-3.5 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50";

export default function PlansEntitlementsPage() {
  const { addToast } = useToast() || {};
  const [plans, setPlans] = useState([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  const [newPlan, setNewPlan] = useState({ code: "", name: "" });
  const [newVersion, setNewVersion] = useState({ planId: "", featureSet: "{}", scaleLimits: "{}" });
  const [statusTransition, setStatusTransition] = useState({ planVersionId: "", status: "APPROVED" });
  const [newFlag, setNewFlag] = useState({ planVersionId: "", featureKey: "", limitValue: "" });

  const [overrideOrgId, setOverrideOrgId] = useState("");
  const [overrides, setOverrides] = useState([]);
  const [newOverride, setNewOverride] = useState({ featureKey: "", limitValue: "", reason: "", expiresAt: "" });

  const featureKeys = useMemo(() => {
    const keys = new Set();
    plans.forEach((p) => Object.keys(p.entitlement_flags || {}).forEach((k) => keys.add(k)));
    return Array.from(keys).sort();
  }, [plans]);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listPublishedPlans();
      setPlans(res || []);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  async function withBusy(fn) {
    setBusy(true);
    try {
      await fn();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  function handleCreatePlan(e) {
    e.preventDefault();
    withBusy(async () => {
      await createBillingPlan(newPlan);
      addToast?.("Plan created.", "success");
      setNewPlan({ code: "", name: "" });
      load();
    });
  }

  function handleCreateVersion(e) {
    e.preventDefault();
    withBusy(async () => {
      const featureSet = JSON.parse(newVersion.featureSet || "{}");
      const scaleLimits = JSON.parse(newVersion.scaleLimits || "{}");
      await createBillingPlanVersion(newVersion.planId, { feature_set: featureSet, scale_limits: scaleLimits });
      addToast?.("Plan version created (DRAFT).", "success");
      load();
    });
  }

  function handleStatusTransition(e) {
    e.preventDefault();
    withBusy(async () => {
      await transitionPlanVersionStatus(statusTransition.planVersionId, statusTransition.status);
      addToast?.("Plan version status updated.", "success");
      load();
    });
  }

  function handleAddFlag(e) {
    e.preventDefault();
    withBusy(async () => {
      await addEntitlementFlag(newFlag.planVersionId, {
        feature_key: newFlag.featureKey,
        limit_value: newFlag.limitValue === "" ? null : Number(newFlag.limitValue),
      });
      addToast?.("Entitlement flag added.", "success");
      setNewFlag({ planVersionId: "", featureKey: "", limitValue: "" });
      load();
    });
  }

  function loadOverrides() {
    withBusy(async () => {
      const res = await listEntitlementOverrides(overrideOrgId);
      setOverrides(res || []);
    });
  }

  function handleCreateOverride(e) {
    e.preventDefault();
    withBusy(async () => {
      await createEntitlementOverride(overrideOrgId, {
        feature_key: newOverride.featureKey,
        limit_value: newOverride.limitValue === "" ? null : Number(newOverride.limitValue),
        reason: newOverride.reason,
        expires_at: new Date(newOverride.expiresAt).toISOString(),
      });
      addToast?.("Entitlement override created.", "success");
      setNewOverride({ featureKey: "", limitValue: "", reason: "", expiresAt: "" });
      loadOverrides();
    });
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <Layers size={22} className="text-primary" /> Plans & Entitlements
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Manage the plan catalog and per-organization entitlement overrides.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <SectionCard title="Published Plans">
        {plans.length === 0 && !loading ? (
          <p className="text-sm text-foreground-disabled">No published plans yet.</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm min-w-[560px]">
              <thead>
                <tr>
                  <th className="w-48 px-3 py-3 text-left align-bottom text-xs font-semibold uppercase tracking-wider text-foreground-muted">
                    Entitlement
                  </th>
                  {plans.map((p) => (
                    <th key={p.plan_version_id} className="border-l border-border-light px-3 py-3 text-left align-bottom">
                      <div className="flex flex-wrap items-center gap-2">
                        <span
                          className="text-sm font-semibold text-foreground"
                          title={`plan_id=${p.plan_id} · plan_version_id=${p.plan_version_id}`}
                        >
                          {p.name}
                        </span>
                        <StatusPill status="active" label="Published" />
                      </div>
                      <p className="mt-1 text-xs text-foreground-muted">{p.code} · v{p.version}</p>
                      <p className="mt-1.5 text-lg font-bold text-foreground">
                        ${p.monthly_price_usd}
                        <span className="text-xs font-normal text-foreground-muted">/mo</span>
                      </p>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {featureKeys.map((key) => (
                  <tr key={key} className="border-t border-border-light">
                    <td className="px-3 py-2.5 text-foreground-secondary">{humanizeFeatureKey(key)}</td>
                    {plans.map((p) => {
                      const flags = p.entitlement_flags || {};
                      const has = Object.prototype.hasOwnProperty.call(flags, key);
                      const val = flags[key];
                      return (
                        <td key={p.plan_version_id} className="border-l border-border-light px-3 py-2.5">
                          {!has ? (
                            <span className="text-foreground-disabled">—</span>
                          ) : val == null ? (
                            <Check size={15} className="text-success" />
                          ) : (
                            <span className="font-medium text-foreground">{val}</span>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                {featureKeys.length === 0 && (
                  <tr className="border-t border-border-light">
                    <td colSpan={plans.length + 1} className="px-3 py-4 text-foreground-disabled">
                      No entitlement flags on any published plan.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        )}
      </SectionCard>

      <SectionCard title="Create Plan">
        <form onSubmit={handleCreatePlan} className="flex flex-wrap items-end gap-2">
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Code</label>
            <input required placeholder="e.g. PROFESSIONAL" value={newPlan.code} onChange={(e) => setNewPlan({ ...newPlan, code: e.target.value })} className={inputCls} />
          </div>
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Name</label>
            <input required placeholder="Display name" value={newPlan.name} onChange={(e) => setNewPlan({ ...newPlan, name: e.target.value })} className={inputCls} />
          </div>
          <button type="submit" disabled={busy} className={btnCls}><Plus size={14} /> Create Plan</button>
        </form>
      </SectionCard>

      <SectionCard title="Create Plan Version (DRAFT)">
        <form onSubmit={handleCreateVersion} className="flex flex-wrap items-end gap-2">
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Plan ID</label>
            <input required type="number" value={newVersion.planId} onChange={(e) => setNewVersion({ ...newVersion, planId: e.target.value })} className={`${inputCls} w-24`} />
          </div>
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Feature Set (JSON)</label>
            <input value={newVersion.featureSet} onChange={(e) => setNewVersion({ ...newVersion, featureSet: e.target.value })} className={`${inputCls} w-64`} />
          </div>
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Scale Limits (JSON)</label>
            <input value={newVersion.scaleLimits} onChange={(e) => setNewVersion({ ...newVersion, scaleLimits: e.target.value })} className={`${inputCls} w-64`} />
          </div>
          <button type="submit" disabled={busy} className={btnCls}><Plus size={14} /> Create Version</button>
        </form>
      </SectionCard>

      <SectionCard title="Approve / Publish a Plan Version">
        <form onSubmit={handleStatusTransition} className="flex flex-wrap items-end gap-2">
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Plan Version ID</label>
            <input required type="number" value={statusTransition.planVersionId} onChange={(e) => setStatusTransition({ ...statusTransition, planVersionId: e.target.value })} className={`${inputCls} w-32`} />
          </div>
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Transition To</label>
            <select value={statusTransition.status} onChange={(e) => setStatusTransition({ ...statusTransition, status: e.target.value })} className={inputCls}>
              <option value="APPROVED">APPROVED (from DRAFT)</option>
              <option value="PUBLISHED">PUBLISHED (from APPROVED)</option>
            </select>
          </div>
          <button type="submit" disabled={busy} className={btnCls}>Transition</button>
        </form>
      </SectionCard>

      <SectionCard title="Add Entitlement Flag to a Plan Version">
        <form onSubmit={handleAddFlag} className="flex flex-wrap items-end gap-2">
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Plan Version ID</label>
            <input required type="number" value={newFlag.planVersionId} onChange={(e) => setNewFlag({ ...newFlag, planVersionId: e.target.value })} className={`${inputCls} w-32`} />
          </div>
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Feature Key</label>
            <input required value={newFlag.featureKey} onChange={(e) => setNewFlag({ ...newFlag, featureKey: e.target.value })} className={inputCls} />
          </div>
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Limit Value (optional)</label>
            <input type="number" value={newFlag.limitValue} onChange={(e) => setNewFlag({ ...newFlag, limitValue: e.target.value })} className={`${inputCls} w-32`} />
          </div>
          <button type="submit" disabled={busy} className={btnCls}><Plus size={14} /> Add Flag</button>
        </form>
      </SectionCard>

      <SectionCard title="Entitlement Overrides (per organization)">
        <div className="flex flex-wrap items-end gap-2 mb-4">
          <div>
            <label className="block text-xs text-foreground-muted mb-1">Organization ID</label>
            <input type="number" value={overrideOrgId} onChange={(e) => setOverrideOrgId(e.target.value)} className={`${inputCls} w-32`} />
          </div>
          <button type="button" disabled={busy || !overrideOrgId} onClick={loadOverrides} className="rounded-lg border border-border px-3.5 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50">
            Load Overrides
          </button>
        </div>

        {overrides.length > 0 && (
          <ul className="mb-4 text-sm text-foreground-secondary space-y-1">
            {overrides.map((o) => (
              <li key={o.id}>
                {o.feature_key}{o.limit_value != null ? `: ${o.limit_value}` : ""} — {o.reason} (expires {new Date(o.expires_at).toLocaleDateString()})
              </li>
            ))}
          </ul>
        )}

        {overrideOrgId && (
          <form onSubmit={handleCreateOverride} className="flex flex-wrap items-end gap-2">
            <div>
              <label className="block text-xs text-foreground-muted mb-1">Feature Key</label>
              <input required value={newOverride.featureKey} onChange={(e) => setNewOverride({ ...newOverride, featureKey: e.target.value })} className={inputCls} />
            </div>
            <div>
              <label className="block text-xs text-foreground-muted mb-1">Limit Value (optional)</label>
              <input type="number" value={newOverride.limitValue} onChange={(e) => setNewOverride({ ...newOverride, limitValue: e.target.value })} className={`${inputCls} w-32`} />
            </div>
            <div>
              <label className="block text-xs text-foreground-muted mb-1">Reason</label>
              <input required value={newOverride.reason} onChange={(e) => setNewOverride({ ...newOverride, reason: e.target.value })} className={inputCls} />
            </div>
            <div>
              <label className="block text-xs text-foreground-muted mb-1">Expires At</label>
              <input required type="date" value={newOverride.expiresAt} onChange={(e) => setNewOverride({ ...newOverride, expiresAt: e.target.value })} className={inputCls} />
            </div>
            <button type="submit" disabled={busy} className={btnCls}><Plus size={14} /> Create Override</button>
          </form>
        )}
      </SectionCard>
    </div>
  );
}
