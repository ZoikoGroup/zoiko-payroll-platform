import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { useAuth } from "./AuthContext";
import { getOrganizationDetails } from "../service/orgAdminService";
import { ROLES } from "../config/roles";

const OrganizationContext = createContext(null);

// Only org_admin / payroll_admin sessions have an organization to show in the
// app shell — skip the fetch entirely for super_admin/employee so we never
// make a call the current page has no use for.
const ORG_SCOPED_ROLES = [ROLES.ORG_ADMIN, ROLES.PAYROLL_ADMIN];

export function OrganizationProvider({ children }) {
  const { role, isAuthenticated } = useAuth();
  const [organization, setOrganization] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);

  const refresh = useCallback(async () => {
    if (!isAuthenticated || !ORG_SCOPED_ROLES.includes(role)) {
      setOrganization(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const data = await getOrganizationDetails();
      setOrganization(data);
    } catch (err) {
      setError(err);
    } finally {
      setLoading(false);
    }
  }, [isAuthenticated, role]);

  useEffect(() => {
    refresh();
  }, [refresh]);

  const value = { organization, loading, error, refresh };

  return <OrganizationContext.Provider value={value}>{children}</OrganizationContext.Provider>;
}

export function useOrganization() {
  const ctx = useContext(OrganizationContext);
  if (!ctx) throw new Error("useOrganization must be used within an OrganizationProvider");
  return ctx;
}
