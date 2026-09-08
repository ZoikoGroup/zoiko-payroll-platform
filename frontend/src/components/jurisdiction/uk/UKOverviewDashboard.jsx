import { Landmark, Users2, Percent, Layers } from "lucide-react";
import StatusPill from "../../StatusPill";
import { STATUS_PILL_MAP } from "../constants";

// UK-specific compliance overview dashboard — displayed on the Overview
// tab of the JurisdictionLayout. Shows summary cards for the UK
// jurisdiction: active pack, sub-jurisdictions, configured components,
// and PAYE tax bands. Follows the same structure as
// usa/USOverviewDashboard.jsx but simplified for UK's flat jurisdiction
// model (national + sub-jurisdictions, not federal vs state split).
export default function UKOverviewDashboard({ pack, rates, slabs }) {
  const activePack = pack || null;
  const totalRates = (rates || []).length;
  const totalSlabs = (slabs || []).filter((s) => s.ruleType === "MARGINAL_RATE").length;
  const niBandCount = (slabs || []).filter((s) => s.ruleType === "NI_BAND").length;
  const configuredSubs = activePack?.jurisdictionState ? 1 : 0;

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        <SummaryCard
          icon={Landmark}
          label="Active Pack"
          value={activePack ? `v${activePack.version}` : "Not configured"}
          sub={activePack ? (
            <StatusPill status={STATUS_PILL_MAP[activePack.status] || "pending"} label={activePack.status} />
          ) : null}
        />
        <SummaryCard
          icon={Users2}
          label="Sub-Jurisdictions"
          value={configuredSubs > 0 ? `${configuredSubs} configured` : "National only"}
          sub={configuredSubs > 0 ? activePack.jurisdictionState : "England, Scotland, Wales, NI"}
        />
        <SummaryCard
          icon={Percent}
          label="Tax Components"
          value={totalRates > 0 ? String(totalRates) : "Not configured"}
          sub={niBandCount > 0 ? `${niBandCount} NI bands` : null}
        />
        <SummaryCard
          icon={Layers}
          label="PAYE Tax Bands"
          value={totalSlabs > 0 ? String(totalSlabs) : "Not configured"}
        />
      </div>

      {activePack && (
        <div className="rounded-xl border border-border bg-surface px-4 py-3">
          <p className="text-xs text-foreground-muted">
            Pack: <span className="font-semibold text-foreground">{activePack.packId}</span>
            {" · "}v{activePack.version}
            {activePack.taxYear ? ` · FY ${activePack.taxYear}` : ""}
            {activePack.effectiveFrom ? ` · ${activePack.effectiveFrom} → ${activePack.effectiveTo || "open"}` : ""}
          </p>
        </div>
      )}
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
