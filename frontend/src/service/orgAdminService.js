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
