import { createContext, useContext, useState, useEffect, useCallback, useMemo } from "react";
import { getEntitledCountries } from "../../service/jurisdictionService";

// The org's country entitlement list (which countries it may add employees
// in, capped by plan: Core 1, Professional 3, Business 10, Enterprise
// negotiated). Fetched ONCE per payroll-module session, same pattern as
// PayrollSetupContext, and re-fetched by whoever changes the list (the
// Compliance > Countries panel) via refresh().
const EntitledCountriesContext = createContext(null);

// Employee records (countryFieldSpecs.js COUNTRIES) spell the United Kingdom
// "UK", while the org jurisdiction / ISO lists use "GB" — compare through
// this so an entitlement row in either spelling matches the employee's code.
export function toEmployeeCountryCode(code) {
  const upper = String(code || "").trim().toUpperCase();
  return upper === "GB" ? "UK" : upper;
}

export function EntitledCountriesProvider({ children }) {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const payload = await getEntitledCountries();
      setData(payload);
      setError(null);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, []);

  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { refresh(); }, [refresh]);

  const value = useMemo(() => {
    const countries = data?.countries || [];
    const entitled = countries.filter((c) => c.status === "ACTIVE").map((c) => c.code);
    const entitledEmployeeCodes = entitled.map(toEmployeeCountryCode);
    const primary = countries.find((c) => c.isPrimary)?.code || null;
    return {
      countries,
      entitled,
      primary,
      limit: data ? data.limit ?? null : null,
      used: data?.used ?? 0,
      planCode: data?.planCode ?? null,
      canAdd: Boolean(data?.canAdd),
      addable: data?.addable || [],
      // Every country Zoiko runs payroll for that the org hasn't activated,
      // each {code, name, available, unavailableReason}.
      catalog: data?.catalog || [],
      // How many more countries the plan allows (null = unlimited).
      remaining: data ? data.remaining ?? null : null,
      enforcementMode: data?.enforcementMode || "off",
      // true once a payload has arrived — consumers fall back to their
      // pre-entitlement behaviour (every country) until then or on error.
      loaded: Boolean(data),
      loading,
      error,
      refresh,
      isEntitled: (code) => entitledEmployeeCodes.includes(toEmployeeCountryCode(code)),
      // Primary country in the employee-record spelling ("UK", not "GB").
      primaryEmployeeCode: primary ? toEmployeeCountryCode(primary) : null,
      entitledEmployeeCodes,
    };
  }, [data, loading, error, refresh]);

  return <EntitledCountriesContext.Provider value={value}>{children}</EntitledCountriesContext.Provider>;
}

export function useEntitledCountries() {
  const ctx = useContext(EntitledCountriesContext);
  if (!ctx) throw new Error("useEntitledCountries must be used within an EntitledCountriesProvider");
  return ctx;
}
