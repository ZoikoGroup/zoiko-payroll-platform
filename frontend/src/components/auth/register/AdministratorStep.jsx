import { useState } from "react";
import { Check, Clock, Eye, EyeOff, Lock, Mail, UserRound } from "lucide-react";

import { getTimezonesForCountryName } from "../../../utils/registrationRegions";
import { AUTH_FOOTER_LINKS } from "../AuthLayout";
import PhoneInput from "../PhoneInput";
import { PASSWORD_CHECKS } from "./registerValidation";
import { Field, FieldError, IconInput, IconSelect, StepHeading, controlClass, errorId, invalidProps } from "./fields";

const termsLink = AUTH_FOOTER_LINKS.find((l) => l.label === "Terms")?.href;
const privacyLink = AUTH_FOOTER_LINKS.find((l) => l.label === "Privacy")?.href;

// Step 2: the primary administrator and the account's setup preferences, in
// one grid (three columns on wide screens, two on laptops/tablets, one on
// phones) so the step fits beside the brand panel.
//
// `social` is set when the admin signed up through a provider: name and
// email come pre-filled, the email is read-only (it is the provider's
// verified address) unless `social.emailEditable`, and there is no password.
export default function AdministratorStep({ form, errors, onChange, onPhoneCountryChange, social }) {
  const [showPassword, setShowPassword] = useState(false);
  const timezones = getTimezonesForCountryName(form.country);
  const emailReadOnly = Boolean(social && !social.emailEditable);

  return (
    <div>
      <StepHeading title="Administrator & setup" subtitle="This will be your primary administrator account." />
      <div className="grid gap-x-4 gap-y-3 sm:grid-cols-2 xl:grid-cols-3">
        <Field id="firstName" label="First name" required error={errors.firstName}>
          <IconInput icon={UserRound} id="firstName" required autoComplete="given-name" error={errors.firstName}
            value={form.firstName} onChange={(e) => onChange("firstName", e.target.value)} placeholder="e.g. Lennox" />
        </Field>
        <Field id="lastName" label="Last name" required error={errors.lastName}>
          <IconInput icon={UserRound} id="lastName" required autoComplete="family-name" error={errors.lastName}
            value={form.lastName} onChange={(e) => onChange("lastName", e.target.value)} placeholder="e.g. Green" />
        </Field>
        <Field id="adminEmail" label="Work email" required error={errors.adminEmail} hint={social?.emailHint}
          className={social?.emailHint ? "sm:col-span-2 xl:col-span-1" : ""}>
          <IconInput icon={Mail} id="adminEmail" type="email" required autoComplete="email" error={errors.adminEmail}
            value={form.adminEmail} onChange={(e) => onChange("adminEmail", e.target.value)}
            placeholder="name@company.com" readOnly={emailReadOnly}
            title={emailReadOnly ? `Your ${social.label} account's email` : undefined} />
        </Field>
        <Field id="phone" label="Phone number" required error={errors.phone}>
          <PhoneInput id="phone" country={form.phoneCountry} onCountryChange={onPhoneCountryChange}
            number={form.phoneNumber} onNumberChange={(v) => onChange("phoneNumber", v)}
            invalid={Boolean(errors.phone)} describedBy={errors.phone ? errorId("phone") : undefined} />
        </Field>
        {!social && (
          <Field id="password" label="Password" required error={errors.password}
            hint={
              <ul className="flex flex-wrap gap-x-2.5 gap-y-0.5">
                {PASSWORD_CHECKS.map(([label, test]) => {
                  const ok = test(form.password);
                  return (
                    <li key={label} className={`inline-flex items-center gap-1 ${ok ? "text-emerald-700" : ""}`}>
                      {ok ? <Check size={13} aria-hidden="true" /> : <span aria-hidden="true">•</span>} {label}
                    </li>
                  );
                })}
              </ul>
            }>
            <div className="relative">
              <Lock size={17} className="pointer-events-none absolute left-4 top-1/2 -translate-y-1/2 text-slate-500" aria-hidden="true" />
              <input id="password" type={showPassword ? "text" : "password"} autoComplete="new-password"
                value={form.password} onChange={(e) => onChange("password", e.target.value)}
                {...invalidProps("password", errors.password, true)}
                placeholder="Create password"
                className={controlClass({ withTrailing: true, invalid: Boolean(errors.password) })} />
              <button type="button" onClick={() => setShowPassword((v) => !v)}
                aria-label={showPassword ? "Hide password" : "Show password"}
                className="absolute right-3 top-1/2 -translate-y-1/2 rounded p-1 text-slate-500 hover:text-slate-800">
                {showPassword ? <EyeOff size={18} /> : <Eye size={18} />}
              </button>
            </div>
          </Field>
        )}
        <Field id="timezone" label="Timezone" required={timezones.length > 0} error={errors.timezone}>
          <IconSelect icon={Clock} id="timezone" value={form.timezone} required={timezones.length > 0}
            error={errors.timezone} disabled={timezones.length === 0} onChange={(e) => onChange("timezone", e.target.value)}>
            {timezones.length === 0
              ? <option value="">Select country first</option>
              : timezones.map((tz) => <option key={tz} value={tz}>{tz}</option>)}
          </IconSelect>
        </Field>
        <Field id="product" label="Product" required>
          <div id="product" role="radio" aria-checked="true" tabIndex={0} title="Pay runs, statutory rates & payslips"
            className="flex h-11 items-center gap-3 rounded-lg border-2 border-blue-600 bg-blue-50 px-4">
            <span className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full border-2 border-blue-600">
              <span className="h-2 w-2 rounded-full bg-blue-600" />
            </span>
            <span className="min-w-0 truncate text-[14px] font-semibold text-blue-800">Zoiko Payroll</span>
          </div>
        </Field>
        <div className={`self-end ${social ? "sm:col-span-2 xl:col-span-3" : "sm:col-span-2"}`}>
          <label className="flex min-h-11 cursor-pointer items-center gap-2.5 text-[14px] text-slate-700">
            <input id="termsAccepted" type="checkbox" checked={form.termsAccepted}
              onChange={(e) => onChange("termsAccepted", e.target.checked)}
              {...invalidProps("termsAccepted", errors.termsAccepted, true)}
              className="h-4 w-4 shrink-0 rounded border-slate-300 accent-blue-600" />
            <span>
              I agree to the{" "}
              <a href={termsLink} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-700 hover:underline">Terms of Service</a>
              {" "}and{" "}
              <a href={privacyLink} target="_blank" rel="noopener noreferrer" className="font-medium text-blue-700 hover:underline">Privacy Policy</a>.
              <span className="text-red-600" aria-hidden="true"> *</span>
            </span>
          </label>
          <FieldError id="termsAccepted" message={errors.termsAccepted} />
        </div>
      </div>
    </div>
  );
}
