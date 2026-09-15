import { useState } from "react";
import { Link } from "react-router-dom";
import { ArrowLeft } from "lucide-react";
import TestCertificationPanel from "../components/jurisdiction/TestCertificationPanel";

// Super Admin > Compliance > Test Certification (§19 gap-closure
// Part 11, 2026-09-09; generalized to Canada, gap-closure Phase 8,
// 2026-09-11) — a jurisdiction picker around the shared
// TestCertificationPanel (extracted gap-closure Plan Phase 4,
// 2026-09-14, so the SAME panel can also be surfaced inside a single
// country's own Compliance workspace, e.g. USACompliancePage).
const JURISDICTIONS = [
  { value: "UK", label: "UK (HMRC)", fixturesPath: "backend/tests/fixtures/hmrc_golden/README.md" },
  { value: "CA", label: "Canada (CRA/Revenu Quebec)", fixturesPath: "backend/tests/fixtures/cra_golden/README.md" },
  { value: "IN", label: "India (CBDT/EPFO/ESIC)", fixturesPath: "backend/tests/fixtures/in_golden/README.md" },
  { value: "US", label: "United States (IRS/SSA/State DOR)", fixturesPath: "backend/tests/fixtures/us_golden/README.md" },
];

export default function TestCertificationPage() {
  const [jurisdiction, setJurisdiction] = useState("UK");
  const activeJurisdiction = JURISDICTIONS.find((j) => j.value === jurisdiction) || JURISDICTIONS[0];

  return (
    <div>
      <Link to="/super-admin/compliance" className="mb-2 flex items-center gap-1 text-xs font-semibold text-foreground-muted hover:text-foreground">
        <ArrowLeft size={14} /> Back to Compliance
      </Link>
      <div className="mb-4 flex items-center justify-end">
        <select
          value={jurisdiction} onChange={(e) => setJurisdiction(e.target.value)}
          className="rounded-lg border border-border bg-surface px-3 py-2 text-sm font-semibold text-foreground"
        >
          {JURISDICTIONS.map((j) => <option key={j.value} value={j.value}>{j.label}</option>)}
        </select>
      </div>
      <TestCertificationPanel
        jurisdiction={activeJurisdiction.value} label={activeJurisdiction.label} fixturesPath={activeJurisdiction.fixturesPath}
      />
    </div>
  );
}
