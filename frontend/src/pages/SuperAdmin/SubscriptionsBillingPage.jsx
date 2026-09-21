import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { CreditCard, RefreshCcw, ShieldCheck } from "lucide-react";
import StatusPill from "../../components/StatusPill";
import { useToast } from "../../context/ToastContext";
import { listAllSubscriptions } from "../../service/commandCenterService";

const DAY_MS = 86400000;

// Raw BillingSubscription.status values (see billing/models.py
// SubscriptionStatus) plus two derived-only pseudo-statuses: NONE (no
// subscription row at all — a PRODUCTION org created before this
// feature, or any org that never subscribed) and GRACE_READONLY/CLOSED,
// which are trial *stages* computed from current_period_end /
// grace_period_ends_at (trial_lifecycle.resolve_trial_stage) — the raw
// `status` column stays "TRIALING" straight through grace and closure,
// so displaying it as-is would show a closed trial as still active.
const DISPLAY_META = {
  NONE: { pill: "inactive", label: "No Subscription" },
  TRIALING: { pill: "pending", label: "Trialing" },
  ACTIVE: { pill: "active", label: "Active" },
  PAST_DUE: { pill: "on_hold", label: "Past Due" },
  SUSPENDED: { pill: "suspended", label: "Suspended" },
  CANCELLED: { pill: "deactivated", label: "Cancelled" },
  GRACE_READONLY: { pill: "on_hold", label: "Grace (Read-Only)" },
  CLOSED: { pill: "rejected", label: "Trial Closed" },
};

// Commercial Billing & Subscription Operating Standard §A1 — same mapping
// OrganizationsPage.jsx uses for its billing_classification badge.
const BILLING_CLASSIFICATIONS = ["COMMERCIAL_ACTIVE", "NON_CHARGEABLE", "LEGACY", "INTERNAL", "DEMO", "QA"];
const BILLING_CLASSIFICATION_PILL = {
  COMMERCIAL_ACTIVE: "active",
  NON_CHARGEABLE: "inactive",
  LEGACY: "on_hold",
  INTERNAL: "deactivated",
  DEMO: "pending",
  QA: "pending",
};

// §12 — which commercial route governs this org's billing (mirrors
// billing/models.py's BillingAuthority). Distinct from billing_classification
// above: that's WHETHER an org is chargeable, this is WHICH route governs it.
const BILLING_AUTHORITY_LABEL = {
  STANDALONE: "Standalone",
  ZOIKO_ONE_BUNDLE: "Zoiko One Bundle",
  ENTERPRISE_ORDER_FORM: "Order Form",
};
const BILLING_AUTHORITY_PILL = {
  STANDALONE: "approved",
  ZOIKO_ONE_BUNDLE: "approved",
  ENTERPRISE_ORDER_FORM: "active",
};

// Step 4 / blocker #17 — BillingDunningState.stage (billing/models.py's
// DunningStage enum). NONE means no dunning row at all (never PAST_DUE,
// or already recovered and reset back — reset_dunning sets stage=RETRY,
// not NULL, so a fully-recovered org shows RETRY, not NONE, until the row
// itself is examined; NONE specifically means the row never existed).
const DUNNING_STAGES = ["RETRY", "RESTRICT_EXPANSION", "RESTRICT_NEW_RUN", "READ_ONLY"];
const DUNNING_STAGE_LABEL = {
  RETRY: "Retry",
  RESTRICT_EXPANSION: "Restrict Expansion",
  RESTRICT_NEW_RUN: "Restrict New Runs",
  READ_ONLY: "Read-Only",
};
const DUNNING_STAGE_PILL = {
  RETRY: "pending",
  RESTRICT_EXPANSION: "on_hold",
  RESTRICT_NEW_RUN: "on_hold",
  READ_ONLY: "rejected",
};

function formatDate(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}

function displayStatus(row) {
  if (row.status === "NONE") return "NONE";
  if (row.trial_stage === "GRACE_READONLY") return "GRACE_READONLY";
  if (row.trial_stage === "CLOSED") return "CLOSED";
  return row.status;
}

const BAR_COLOR = {
  success: "#16A34A",
  warning: "#D97706",
  error: "#DC2626",
};

// Percent of the current period (or, once in grace, the grace window)
// remaining, plus a human label — same "remaining/total" derivation
// TrialBanner.jsx uses for the trial banner's own progress bar.
function computeRemaining(row) {
  const now = Date.now();

  if (row.status === "NONE") return null;

  if (row.trial_stage === "CLOSED") {
    return { label: "Closed", percent: 0, tone: "error" };
  }

  if (row.trial_stage === "GRACE_READONLY" && row.grace_period_ends_at) {
    const graceEndMs = new Date(row.grace_period_ends_at).getTime();
    const periodEndMs = row.current_period_end ? new Date(row.current_period_end).getTime() : graceEndMs - DAY_MS;
    const totalMs = Math.max(1, graceEndMs - periodEndMs);
    const remainingMs = Math.max(0, graceEndMs - now);
    const days = Math.ceil(remainingMs / DAY_MS);
    return {
      label: `${days}d grace left`,
      percent: Math.min(100, Math.max(0, (remainingMs / totalMs) * 100)),
      tone: "warning",
    };
  }

  if (!row.current_period_end) return null;

  const periodEndMs = new Date(row.current_period_end).getTime();
  const periodStartMs = row.current_period_start ? new Date(row.current_period_start).getTime() : periodEndMs - 30 * DAY_MS;
  const totalMs = Math.max(1, periodEndMs - periodStartMs);
  const remainingMs = Math.max(0, periodEndMs - now);
  const percent = Math.min(100, Math.max(0, (remainingMs / totalMs) * 100));
  const days = Math.ceil(remainingMs / DAY_MS);
  const tone = remainingMs <= 0 ? "error" : percent < 20 ? "warning" : "success";
  return { label: `${Math.max(0, days)}d left`, percent, tone };
}

function RemainingBar({ row }) {
  const remaining = computeRemaining(row);
  if (!remaining) return <span className="text-foreground-disabled">—</span>;
  const color = BAR_COLOR[remaining.tone];
  return (
    <div className="min-w-[120px]">
      <div className="h-1.5 w-full overflow-hidden rounded-full bg-surface-muted">
        <div
          className="h-full rounded-full transition-all"
          style={{ width: `${remaining.percent}%`, backgroundColor: color }}
        />
      </div>
      <span className="mt-1 block text-xs font-medium" style={{ color }}>{remaining.label}</span>
    </div>
  );
}

export default function SubscriptionsBillingPage() {
  const { addToast } = useToast() || {};
  const [searchParams, setSearchParams] = useSearchParams();
  const [rows, setRows] = useState([]);
  const [loading, setLoading] = useState(true);
  const [status, setStatus] = useState(searchParams.get("status") || "");
  const [workspaceType, setWorkspaceType] = useState(searchParams.get("workspace_type") || "");
  const [billingClassification, setBillingClassification] = useState(searchParams.get("billing_classification") || "");
  const [chargeEnabled, setChargeEnabled] = useState(searchParams.get("charge_enabled") || "");
  const [dunningStage, setDunningStage] = useState(searchParams.get("dunning_stage") || "");

  const setStatusAndUrl = (value) => {
    setStatus(value);
    const next = new URLSearchParams(searchParams);
    if (value) next.set("status", value); else next.delete("status");
    setSearchParams(next, { replace: true });
  };

  const setWorkspaceTypeAndUrl = (value) => {
    setWorkspaceType(value);
    const next = new URLSearchParams(searchParams);
    if (value) next.set("workspace_type", value); else next.delete("workspace_type");
    setSearchParams(next, { replace: true });
  };

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const res = await listAllSubscriptions({
        status: status || undefined,
        workspace_type: workspaceType || undefined,
        billing_classification: billingClassification || undefined,
        charge_enabled: chargeEnabled || undefined,
        dunning_stage: dunningStage || undefined,
      });
      setRows(res.subscriptions || []);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setLoading(false);
    }
  }, [status, workspaceType, billingClassification, chargeEnabled, dunningStage]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => { load(); }, [load]);

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <div>
          <h1 className="text-2xl font-bold text-foreground flex items-center gap-2">
            <CreditCard size={22} className="text-primary" /> Subscriptions & Billing
          </h1>
          <p className="text-sm text-foreground-muted mt-0.5">Every organization, whether or not it has a subscription yet — and their billing status.</p>
        </div>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-slate-100 dark:hover:bg-white/5 disabled:opacity-50"
        >
          <RefreshCcw size={15} className={loading ? "animate-spin" : ""} /> Refresh
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2 mb-4">
        <select value={status} onChange={(e) => setStatusAndUrl(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Statuses</option>
          <option value="NONE">No Subscription</option>
          <option value="TRIALING">Trialing</option>
          <option value="ACTIVE">Active</option>
          <option value="PAST_DUE">Past Due</option>
          <option value="SUSPENDED">Suspended</option>
          <option value="CANCELLED">Cancelled</option>
        </select>
        <select value={workspaceType} onChange={(e) => setWorkspaceTypeAndUrl(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Workspace Types</option>
          <option value="PRODUCTION">Production</option>
          <option value="EVALUATION">Evaluation</option>
        </select>
        <select value={billingClassification} onChange={(e) => setBillingClassification(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Billing Classifications</option>
          {BILLING_CLASSIFICATIONS.map((c) => <option key={c} value={c}>{c}</option>)}
        </select>
        <select value={chargeEnabled} onChange={(e) => setChargeEnabled(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">Charge Enabled: Any</option>
          <option value="true">Charge Enabled: Yes</option>
          <option value="false">Charge Enabled: No</option>
        </select>
        <select value={dunningStage} onChange={(e) => setDunningStage(e.target.value)} className="rounded-lg border border-border bg-surface py-2 px-3 text-sm text-foreground">
          <option value="">All Dunning Stages</option>
          <option value="NONE">No Dunning Row</option>
          {DUNNING_STAGES.map((s) => <option key={s} value={s}>{DUNNING_STAGE_LABEL[s]}</option>)}
        </select>
      </div>

      <div className="bg-surface rounded-xl shadow-sm border border-border overflow-hidden overflow-x-auto">
        <table className="w-full text-sm min-w-[1250px]">
          <thead className="bg-background text-left text-xs text-foreground-muted">
            <tr>
              <th className="px-4 py-3">Organization</th>
              <th className="px-4 py-3">Workspace</th>
              <th className="px-4 py-3">Billing Classification</th>
              <th className="px-4 py-3">Charge Enabled</th>
              <th className="px-4 py-3">Commercial Route</th>
              <th className="px-4 py-3">Plan</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Dunning</th>
              <th className="px-4 py-3">Period Start</th>
              <th className="px-4 py-3">Period End</th>
              <th className="px-4 py-3">Grace Ends</th>
              <th className="px-4 py-3">Remaining</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => {
              const ds = displayStatus(row);
              const meta = DISPLAY_META[ds] || { pill: "inactive", label: ds };
              return (
                <tr key={row.organization_id} className="border-t border-border-light">
                  <td className="px-4 py-3 font-medium text-foreground">{row.organization_name}</td>
                  <td className="px-4 py-3 text-foreground-muted">{row.workspace_type}</td>
                  <td className="px-4 py-3">
                    <StatusPill
                      status={BILLING_CLASSIFICATION_PILL[row.billing_classification] || "inactive"}
                      label={row.billing_classification || "NON_CHARGEABLE"}
                    />
                  </td>
                  <td className="px-4 py-3 text-foreground-muted">{row.charge_enabled ? "Yes" : "No"}</td>
                  <td className="px-4 py-3">
                    {row.billing_authority ? (
                      <StatusPill
                        status={BILLING_AUTHORITY_PILL[row.billing_authority] || "inactive"}
                        label={BILLING_AUTHORITY_LABEL[row.billing_authority] || row.billing_authority}
                      />
                    ) : (
                      <span className="text-foreground-disabled">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-foreground-secondary">{row.plan_name || row.plan_code || "—"}</td>
                  <td className="px-4 py-3"><StatusPill status={meta.pill} label={meta.label} /></td>
                  <td className="px-4 py-3">
                    {row.dunning_stage ? (
                      <div className="flex flex-col gap-1">
                        <StatusPill status={DUNNING_STAGE_PILL[row.dunning_stage] || "inactive"} label={DUNNING_STAGE_LABEL[row.dunning_stage] || row.dunning_stage} />
                        {row.dunning_in_flight_run_guard && (
                          <span
                            className="inline-flex items-center gap-1 text-xs font-semibold"
                            style={{ color: "#166534" }}
                            title="An authorized payroll run is currently in flight for this org — dunning is frozen at this stage and that run will complete normally."
                          >
                            <ShieldCheck size={12} className="shrink-0" />
                            Payment overdue, but protected — an authorized run is in flight
                          </span>
                        )}
                      </div>
                    ) : (
                      <span className="text-foreground-disabled">—</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-foreground-muted">{formatDate(row.current_period_start)}</td>
                  <td className="px-4 py-3 text-foreground-muted">{formatDate(row.current_period_end)}</td>
                  <td className="px-4 py-3 text-foreground-muted">{formatDate(row.grace_period_ends_at)}</td>
                  <td className="px-4 py-3"><RemainingBar row={row} /></td>
                </tr>
              );
            })}
          </tbody>
        </table>
        {!loading && rows.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <CreditCard size={28} className="text-border-strong" />
            <p className="text-sm text-foreground-disabled">No organizations match these filters.</p>
          </div>
        )}
      </div>
    </div>
  );
}
