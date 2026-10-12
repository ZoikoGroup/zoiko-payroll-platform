import AUCoefficientBandsPanel from "./AUCoefficientBandsPanel";
import { AU_PAYG_SCALES } from "./auComponentConfig";

// ATO Schedule 1 (NAT 1004) — §5/§6. Scale 4 (no TFN) is listed for
// completeness but never gets coefficient bands (it's a flat rate on
// actual earnings — see engine/countries/australia.py's
// _calculate_au_payg_schedule1 — configured instead via the Special
// Payments tab's Scale 4 rate rows).
export default function AUPaygTab(props) {
  return (
    <AUCoefficientBandsPanel
      {...props}
      ruleType="AU_PAYG_COEFFICIENT"
      familyOptions={AU_PAYG_SCALES}
      familyLabel="Scale"
      title="PAYG Withholding — Schedule 1 (NAT 1004)"
      description="Coefficient bands by Scale — y = a·x − b, where x is the weekly-equivalent earnings figure. Medicare Levy proper is embedded here (Scale 5/6 are the Medicare-exempt scales), never a separate calculation."
    />
  );
}
