import { api } from "./api";

export const getOrganizationDetails = () => api.get("/api/organizations/me/detail");
export const updateOrganizationDetails = (data) =>
  api.put("/api/organizations/me", {
    organization_name: data.name,
    industry: data.industry,
    company_type: data.companyType,
    address: data.address,
    city: data.city,
    state: data.state,
    country: data.country,
    currency: data.currency || undefined,
  });
export const uploadOrganizationLogo = (file) => {
  const formData = new FormData();
  formData.append("file", file);
  return api.post("/api/organizations/me/logo", formData);
};
export const getOrganizationDashboardStats = () => api.get("/api/organizations/me/dashboard-stats");
export const getOrganizationActivity = async () => {
  try {
    const res = await api.get("/api/payroll/dashboard/activity", { params: { limit: 8 } });
    return Array.isArray(res) ? res : [];
  } catch {
    return [];
  }
};

// ── Team management (Org Admin only) ────────────────────────────────────────
// Org Admin can invite Payroll Admins into their organization. Employee
// self-service logins were removed from the platform, so "payroll_admin"
// is the only role an Org Admin is ever allowed to create here — the
// backend enforces the same restriction independently (can_create_role).
export const listOrgUsers = (params) => api.get("/api/auth/admin/users", { params });

export const invitePayrollAdmin = ({ email, firstName, lastName, phone }) =>
  api.post("/api/auth/admin/users", {
    email,
    first_name: firstName,
    last_name: lastName,
    phone: phone || undefined,
    role: "payroll_admin",
    send_invite: true,
  });

export const deactivateOrgUser = (userId) => api.delete(`/api/auth/admin/users/${userId}`);

export const resendUserInvite = (userId) => api.post(`/api/auth/admin/users/${userId}/resend-invite`);
