// Registration wizard draft, kept in sessionStorage so a refresh mid-way (or
// a trip to a sign-in provider and back) doesn't lose what was typed.
//
// Never stored: the password. It is stripped here, not by the callers, so a
// future field added to the form can't accidentally leak one into storage.
// sessionStorage is per-tab and cleared when the tab closes; the draft is
// also removed as soon as the account is created.

const DRAFT_KEY = "zoiko_payroll_register_draft_v1";
const NEVER_STORED = new Set(["password"]);

export const EMPTY_FORM = Object.freeze({
  orgName: "",
  companyType: "",
  industry: "",
  country: "",
  state: "",
  city: "",
  address: "",
  taxNo: "",
  taxIdentifiers: {},
  firstName: "",
  lastName: "",
  adminEmail: "",
  phoneCountry: "",
  // True once the admin picks a calling code by hand; until then the code
  // follows the organization's country from step 1.
  phoneCountryTouched: false,
  phoneNumber: "",
  password: "",
  timezone: "",
  termsAccepted: false,
});

function storage() {
  try {
    return window.sessionStorage;
  } catch {
    return null; // Blocked storage (some private modes): the draft is a convenience only.
  }
}

/** Returns {form, planCode, social} or null when there is no usable draft. */
export function loadDraft() {
  const store = storage();
  if (!store) return null;
  try {
    const raw = store.getItem(DRAFT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object") return null;
    const form = { ...EMPTY_FORM };
    for (const key of Object.keys(EMPTY_FORM)) {
      if (NEVER_STORED.has(key)) continue;
      if (parsed.form && key in parsed.form) form[key] = parsed.form[key];
    }
    if (!form.taxIdentifiers || typeof form.taxIdentifiers !== "object") form.taxIdentifiers = {};
    return {
      form,
      planCode: typeof parsed.planCode === "string" ? parsed.planCode : null,
      social: parsed.social && typeof parsed.social === "object" ? parsed.social : null,
    };
  } catch {
    return null;
  }
}

export function saveDraft({ form, planCode, social }) {
  const store = storage();
  if (!store) return;
  const safeForm = {};
  for (const [key, value] of Object.entries(form)) {
    if (!NEVER_STORED.has(key)) safeForm[key] = value;
  }
  try {
    store.setItem(DRAFT_KEY, JSON.stringify({ form: safeForm, planCode, social }));
  } catch {
    // Quota / blocked storage: keep working without persistence.
  }
}

export function clearDraft() {
  const store = storage();
  if (!store) return;
  try {
    store.removeItem(DRAFT_KEY);
  } catch {
    // ignore
  }
}
