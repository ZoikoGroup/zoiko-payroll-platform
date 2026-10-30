/**
 * service/billingService.js
 * --------------------------
 * Tenant-facing billing API calls.
 *   GET  /billing/plans           → published plan versions
 *   GET  /billing/my-subscription → current subscription
 *   GET  /billing/trial-status    → banner payload
 *   GET  /billing/plan-change-impact → countries a plan change keeps/pauses/restores
 *   POST /billing/checkout        → create Stripe Checkout Session
 */
import { api } from "./api";

/** Fetch all publicly listed plans with their entitlement flags. */
export const listPublishedPlans = () => api.get("/api/billing/plans");

/** Fetch the calling org's own subscription + entitlements. */
export const getMySubscription = () => api.get("/api/billing/my-subscription");

/** Fetch lightweight trial-banner payload (null when no subscription). */
export const getTrialStatus = () => api.get("/api/billing/trial-status");

/**
 * What switching to planCode would do to the org's countries:
 * { planCode, newLimit (null = unlimited), currentLimit, countries, keep, pause, restore }.
 */
export const getPlanChangeImpact = (planCode) =>
  api.get("/api/billing/plan-change-impact", { params: { plan_code: planCode } });

/**
 * Create a Stripe Checkout Session for plan_code.
 * Returns { checkout_url } — caller should redirect to it — or, for an org
 * already on an active paid subscription, { plan_changed: true, message }:
 * the plan was changed in place (prorated), there is nothing to redirect to.
 * A plan that would pause countries returns 409 (trace.reason
 * "plan_change_pauses_countries") unless acknowledgeCountryPause is true.
 *
 * @param {string} planCode  e.g. "PROFESSIONAL"
 * @param {{acknowledgeCountryPause?: boolean}} [options]
 * @returns {Promise<{checkout_url: string}>}
 */
export const createCheckoutSession = (planCode, { acknowledgeCountryPause = false } = {}) =>
  api.post("/api/billing/checkout", {
    plan_code: planCode,
    acknowledge_country_pause: acknowledgeCountryPause,
  });

/** Fetch the calling org's own invoices, newest first (Step 3). */
export const listMyInvoices = () => api.get("/api/billing/my-subscription/invoices");

/** Fetch a specific invoice's per-employee explanation (Step 3 / Part 7). */
export const getMyInvoiceExplanation = (invoiceId) =>
  api.get(`/api/billing/my-subscription/invoice-explanation/${invoiceId}`);

/** Fetch lightweight dunning-banner payload (null when no dunning row exists). Step 4. */
export const getDunningStatus = () => api.get("/api/billing/dunning-status");

/** Create a Stripe Billing Portal session; returns { portal_url } to redirect to. Step 4. */
export const createBillingPortalSession = () =>
  api.post("/api/billing/my-subscription/billing-portal", {});

/** Schedule cancellation at the end of the current Stripe billing period. */
export const cancelMySubscription = () =>
  api.post("/api/billing/cancel", {});
