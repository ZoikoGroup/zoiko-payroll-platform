// Tenant scoping administration (ZP-PRIV C.3): legal entities, pay groups,
// payroll-admin scope and worker placement. Org admins only.
import { api } from "./api";

export const scopeService = {
  listEntities: () => api.get("/api/organizations/me/legal-entities"),
  createEntity: (body) => api.post("/api/organizations/me/legal-entities", body),
  listPayGroups: () => api.get("/api/organization-admin/pay-groups"),
  createPayGroup: (body) => api.post("/api/organization-admin/pay-groups", body),
  updatePayGroup: (id, body) => api.put(`/api/organization-admin/pay-groups/${id}`, body),
  getUserScope: (userId) => api.get(`/api/organization-admin/users/${userId}/scope`),
  setUserScope: (userId, body) => api.put(`/api/organization-admin/users/${userId}/scope`, body),
  setPlacement: (employeeId, body) => api.put(`/api/organization-admin/employees/${employeeId}/placement`, body),
};
