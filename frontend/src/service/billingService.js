/**
 * service/billingService.js
 * --------------------------
 * Tenant-facing billing API calls.
 *   GET  /billing/plans           → published plan versions
 *   GET  /billing/my-subscription → current subscription
 *   GET  /billing/trial-status    → banner payload
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
 * Create a Stripe Checkout Session for plan_code.
 * Returns { checkout_url } — caller should redirect to it.
 *
 * @param {string} planCode  e.g. "PROFESSIONAL"
 * @returns {Promise<{checkout_url: string}>}
 */
export const createCheckoutSession = (planCode) =>
  api.post("/api/billing/checkout", { plan_code: planCode });
