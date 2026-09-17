import { useCallback, useEffect, useState } from "react";
import { Layers, RefreshCcw, Plus } from "lucide-react";
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

function SectionCard({ title, children }) {
  return (
    <div className="bg-surface border border-border rounded-xl shadow-sm p-5 mb-6">
      <h2 className="text-sm font-semibold text-foreground-secondary mb-3">{title}</h2>
      {children}
    </div>
  );
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
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {plans.map((p) => (
            <div key={p.plan_version_id} className="rounded-lg border border-border-light p-4">
              <div className="flex items-center justify-between mb-1">
                <p className="text-sm font-semibold text-foreground">{p.name}</p>
                <span className="text-xs text-foreground-disabled">v{p.version}</span>
              </div>
              <p className="text-xs text-foreground-muted mb-2">{p.code} · plan_id={p.plan_id} · plan_version_id={p.plan_version_id}</p>
              <p className="text-sm text-foreground-secondary mb-2">${p.monthly_price_usd}/mo</p>
              <ul className="text-xs text-foreground-muted space-y-0.5">
                {Object.entries(p.entitlement_flags || {}).map(([featureKey, limitValue]) => (
                  <li key={featureKey}>{featureKey}{limitValue != null ? `: ${limitValue}` : ""}</li>
                ))}
                {Object.keys(p.entitlement_flags || {}).length === 0 && <li>No entitlement flags.</li>}
              </ul>
            </div>
          ))}
          {plans.length === 0 && !loading && (
            <p className="text-sm text-foreground-disabled col-span-full">No published plans yet.</p>
          )}
        </div>
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
