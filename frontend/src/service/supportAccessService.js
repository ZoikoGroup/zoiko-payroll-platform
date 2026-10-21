// JIT Support Access API (ZP-PRIV Part D).
import { apiFetch } from "../api/client";
import { api } from "./api";

const SA = "/api/super-admin/support-access";
const ORG = "/api/organization-admin/support-access";

// Operator / Platform Security side.
export const supportAccessOperator = {
  config: () => apiFetch(`${SA}/config`),
  searchTenants: (q) => apiFetch(`${SA}/tenants`, { params: { q } }),
  scopeOptions: (organizationId) => apiFetch(`${SA}/tenants/${organizationId}/scope-options`),
  ticketNumber: () => apiFetch(`${SA}/ticket-number`),
  request: (body) => apiFetch(`${SA}/request`, { method: "POST", body }),
  cancel: (id) => apiFetch(`${SA}/${id}/cancel`, { method: "POST" }),
  exit: (id) => apiFetch(`${SA}/${id}/exit`, { method: "POST" }),
  active: () => apiFetch(`${SA}/active`),
  mine: () => apiFetch(`${SA}/mine`),
  credentials: (id) => apiFetch(`${SA}/${id}/credentials`),
  live: () => apiFetch(`${SA}/live`),
  revoke: (id, reason) => apiFetch(`${SA}/${id}/revoke`, { method: "POST", body: { reason } }),
  approvals: () => apiFetch(`${SA}/approvals`),
  zoikoApprove: (id) => apiFetch(`${SA}/${id}/zoiko-approve`, { method: "POST" }),
  breakGlass: (body) => apiFetch(`${SA}/break-glass`, { method: "POST", body }),
  pendingReview: () => apiFetch(`${SA}/pending-review`),
  review: (id, outcome, findings) =>
    apiFetch(`${SA}/${id}/review`, { method: "POST", body: { outcome, findings } }),
};

// Tenant (org admin) side.
export const supportAccessTenant = {
  list: () => api.get(`${ORG}/`),
  approve: (id, body) => api.post(`${ORG}/${id}/approve`, body),
  deny: (id, reason) => api.post(`${ORG}/${id}/deny`, { reason }),
  revoke: (id, reason) => api.post(`${ORG}/${id}/revoke`, { reason }),
  audit: () => api.get(`${ORG}/audit`),
};

export const SCOPE_LABELS = {
  diagnostics: "Diagnostics — organization settings only",
  entity: "One legal entity",
  pay_group: "One pay group",
  employees: "Named employees (up to 10)",
  tenant: "Emergency — all employees, names and contact only",
};

export const FIELD_CLASS_LABELS = {
  identifier: "Identity (name, code, role)",
  contact: "Contact details",
  bank: "Bank details",
  tax: "Tax and statutory identifiers",
  salary: "Salary",
  leave: "Leave and health",
};
