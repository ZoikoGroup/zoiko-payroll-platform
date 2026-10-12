import HKStatutoryConfigurationTab from "../../components/jurisdiction/hong_kong/HKStatutoryConfigurationTab";

// Hong Kong statutory rates are administered in the governed HK workspace
// (domains, statutory units, source + reason on every edit, Draft versions
// only) rather than the shared StatutoryRatesLayout, which shows fractions as
// percentages and edits without a source document.
export default function HKStatutoryPage() {
  return (
    <div className="p-6">
      <h1 className="mb-4 text-[18px] font-semibold text-foreground">Hong Kong — Statutory Configuration</h1>
      <HKStatutoryConfigurationTab />
    </div>
  );
}
