import { PackTableHeader, TaxSlabsTable } from "./PackRowTables";

// Generic percentage-bracket Tax Slabs tab — the default for every country
// (US state income tax, UK's Scotland bands, country-level income tax
// everywhere). India's state-level Professional Tax overrides this via
// JurisdictionLayout's `slabsTabOverride` prop instead of changing this
// component. The table itself lives in PackRowTables.jsx so a country with a
// governed editor (Belgium) renders the same table.
export default function SlabsTab({ pack, slabs, onAdd, onEdit, onDelete }) {
  const isActive = pack?.status === "Active";
  return (
    <div className="space-y-3">
      <PackTableHeader
        description="Canonical tax brackets linked to this pack."
        locked={isActive} lockedNoun="brackets" addLabel="Add Bracket" onAdd={onAdd}
      />
      <TaxSlabsTable rows={slabs} onEdit={onEdit} onDelete={onDelete} actionsDisabled={isActive} />
    </div>
  );
}
