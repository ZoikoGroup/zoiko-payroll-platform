// Employee email / phone rules for the UI. Mirrors
// backend/app/modules/payroll/contact_validation.py (same messages); the
// server stays the authority — it also converts phone numbers to the
// international E.164 form using libphonenumber's per-country rules, which
// this lightweight check does not try to repeat.

export const EMAIL_INVALID = "Enter a valid email address, for example name@company.com.";
export const PHONE_BAD_CHARACTERS = "Phone number may contain only digits, spaces, ( ) - . and a leading +.";
export const PHONE_INVALID = "Enter a valid phone number, for example +44 7700 900123.";

const EMAIL_LOCAL = /^[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+(\.[A-Za-z0-9!#$%&'*+/=?^_`{|}~-]+)*$/;
const EMAIL_DOMAIN_LABEL = /^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$/;
const EMAIL_TLD = /^[A-Za-z]{2,63}$/;
const PHONE_ALLOWED = /^\+?[0-9\s().-]+$/;

export function normalizeEmail(value) {
  return String(value ?? "").trim().toLowerCase();
}

/** Error message for an email, or null when it is valid (a blank value is valid — required-ness is checked by the form). */
export function emailError(value) {
  const text = normalizeEmail(value);
  if (!text) return null;
  if (text.length > 254 || (text.match(/@/g) || []).length !== 1 || /\s/.test(text)) return EMAIL_INVALID;
  const [local, domain] = text.split("@");
  if (!local || local.length > 64 || !EMAIL_LOCAL.test(local)) return EMAIL_INVALID;
  const labels = domain.split(".");
  if (labels.length < 2 || !labels.every((label) => EMAIL_DOMAIN_LABEL.test(label))) return EMAIL_INVALID;
  if (!EMAIL_TLD.test(labels[labels.length - 1])) return EMAIL_INVALID;
  return null;
}

/**
 * Error message for a phone number, or null when it looks valid (a blank value is valid).
 * Structure only: allowed characters, and 8-15 digits for an international number
 * (+ or 00 prefix) or 4-15 digits for a national one (read as the employee's country
 * by the server, which applies that country's exact length rules).
 */
export function phoneError(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  if (!PHONE_ALLOWED.test(text)) return PHONE_BAD_CHARACTERS;
  const international = text.startsWith("+") || text.startsWith("00");
  let digits = text.replace(/\D/g, "");
  if (text.startsWith("00")) digits = digits.slice(2);
  if (international ? digits.length < 8 || digits.length > 15 : digits.length < 4 || digits.length > 15) {
    return PHONE_INVALID;
  }
  return null;
}

/** True when `value` is unchanged from what is already stored (legacy values are not re-checked). */
export function isUnchangedContact(stored, value) {
  return String(stored ?? "").trim().toLowerCase() === String(value ?? "").trim().toLowerCase();
}
