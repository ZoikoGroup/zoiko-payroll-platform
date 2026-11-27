import { Building, Factory, FileText, Landmark, MapPin } from "lucide-react";

import { REGISTRATION_COUNTRIES, getStatesForCountryName } from "../../../utils/registrationRegions";
import { getJurisdictionTaxFields, getJurisdictionTaxSchema } from "../../../utils/jurisdictionTax";
import CountrySelect from "../../jurisdiction/CountrySelect";
import { DIAL_CODES } from "../PhoneInput";
import { Field, IconInput, IconSelect, StepHeading, errorId } from "./fields";

// Each registration country with its ISO code, so the picker can show its flag.
const COUNTRY_OPTIONS = REGISTRATION_COUNTRIES.map((name) => ({ value: name, label: name, code: DIAL_CODES[name]?.[0] }));

export const COMPANY_TYPES = [
  "Private Limited", "Public Limited", "Limited Liability Company (LLC)", "Sole Proprietorship",
  "Partnership", "Corporation", "Non-profit", "Government / Public sector", "Other",
];
export const INDUSTRIES = [
  "Technology", "Telecommunications", "Financial Services", "Healthcare", "Manufacturing",
  "Retail & E-commerce", "Professional Services", "Education", "Construction", "Hospitality",
  "Transport & Logistics", "Energy & Utilities", "Media & Entertainment", "Non-profit", "Other",
];

// Step 1. One grid for every field: three columns on wide screens, two on
// laptops/tablets, one on phones. The address takes two columns and the tax
// registration field(s) flow after it, so the step stays short enough to
// sit beside the brand panel without scrolling on a 1366 x 768 screen.
export default function OrganizationStep({ form, errors, onChange, onCountryChange, onTaxChange }) {
  const states = getStatesForCountryName(form.country);
  const taxFields = getJurisdictionTaxFields(form.country);
  const taxSchema = getJurisdictionTaxSchema(form.country);
  const statePlaceholder = !form.country ? "Select country first" : states.length === 0 ? "Not applicable" : "Select state";

  return (
    <div>
      <StepHeading title="Organization details" />
      <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
        <Field id="orgName" label="Organization name" required error={errors.orgName}>
          <IconInput icon={Building} id="orgName" required autoComplete="organization" error={errors.orgName}
            value={form.orgName} onChange={(e) => onChange("orgName", e.target.value)} placeholder="e.g. Zoiko Telecom" />
        </Field>
        <Field id="companyType" label="Company type" required error={errors.companyType}>
          <IconSelect icon={FileText} id="companyType" required error={errors.companyType} value={form.companyType}
            onChange={(e) => onChange("companyType", e.target.value)}>
            <option value="">Select type</option>
            {COMPANY_TYPES.map((t) => <option key={t} value={t}>{t}</option>)}
          </IconSelect>
        </Field>
        <Field id="industry" label="Industry" required error={errors.industry}>
          <IconSelect icon={Factory} id="industry" required error={errors.industry} value={form.industry}
            onChange={(e) => onChange("industry", e.target.value)}>
            <option value="">Select industry</option>
            {INDUSTRIES.map((t) => <option key={t} value={t}>{t}</option>)}
          </IconSelect>
        </Field>

        <Field id="country" label="Country" required error={errors.country}>
          <CountrySelect id="country" variant="auth" required value={form.country} onChange={onCountryChange}
            options={COUNTRY_OPTIONS} placeholder="Select country" invalid={Boolean(errors.country)}
            describedBy={errors.country ? errorId("country") : undefined} />
        </Field>
        <Field id="state" label="State / Province" error={errors.state}>
          <IconSelect icon={MapPin} id="state" value={form.state} disabled={states.length === 0}
            onChange={(e) => onChange("state", e.target.value)}>
            <option value="">{statePlaceholder}</option>
            {states.map((s) => <option key={s} value={s}>{s}</option>)}
          </IconSelect>
        </Field>
        <Field id="city" label="City" error={errors.city}>
          <IconInput icon={Landmark} id="city" value={form.city} autoComplete="address-level2"
            onChange={(e) => onChange("city", e.target.value)} placeholder="e.g. New York" />
        </Field>

        <Field id="address" label="Address" required error={errors.address} className="sm:col-span-2">
          <IconInput icon={MapPin} id="address" required autoComplete="street-address" error={errors.address}
            value={form.address} onChange={(e) => onChange("address", e.target.value)} placeholder="e.g. 123 Main St, Suite 100" />
        </Field>
        {taxFields.length > 0 ? (
          taxFields.map((f) => {
            const id = `reg-${f.key}`;
            const error = errors[`tax:${f.key}`];
            return (
              <Field key={f.key} id={id} label={f.label} required={f.primary} error={error}
                info={`${taxSchema.label} for payroll in ${form.country}. Format is checked when you continue.`}>
                <IconInput icon={FileText} id={id} error={error} value={form.taxIdentifiers[f.key] || ""}
                  onChange={(e) => onTaxChange(f.key, e.target.value)} placeholder={`e.g. ${f.example}`} />
              </Field>
            );
          })
        ) : (
          <Field id="taxNo" label="Tax registration no." error={errors.taxNo}
            info="Your company's tax or business registration number for payroll filings.">
            <IconInput icon={FileText} id="taxNo" value={form.taxNo} onChange={(e) => onChange("taxNo", e.target.value)}
              placeholder="e.g. EIN, VAT no." />
          </Field>
        )}
      </div>
    </div>
  );
}
