/**
 * service/jurisdictionService.js
 * -------------------------------
 * Tenant-facing country entitlement API calls. Every call returns the same
 * payload: { countries, limit, used, planCode, canAdd, addable, enforcementMode }.
 *   GET    /payroll/jurisdictions/entitled                  → entitled countries + plan cap
 *   POST   /payroll/jurisdictions/entitled                  → add a country
 *   POST   /payroll/jurisdictions/entitled/{code}/primary   → make a country primary
 *   DELETE /payroll/jurisdictions/entitled/{code}           → remove a country (409 if in use / primary)
 *   POST   /payroll/jurisdictions/entitled/replace-primary  → swap the only country (one-country plans)
 */
import { api } from "./api";

/** Fetch the calling org's entitled countries and its plan's country cap. */
export const getEntitledCountries = () => api.get("/api/payroll/jurisdictions/entitled");

/** Add a country to the org's entitlement list (403 when the plan cap is reached). */
export const addEntitledCountry = (countryCode) =>
  api.post("/api/payroll/jurisdictions/entitled", { countryCode });

/** Make an already-entitled country the org's primary country. */
export const setPrimaryCountry = (countryCode) =>
  api.post(`/api/payroll/jurisdictions/entitled/${encodeURIComponent(countryCode)}/primary`, {});

/** Remove a non-primary country; 409 with a human message while employees still use it. */
export const removeEntitledCountry = (countryCode) =>
  api.delete(`/api/payroll/jurisdictions/entitled/${encodeURIComponent(countryCode)}`);

/**
 * Replace the primary country on a one-country plan.
 * 409 with a message + count while employees remain in the old country.
 *
 * @param {string} countryCode  e.g. "US"
 */
export const replacePrimaryCountry = (countryCode) =>
  api.post("/api/payroll/jurisdictions/entitled/replace-primary", { countryCode });
