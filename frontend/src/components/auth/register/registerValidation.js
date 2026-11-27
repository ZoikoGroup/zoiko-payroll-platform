import { getTimezonesForCountryName } from "../../../utils/registrationRegions";
import { validateJurisdictionTaxIds } from "../../../utils/jurisdictionTax";

// Per-step validation for the registration wizard. Returns {field: message}
// for the step's own fields only, so "Continue" never complains about a step
// the admin hasn't reached. The rules match what the old single-page form
// enforced through native `required` attributes, plus the API's password rule.

// Mirrors the API's registration rule (backend auth/schemas.py).
export const PASSWORD_CHECKS = [
  ["At least 12 characters", (p) => p.length >= 12],
  ["A letter", (p) => /[A-Za-z]/.test(p)],
  ["A number", (p) => /[0-9]/.test(p)],
  ["A symbol", (p) => /[^A-Za-z0-9]/.test(p)],
];
export const passwordOk = (p) => PASSWORD_CHECKS.every(([, test]) => test(p));

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

export function isEmail(value) {
  return EMAIL_RE.test(String(value || "").trim());
}

/** Field order per step: the first failing field in this order gets focus. */
export const STEP_FIELDS = {
  1: ["orgName", "companyType", "industry", "country", "state", "city", "address", "taxNo"],
  2: ["firstName", "lastName", "adminEmail", "phone", "password", "timezone", "termsAccepted"],
};

export function validateOrganization(form) {
  const errors = {};
  if (!form.orgName.trim()) errors.orgName = "Enter your organization's name.";
  if (!form.companyType) errors.companyType = "Select a company type.";
  if (!form.industry) errors.industry = "Select an industry.";
  if (!form.country) errors.country = "Select the country you run payroll in.";
  if (!form.address.trim()) errors.address = "Enter your organization's address.";
  for (const err of validateJurisdictionTaxIds(form.country, form.taxIdentifiers)) {
    errors[`tax:${err.key}`] = err.message;
  }
  return errors;
}

export function validateAdministrator(form, { passwordless = false, emailEditable = true } = {}) {
  const errors = {};
  if (!form.firstName.trim()) errors.firstName = "Enter your first name.";
  if (!form.lastName.trim()) errors.lastName = "Enter your last name.";
  if (emailEditable) {
    if (!form.adminEmail.trim()) errors.adminEmail = "Enter your work email.";
    else if (!isEmail(form.adminEmail)) errors.adminEmail = "Enter a valid email address, like name@company.com.";
  }
  const digits = form.phoneNumber.replace(/\D/g, "");
  if (!digits) errors.phone = "Enter a phone number.";
  else if (digits.length < 4 || digits.length > 15) errors.phone = "Enter a valid phone number.";
  if (!passwordless) {
    if (!form.password) errors.password = "Create a password.";
    else if (!passwordOk(form.password)) {
      errors.password = "Use at least 12 characters with a letter, a number and a symbol.";
    }
  }
  if (getTimezonesForCountryName(form.country).length > 0 && !form.timezone) {
    errors.timezone = "Select a timezone.";
  }
  if (!form.termsAccepted) errors.termsAccepted = "Accept the Terms of Service and Privacy Policy to continue.";
  return errors;
}

/** Errors for one step; steps 3 (review) and 4 (plan) have no fields of their own. */
export function validateStep(step, form, options) {
  if (step === 1) return validateOrganization(form);
  if (step === 2) return validateAdministrator(form, options);
  return {};
}

/** The first step (1..2) that still has errors, or null when both are complete. */
export function firstIncompleteStep(form, options) {
  if (Object.keys(validateOrganization(form)).length) return 1;
  if (Object.keys(validateAdministrator(form, options)).length) return 2;
  return null;
}
