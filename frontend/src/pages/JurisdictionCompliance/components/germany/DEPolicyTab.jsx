import Collapsible from "../../../../components/jurisdiction/Collapsible";
import Notice from "../../../../components/jurisdiction/Notice";
import { ContributionRatesTable } from "../../../../components/jurisdiction/PackRowTables";
import { useLoad } from "../../../../components/jurisdiction/japan/jpFormat";
import { getGermanyPackContributions } from "../../../../service/superAdminService";
import {
  ChurchTaxTab, EarningTaxabilityTab, OvertimeGrundlohnCapsTab, OvertimePremiumCategoriesTab,
} from "../../GermanyStatutoryRegistriesPage";
import { ENGINE_FILES } from "./deShared";

// Germany Policy tab: how earnings are treated (taxability, overtime premium
// categories, Grundlohn caps) and church tax (the Land matrix built into the
// engine, the registry rate overrides, and the sub-Land exceptions). The
// registry editors are the existing maker-checker tabs, unchanged.

function ChurchTaxOverrides({ pack }) {
  const [view, error] = useLoad(() => getGermanyPackContributions(pack.id));
  if (error) return <p className="text-xs text-error">{error}</p>;
  if (!view) return <p className="text-xs text-foreground-muted">Loading…</p>;
  return (
    <ContributionRatesTable
      rows={view.churchTaxOverrides}
      hideColumns={["state", "filingStatus", "employee", "employer", "flat"]}
      extraColumns={[
        { key: "rate", label: "Rate %", render: (r) => (r.totalRatePct != null ? `${r.totalRatePct}%` : "—") },
        { key: "inForce", label: "In force", render: (r) => `${r.effectiveFrom || "—"} → ${r.effectiveTo || "open"}` },
        { key: "status", label: "Status", render: (r) => r.status || "—" },
      ]}
      emptyText="No church-tax rate override in the parameter registry for this pack; the engine uses its built-in Land rates." />
  );
}

export default function DEPolicyTab({ pack }) {
  return (
    <div className="space-y-3" data-testid="de-policy">
      <p className="text-xs text-foreground-muted">
        Earning treatment and church tax. Registry rows follow their own Draft → Verified → Approved → Published lifecycle.
      </p>
      <Collapsible title="Earning taxability" testId="de-policy-earning" defaultOpen
        summary="Wage-tax and social-insurance treatment per earning type.">
        <EarningTaxabilityTab />
      </Collapsible>
      <Collapsible title="Overtime premium categories" testId="de-policy-overtime"
        summary="Night, Sunday and holiday premium categories (§3b EStG).">
        <OvertimePremiumCategoriesTab />
      </Collapsible>
      <Collapsible title="Overtime Grundlohn caps" testId="de-policy-grundlohn"
        summary="Base-pay caps per dimension (wage tax / social insurance).">
        <OvertimeGrundlohnCapsTab />
      </Collapsible>
      <Collapsible title="Church tax" testId="de-policy-church"
        summary="Land matrix (built into the engine), registry rate overrides and sub-Land exceptions.">
        <div className="space-y-3">
          <Notice tone="info" title="Land rates: built into engine, no data row" testId="de-church-engine">
            The 16-Land base matrix below is read from the engine constant in {ENGINE_FILES.churchTax}.
          </Notice>
          <p className="text-xs font-semibold text-foreground">Rate overrides (parameter registry)</p>
          <ChurchTaxOverrides pack={pack} />
          <ChurchTaxTab />
        </div>
      </Collapsible>
    </div>
  );
}
