import PolicyLayout from "./shared/PolicyLayout";

// Hong Kong's Policy authoring page — see INPolicyPage.jsx's comment for the
// shared-vs-jurisdiction-specific split this file is part of. Before this
// page existed, "+ New Policy" for Hong Kong fell back to India's page and
// authored the pack as country="IN" (gap-closure D-5).
export default function HKPolicyPage() {
  // Hong Kong is territory-level (no states) and has no HRA concept: the
  // hra_pct split is labelled as a housing allowance (a cash allowance —
  // classified for IRD / MPF in Statutory Configuration → Earning
  // Classification). These are payroll structure defaults, not statutory rules.
  return <PolicyLayout country="HK" countryName="Hong Kong" hasStates={false} allowanceLabel="Housing allowance" />;
}
