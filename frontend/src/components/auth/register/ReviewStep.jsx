import { Pencil } from "lucide-react";

import { getJurisdictionTaxFields } from "../../../utils/jurisdictionTax";
import { StepHeading } from "./fields";

function ReviewRow({ label, value }) {
  return (
    <div className="grid grid-cols-[120px_1fr] gap-3 py-1.5 text-[14px]">
      <dt className="text-[13px] text-slate-500">{label}</dt>
      <dd className="break-words text-slate-900">{value || <span className="text-slate-400">—</span>}</dd>
    </div>
  );
}

function ReviewGroup({ title, onEdit, children }) {
  return (
    <section className="min-w-0 rounded-xl border border-slate-200 px-4 py-1.5">
      <div className="flex items-center justify-between gap-2 border-b border-slate-100 py-1.5">
        <h4 className="text-[14px] font-bold text-slate-900">{title}</h4>
        <button type="button" onClick={onEdit}
          className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-[13px] font-medium text-blue-700 hover:bg-blue-50">
          <Pencil size={13} aria-hidden="true" /> Edit<span className="sr-only"> {title.toLowerCase()}</span>
        </button>
      </div>
      <dl className="divide-y divide-slate-100">{children}</dl>
    </section>
  );
}

// Step 3: everything entered so far, grouped by the step it came from, each
// with an Edit link back to that step (the data is kept).
export default function ReviewStep({ form, phone, social, selectedPlan, onEditStep }) {
  const taxFields = getJurisdictionTaxFields(form.country);
  const fullName = `${form.firstName.trim()} ${form.lastName.trim()}`.trim();
  return (
    <div>
      <StepHeading title="Review & confirm" subtitle="Check your details, then choose a plan to create the account." />
      <div className="grid items-start gap-3 xl:grid-cols-2">
        <ReviewGroup title="Organization" onEdit={() => onEditStep(1)}>
          <ReviewRow label="Organization" value={form.orgName} />
          <ReviewRow label="Company type" value={form.companyType} />
          <ReviewRow label="Industry" value={form.industry} />
          <ReviewRow label="Location" value={[form.address, form.city, form.state, form.country].filter(Boolean).join(", ")} />
          {taxFields.length > 0
            ? taxFields.map((f) => <ReviewRow key={f.key} label={f.label} value={form.taxIdentifiers[f.key]} />)
            : <ReviewRow label="Tax registration" value={form.taxNo} />}
        </ReviewGroup>
        <ReviewGroup title="Administrator" onEdit={() => onEditStep(2)}>
          <ReviewRow label="Administrator" value={fullName} />
          <ReviewRow label="Work email" value={form.adminEmail} />
          <ReviewRow label="Phone" value={phone} />
          <ReviewRow label="Sign-in" value={social ? `${social.label} account` : "Email and password"} />
          <ReviewRow label="Timezone" value={form.timezone} />
          <ReviewRow label="Product" value="Zoiko Payroll" />
          <ReviewRow label="Plan" value={selectedPlan ? `${selectedPlan.name} (${selectedPlan.priceLabel})` : "Choose in the next step"} />
        </ReviewGroup>
      </div>
    </div>
  );
}
