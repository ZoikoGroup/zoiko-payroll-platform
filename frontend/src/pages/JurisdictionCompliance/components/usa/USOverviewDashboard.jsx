import { useEffect, useState, useCallback } from "react";
import { Landmark, MapPin, Percent, Layers, Building2, ArrowRight } from "lucide-react";
import { getCompliancePolicies } from "../../../../service/superAdminService";
import { STATUS_PILL_MAP } from "../../../../components/jurisdiction/constants";
import StatusPill from "../../../../components/StatusPill";
import useConfiguredUSStates from "./useConfiguredUSStates";

// Jurisdiction-wide USA landing page — the one section that isn't scoped
// to a single pack. Every figure here comes from EXISTING endpoints already
// used elsewhere on this page (getCompliancePolicies, getCanonicalContributionRates,
// getCanonicalTaxSlabs, via the shared useConfiguredUSStates hook) — just
// called with a broader `country`-only filter than JurisdictionLayout uses
// (which always scopes to one jurisdictionPackId). list_canonical_
// contribution_rates/list_canonical_tax_slabs already support this
// (backend/app/modules/payroll/service.py) — no new endpoint involved.
//
// Discovering "which states are configured" has no dedicated backend
// endpoint, so it's derived client-side from the real rate/slab rows'
// jurisdictionState field — never a hardcoded 50-state list. Each
// discovered state then gets its own small getCompliancePolicies call to
// read that state's own pack status/version — bounded by how many states
// are ACTUALLY configured (2 today: California, New York), not iterated
// over every US state.
export default function USOverviewDashboard({ onSelectFederal, onSelectState }) {
  const { states, rateCount, slabCount, loading: statesLoading } = useConfiguredUSStates();
  const [federalPacks, setFederalPacks] = useState([]);
  const [statePacks, setStatePacks] = useState([]); // [{ state, packs: [...] }]
  const [loadingPacks, setLoadingPacks] = useState(true);

  const loadPacks = useCallback(async () => {
    setLoadingPacks(true);
    try {
      const federal = await getCompliancePolicies({ country: "US", packType: "tax" });
      setFederalPacks(federal || []);
      const perState = await Promise.all(
        states.map(async (state) => ({
          state,
          packs: await getCompliancePolicies({ country: "US", state, packType: "tax" }).catch(() => []),
        }))
      );
      setStatePacks(perState);
    } finally {
      setLoadingPacks(false);
    }
  }, [states]);

  useEffect(() => { if (!statesLoading) loadPacks(); }, [statesLoading, loadPacks]);

  if (statesLoading || loadingPacks) {
    return <p className="py-12 text-center text-xs text-foreground-disabled">Loading United States compliance overview…</p>;
  }

  const activeFederal = federalPacks.find((p) => p.status === "Active") || federalPacks[0] || null;
  const configuredStateCount = statePacks.length;

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <SummaryCard
          icon={Landmark}
          label="Federal Pack"
          value={activeFederal ? `v${activeFederal.version}` : "Not configured"}
          sub={activeFederal ? <StatusPill status={STATUS_PILL_MAP[activeFederal.status]} label={activeFederal.status} /> : null}
        />
        <SummaryCard
          icon={MapPin}
          label="Configured States"
          value={configuredStateCount > 0 ? String(configuredStateCount) : "Not configured"}
          sub={configuredStateCount > 0 ? statePacks.map((s) => s.state).join(", ") : null}
        />
        <SummaryCard icon={Percent} label="Contribution Components" value={rateCount > 0 ? String(rateCount) : "Not configured"} />
        <SummaryCard icon={Layers} label="Tax Brackets" value={slabCount > 0 ? String(slabCount) : "Not configured"} />
      </div>

      <div className="rounded-xl border border-border bg-surface">
        <div className="border-b border-border-light px-5 py-3">
          <h3 className="text-sm font-bold text-foreground">Jurisdiction Packs</h3>
        </div>
        <div className="divide-y divide-border-light">
          <PackRow
            icon={Landmark}
            title="Federal"
            sub="Country-level — Social Security, Medicare, FUTA, Federal Income Tax"
            pack={activeFederal}
            onClick={onSelectFederal}
          />
          {statePacks.map(({ state, packs }) => {
            const active = packs.find((p) => p.status === "Active") || packs[0] || null;
            return (
              <PackRow
                key={state}
                icon={Building2}
                title={state}
                sub="State income tax"
                pack={active}
                onClick={() => onSelectState(state)}
              />
            );
          })}
          {statePacks.length === 0 && (
            <p className="px-5 py-6 text-center text-xs text-foreground-disabled">No state-level packs configured yet.</p>
          )}
        </div>
      </div>
    </div>
  );
}

function SummaryCard({ icon: Icon, label, value, sub }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="mb-2 flex items-center gap-2 text-foreground-muted">
        <Icon size={15} />
        <span className="text-[11px] font-bold uppercase tracking-wider">{label}</span>
      </div>
      <p className="text-xl font-extrabold text-foreground">{value}</p>
      {sub && <div className="mt-1 text-xs text-foreground-muted">{sub}</div>}
    </div>
  );
}

function PackRow({ icon: Icon, title, sub, pack, onClick }) {
  return (
    <button
      onClick={onClick}
      className="flex w-full items-center justify-between px-5 py-3.5 text-left transition-colors hover:bg-surface-muted"
    >
      <div className="flex items-center gap-3">
        <Icon size={16} className="text-foreground-muted" />
        <div>
          <p className="text-sm font-semibold text-foreground">{title}</p>
          <p className="text-xs text-foreground-muted">{sub}</p>
        </div>
      </div>
      <div className="flex items-center gap-3">
        {pack ? (
          <>
            <span className="text-xs text-foreground-muted">v{pack.version}</span>
            <StatusPill status={STATUS_PILL_MAP[pack.status]} label={pack.status} />
          </>
        ) : (
          <span className="text-xs text-foreground-disabled">Not configured</span>
        )}
        <ArrowRight size={14} className="text-foreground-disabled" />
      </div>
    </button>
  );
}
