import AUCoefficientBandsPanel from "./AUCoefficientBandsPanel";
import { AU_STSL_FAMILIES } from "./auComponentConfig";

// ATO Schedule 8 (NAT 3539) — §8. Independently calculated and
// independently traced from ordinary PAYG (§8 STSL CONTRACT), sharing
// the SAME au_tax_free_threshold_claimed/au_residency_status employee
// declarations Schedule 1 itself uses — not a separate STSL-only
// declaration (see engine/countries/australia.py's
// _resolve_au_stsl_family).
export default function AUStslTab(props) {
  return (
    <AUCoefficientBandsPanel
      {...props}
      ruleType="AU_STSL_COEFFICIENT"
      familyOptions={AU_STSL_FAMILIES}
      familyLabel="Declaration"
      title="Study and Training Support Loans — Schedule 8 (NAT 3539)"
      description="Coefficient bands by declaration state — same y = a·x − b formula as Schedule 1, calculated and added as its own payslip line, never folded into ordinary PAYG."
    />
  );
}
