import { ContributionRatesTable, PackTableHeader } from "./PackRowTables";

// Generic Contribution Rates tab — used by every country's compliance page
// for country-level (or state-level, via jurisdictionState) PF/ESI/PT style
// split employer/employee rates, edited through the generic canonical editor.
// The table itself lives in PackRowTables.jsx so a country with a governed
// editor (Belgium) renders the same table.
export default function RatesTab({ pack, rates, onAdd, onEdit, onDelete }) {
  const isActive = pack?.status === "Active";
  return (
    <div className="space-y-3">
      <PackTableHeader
        description="Canonical contribution rates linked to this pack — org-scoped rows sync from these."
        locked={isActive} lockedNoun="rates" addLabel="Add Rate" onAdd={onAdd}
      />
      <ContributionRatesTable rows={rates} onEdit={onEdit} onDelete={onDelete} />
    </div>
  );
}
