// Security & privacy plane API (ZP-PRIV D06, E01-E05, F02/F03).
// Metadata only. Step-up (403 STEP_UP_REQUIRED) is retried centrally by both
// API clients via utils/stepUp.js + StepUpAuthModal - nothing to do here.
import { apiFetch } from "../api/client";
import { api } from "./api";

const SA = "/api/super-admin";
const ORG = "/api/organization-admin";

// Platform plane: super_admin + platform_security read; mutations noted.
export const securityPlatform = {
  events: (params) => apiFetch(`${SA}/security-events`, { params }),
  verifyChain: () => apiFetch(`${SA}/security-events/verify`),
  alertRules: () => apiFetch(`${SA}/alert-rules`),
  alertEvents: (status) => apiFetch(`${SA}/alert-events`, { params: { status } }),
  acknowledgeAlert: (id) => apiFetch(`${SA}/alert-events/${id}/acknowledge`, { method: "POST" }),
  // platform_security only (drill).
  testFire: (key) => apiFetch(`${SA}/alert-rules/${encodeURIComponent(key)}/test-fire`, { method: "POST" }),
  privilegedInventory: () => apiFetch(`${SA}/privileged-inventory`),
  machineClients: () => apiFetch(`${SA}/machine-clients`),
};

// Privacy Assurance (control register + independent review).
export const privacyAssurance = {
  controls: () => apiFetch(`${SA}/privacy-assurance/controls`),
  // platform_security + recent MFA.
  recordReview: (controlId, decision, proofReference) =>
    apiFetch(`${SA}/privacy-assurance/controls/${encodeURIComponent(controlId)}/reviews`, {
      method: "POST",
      body: { decision, proofReference },
    }),
};

// Tenant plane: organization admins, own organization only.
export const securityTenant = {
  events: (params) => api.get(`${ORG}/security-events`, { params }),
  apiScopes: () => api.get(`${ORG}/api-clients/scopes`),
  apiClients: () => api.get(`${ORG}/api-clients`),
  // The returned `credential` is shown once and must never be stored.
  createApiClient: (body) => api.post(`${ORG}/api-clients`, body),
  rotateApiClient: (id) => api.post(`${ORG}/api-clients/${id}/rotate`),
  revokeApiClient: (id) => api.post(`${ORG}/api-clients/${id}/revoke`),
  webhooks: () => api.get(`${ORG}/webhooks`),
  // The returned `signingSecret` is shown once and must never be stored.
  createWebhook: (body) => api.post(`${ORG}/webhooks`, body),
  disableWebhook: (id) => api.post(`${ORG}/webhooks/${id}/disable`),
  dataGovernance: () => api.get(`${ORG}/data-governance`),
  placeHold: (body) => api.post(`${ORG}/legal-holds`, body),
  releaseHold: (id, reason) => api.post(`${ORG}/legal-holds/${id}/release`, { reason }),
  createRequest: (body) => api.post(`${ORG}/data-access-requests`, body),
  completeRequest: (id, outcome) => api.post(`${ORG}/data-access-requests/${id}/complete`, { outcome }),
};

export const API_CLIENT_MAX_DAYS = 365; // machine_clients.MAX_LIFETIME_DAYS
export const WEBHOOK_EVENTS = ["employee.created", "employee.updated", "payroll_run.approved", "payroll_run.paid"];
export const DSAR_TYPES = ["access", "erasure", "rectification"];

// Fail closed: 403/404 become a neutral "not available" state, never raw errors.
export function isUnavailable(err) {
  return err?.status === 403 || err?.status === 404;
}
