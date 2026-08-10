import { createContext, useContext, useState, useEffect, useCallback, useRef } from "react";
import { getActivePolicy, fetchComplianceData } from "../../service/payrollService";
import { getCurrencyForCountry } from "../../utils/currency";

export const PAYROLL_ONBOARDING_MESSAGE = "Complete the Payroll Policy and Compliance setup to unlock the remaining Payroll features.";

// Fetches the org's active policy + compliance details ONCE per module
// session (plus on tab focus, for cross-tab consistency) instead of every
// page/navigation independently re-fetching the same two endpoints —
// previously each sub-module called getCompanyProfile()/fetchComplianceData()/
// getActivePolicy() on its own mount, and the onboarding gate in index.jsx
// re-fetched both on every single navigation between gated pages.
const PayrollSetupContext = createContext(null);

export function PayrollSetupProvider({ children }) {
  const [policy, setPolicy] = useState(null);
  const [compliance, setCompliance] = useState(null);
  const [loading, setLoading] = useState(true);
  const hasLoadedRef = useRef(false);

  const refresh = useCallback(async () => {
    if (!hasLoadedRef.current) setLoading(true);
    const [policyData, complianceData] = await Promise.all([
      getActivePolicy().catch(() => null),
      fetchComplianceData().catch(() => null),
    ]);
    setPolicy(policyData);
    setCompliance(complianceData);
    setLoading(false);
    hasLoadedRef.current = true;
  }, []);

  useEffect(() => {
    refresh();
    // Cross-tab consistency (same pattern used elsewhere in this module for
    // Payroll Runs/Employees) — does NOT re-trigger the "checking" spinner
    // since hasLoadedRef is already true by the time focus can fire.
    window.addEventListener("focus", refresh);
    return () => window.removeEventListener("focus", refresh);
  }, [refresh]);

  const company = compliance?.company || null;
  const jurisdiction = company?.jurisdictionCountry || company?.jurisdiction_country || "";
  const currencyCode = getCurrencyForCountry(jurisdiction)?.code || "USD";
  const calculationMode = policy?.calculationMode || "standard";
  const gateOk = Boolean(policy?.isConfigured) && Boolean(company?.isConfigured);

  const value = { policy, compliance, company, calculationMode, currencyCode, gateOk, loading, refresh };
  return <PayrollSetupContext.Provider value={value}>{children}</PayrollSetupContext.Provider>;
}

export function usePayrollSetup() {
  const ctx = useContext(PayrollSetupContext);
  if (!ctx) throw new Error("usePayrollSetup must be used within a PayrollSetupProvider");
  return ctx;
}
