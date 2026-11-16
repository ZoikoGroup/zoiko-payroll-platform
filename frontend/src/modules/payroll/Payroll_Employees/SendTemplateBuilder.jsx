import { useEffect, useMemo, useRef, useState } from "react";
import { CheckCircle2, Plus, Send, TriangleAlert } from "lucide-react";
import {
  getCustomFields, createCustomField, createUpdateForm, sendUpdateForm,
} from "../../../service/payrollService";
import { STANDARD_EMPLOYEE_FIELDS } from "./EmployeeBulkEditPanel";
import {
  EmployeePicker, FieldChecklist, WizardError, WizardFooter, WizardSteps, sectionLabelClass, wizardInputClass,
} from "./EmployeeWizardParts";
import { useToast } from "../ToastContext";

const CUSTOM_FIELD_TYPES = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "select", label: "Dropdown" },
];

const STEPS = [
  { id: "employees", label: "Select employees" },
  { id: "form", label: "Form details" },
  { id: "review", label: "Review & send" },
];

const REVIEW_NAME_LIMIT = 10;

function toFieldConfig(field, source) {
  return {
    key: source === "custom" ? field.fieldKey : field.key,
    label: field.label,
    type: source === "custom" ? field.fieldType : field.type,
    source,
    required: false,
    options: source === "custom" ? field.selectOptions || null : field.options || null,
  };
}

// Step-by-step Send Template: pick employees -> name the form and choose the
// fields they should fill in -> review -> send. The form is created only at
// Send (it used to be saved as soon as the fields were chosen, leaving unused
// forms behind when an admin backed out); a retry after a failed send reuses
// it as long as the name and fields are unchanged.
export default function SendTemplateBuilder({ employees, selectedIds, onClose, onSent, currencyInfo, orgCountryCode }) {
  const { addToast } = useToast();
  const [step, setStep] = useState(0); // 0..2, then "done"
  const [pickedIds, setPickedIds] = useState(() => new Set(selectedIds || []));
  const [formName, setFormName] = useState("");
  const [checkedStandard, setCheckedStandard] = useState({});
  const [customFields, setCustomFields] = useState([]);
  const [checkedCustom, setCheckedCustom] = useState({});
  const [showAddField, setShowAddField] = useState(false);
  const [newFieldLabel, setNewFieldLabel] = useState("");
  const [newFieldType, setNewFieldType] = useState("text");
  const [newFieldOptions, setNewFieldOptions] = useState("");
  const [addingField, setAddingField] = useState(false);
  const [error, setError] = useState("");
  // { form, signature } of the form created by the last send attempt.
  const [created, setCreated] = useState(null);
  const [sending, setSending] = useState(false);
  const [sendResults, setSendResults] = useState(null);
  const [showAllNames, setShowAllNames] = useState(false);
  const headingRef = useRef(null);

  useEffect(() => {
    getCustomFields().then(setCustomFields).catch(() => {});
  }, []);

  useEffect(() => {
    headingRef.current?.focus();
  }, [step]);

  const selectedEmployees = useMemo(
    () => (employees || []).filter((e) => pickedIds.has(e.id)),
    [employees, pickedIds],
  );
  const recipients = selectedEmployees.filter((e) => e.email);
  const skipped = selectedEmployees.filter((e) => !e.email);

  const fields = useMemo(() => [
    ...STANDARD_EMPLOYEE_FIELDS.filter((f) => checkedStandard[f.key]).map((f) => toFieldConfig(f, "standard")),
    ...customFields.filter((f) => checkedCustom[f.fieldKey]).map((f) => toFieldConfig(f, "custom")),
  ], [checkedStandard, checkedCustom, customFields]);
  const signature = JSON.stringify({ name: formName.trim(), fields });

  function goTo(next) {
    setError("");
    setStep(next);
  }

  function toggleStandard(key) {
    setCheckedStandard((prev) => ({ ...prev, [key]: !prev[key] }));
  }
  function toggleCustom(key) {
    setCheckedCustom((prev) => ({ ...prev, [key]: !prev[key] }));
  }

  async function handleAddCustomField() {
    if (!newFieldLabel.trim()) {
      setError("Enter a label for the new field.");
      return;
    }
    const options = newFieldType === "select"
      ? newFieldOptions.split(",").map((o) => o.trim()).filter(Boolean)
      : null;
    if (newFieldType === "select" && options.length === 0) {
      setError("Enter at least one option for a dropdown field.");
      return;
    }
    setAddingField(true);
    setError("");
    try {
      const field = await createCustomField({ label: newFieldLabel.trim(), fieldType: newFieldType, selectOptions: options });
      setCustomFields((prev) => [...prev, field]);
      setCheckedCustom((prev) => ({ ...prev, [field.fieldKey]: true }));
      setNewFieldLabel("");
      setNewFieldType("text");
      setNewFieldOptions("");
      setShowAddField(false);
      addToast?.(`Custom field "${field.label}" added — it now applies to every employee.`, "success");
    } catch (err) {
      setError(err.message || "Could not add custom field.");
    } finally {
      setAddingField(false);
    }
  }

  function handleContinueFromForm() {
    if (!formName.trim()) {
      setError("Give this form a name.");
      return;
    }
    if (fields.length === 0) {
      setError("Choose at least one field for employees to fill in.");
      return;
    }
    goTo(2);
  }

  async function handleSend() {
    setError("");
    if (recipients.length === 0) {
      setError("None of the selected employees has an email address on file. Go back to step 1 and choose others.");
      return;
    }
    setSending(true);
    try {
      let form = created && created.signature === signature ? created.form : null;
      if (!form) {
        form = await createUpdateForm({ name: formName.trim(), fields });
        setCreated({ form, signature });
      }
      const res = await sendUpdateForm(form.id, recipients.map((e) => e.id));
      const results = res.results || [];
      setSendResults(results);
      const sentCount = results.filter((r) => r.status === "sent").length;
      // Success only when every recipient's email actually went out.
      const tone = sentCount === recipients.length ? "success" : sentCount > 0 ? "warning" : "error";
      addToast?.(`Emailed ${sentCount} of ${recipients.length} employee(s).`, tone);
      onSent?.();
      setStep("done");
    } catch (err) {
      setError(err.message || "Could not send the form. Please try again.");
    } finally {
      setSending(false);
    }
  }

  function startOver() {
    setPickedIds(new Set());
    setFormName("");
    setCheckedStandard({});
    setCheckedCustom({});
    setCreated(null);
    setSendResults(null);
    setShowAllNames(false);
    goTo(0);
  }

  const nameOf = (id) => (employees || []).find((e) => e.id === id)?.name || `#${id}`;
  const visibleRecipients = showAllNames ? recipients : recipients.slice(0, REVIEW_NAME_LIMIT);
  const resultList = (status) => (sendResults || []).filter((r) => r.status === status);

  return (
    <div className="space-y-6">
      <div className="space-y-4">
        <div>
          <h3 ref={headingRef} tabIndex={-1} className="text-[15px] font-bold text-foreground outline-none">
            Send Template
          </h3>
          <p className="mt-1 text-[13px] text-foreground-muted">
            Email selected employees a no-login form to update their details. You review every response before it changes
            anything.
          </p>
        </div>
        <WizardSteps steps={STEPS} current={step === "done" ? STEPS.length : step} />
      </div>

      {step === 0 && (
        <>
          <div>
            <span className={sectionLabelClass}>Who should receive the form?</span>
            <EmployeePicker
              employees={employees}
              selectedIds={pickedIds}
              onSelectionChange={setPickedIds}
              currencyInfo={currencyInfo}
              orgCountryCode={orgCountryCode}
              showEmail
            />
            {skipped.length > 0 && (
              <p className="mt-2 flex items-center gap-1.5 text-[12px] text-warning">
                <TriangleAlert size={14} aria-hidden="true" />
                {skipped.length} selected employee{skipped.length === 1 ? " has" : "s have"} no email and will be skipped.
              </p>
            )}
          </div>
          <WizardError>{error}</WizardError>
          <WizardFooter
            onCancel={onClose}
            onNext={() => goTo(1)}
            nextDisabled={recipients.length === 0}
            nextLabel={
              selectedEmployees.length === 0 ? "Select employees to continue"
                : recipients.length === 0 ? "No selected employee has an email"
                : `Continue with ${recipients.length} employee${recipients.length === 1 ? "" : "s"}`
            }
          />
        </>
      )}

      {step === 1 && (
        <>
          <div className="rounded-[12px] border border-border bg-surface-muted px-4 py-2.5 text-[13px] text-foreground" aria-live="polite">
            Sending to <strong>{recipients.length}</strong> employee{recipients.length === 1 ? "" : "s"} ·{" "}
            <strong>{fields.length}</strong> field{fields.length === 1 ? "" : "s"} chosen
          </div>

          <div>
            <label htmlFor="send-template-form-name" className={sectionLabelClass}>Form name</label>
            <input
              id="send-template-form-name"
              className={wizardInputClass}
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="e.g. Bank Details Update"
            />
          </div>

          <div>
            <span className={sectionLabelClass}>Standard fields</span>
            <FieldChecklist
              fields={STANDARD_EMPLOYEE_FIELDS.map((f) => ({ key: f.key, label: f.label }))}
              checked={checkedStandard}
              onToggle={toggleStandard}
            />
          </div>

          <div>
            <div className="mb-2 flex items-center justify-between gap-3">
              <span className="block text-[11px] font-bold uppercase tracking-widest text-foreground-muted">
                Custom fields (organization-wide)
              </span>
              <button
                type="button"
                onClick={() => setShowAddField((v) => !v)}
                aria-expanded={showAddField}
                className="flex shrink-0 items-center gap-1 whitespace-nowrap text-[12px] font-semibold text-primary transition-colors duration-200 hover:text-primary-hover"
              >
                <Plus size={13} aria-hidden="true" /> Add field
              </button>
            </div>

            {customFields.length > 0 ? (
              <div className="mb-3">
                <FieldChecklist
                  tone="teal"
                  fields={customFields.map((f) => ({ key: f.fieldKey, label: f.label, hint: f.fieldType }))}
                  checked={checkedCustom}
                  onToggle={toggleCustom}
                />
              </div>
            ) : (
              !showAddField && (
                <p className="mb-3 text-[12.5px] text-foreground-muted">No custom fields yet. Use “Add field” to create one.</p>
              )
            )}

            {showAddField && (
              <div className="space-y-3 rounded-[12px] border border-border p-4">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <input
                    aria-label="New field label"
                    className={wizardInputClass}
                    placeholder="Field label, e.g. Emergency Contact"
                    value={newFieldLabel}
                    onChange={(e) => setNewFieldLabel(e.target.value)}
                  />
                  <select aria-label="New field type" className={wizardInputClass} value={newFieldType} onChange={(e) => setNewFieldType(e.target.value)}>
                    {CUSTOM_FIELD_TYPES.map((t) => <option key={t.value} value={t.value}>{t.label}</option>)}
                  </select>
                </div>
                {newFieldType === "select" && (
                  <input
                    aria-label="Dropdown options"
                    className={wizardInputClass}
                    placeholder="Comma-separated options, e.g. Yes, No, Not sure"
                    value={newFieldOptions}
                    onChange={(e) => setNewFieldOptions(e.target.value)}
                  />
                )}
                <p className="text-[11px] text-foreground-muted">
                  This field will show up for every employee in this organization going forward, not just on this form.
                </p>
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => setShowAddField(false)} className="px-3 py-1.5 text-[12.5px] font-semibold text-foreground-muted hover:text-foreground">
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleAddCustomField}
                    disabled={addingField}
                    className="rounded-[10px] bg-category-teal px-4 py-1.5 text-[12.5px] font-bold text-white transition-all duration-200 hover:opacity-90 disabled:opacity-60"
                  >
                    {addingField ? "Adding…" : "Add field"}
                  </button>
                </div>
              </div>
            )}
          </div>

          <WizardError>{error}</WizardError>
          <WizardFooter
            onCancel={onClose}
            onPrevious={() => goTo(0)}
            onNext={handleContinueFromForm}
            nextDisabled={fields.length === 0 || !formName.trim()}
            nextLabel="Review"
          />
        </>
      )}

      {step === 2 && (
        <>
          <div className="grid grid-cols-1 items-start gap-4 lg:grid-cols-2">
            <div className="rounded-[14px] border border-border">
              <div className="border-b border-border px-4 py-3">
                <p className="text-[13px] font-bold text-foreground">“{formName.trim()}”</p>
                <p className="text-[12px] text-foreground-muted">
                  Asks for {fields.length} field{fields.length === 1 ? "" : "s"}
                </p>
              </div>
              <div className="flex flex-wrap gap-2 px-4 py-3">
                {fields.map((f) => (
                  <span
                    key={`${f.source}-${f.key}`}
                    className={`rounded-full px-3 py-1 text-[12px] font-semibold ${
                      f.source === "custom" ? "bg-category-teal/10 text-category-teal" : "bg-primary/10 text-primary"
                    }`}
                  >
                    {f.label}
                  </span>
                ))}
              </div>
            </div>
            <div className="rounded-[14px] border border-border">
              <div className="border-b border-border px-4 py-3">
                <p className="text-[13px] font-bold text-foreground">
                  To {recipients.length} employee{recipients.length === 1 ? "" : "s"}
                </p>
              </div>
              <ul className="max-h-72 divide-y divide-border overflow-y-auto">
                {visibleRecipients.map((e) => (
                  <li key={e.id} className="flex flex-wrap items-center justify-between gap-2 px-4 py-2 text-[13px]">
                    <span className="font-semibold text-foreground">{e.name}</span>
                    <span className="text-foreground-muted">{e.email}</span>
                  </li>
                ))}
              </ul>
              {recipients.length > REVIEW_NAME_LIMIT && (
                <button
                  type="button"
                  onClick={() => setShowAllNames((v) => !v)}
                  className="w-full border-t border-border px-4 py-2 text-left text-[12.5px] font-semibold text-primary hover:text-primary-hover"
                >
                  {showAllNames ? "Show fewer" : `Show all ${recipients.length}`}
                </button>
              )}
            </div>
          </div>
          {skipped.length > 0 && (
            <div className="rounded-[12px] border border-warning/30 bg-warning/10 px-4 py-3 text-[13px] text-warning">
              <p className="font-semibold">Skipped — no email on file ({skipped.length}):</p>
              <p className="mt-0.5">{skipped.map((e) => e.name).join(", ")}</p>
            </div>
          )}
          <p className="text-[12px] text-foreground-muted">
            Each employee gets a personal link that works without signing in. It expires in 7 days and can be used once.
            Responses wait in Review Submissions until you approve them.
          </p>
          <WizardError>{error}</WizardError>
          <WizardFooter
            onCancel={onClose}
            onPrevious={() => goTo(1)}
            onNext={handleSend}
            busy={sending}
            nextIcon={<Send size={14} aria-hidden="true" />}
            nextLabel={sending ? "Sending…" : `Send to ${recipients.length} employee${recipients.length === 1 ? "" : "s"}`}
          />
        </>
      )}

      {step === "done" && sendResults && (
        <>
          <div
            className={`flex items-start gap-3 rounded-[12px] border px-4 py-3 text-[13px] ${
              resultList("sent").length > 0 ? "border-primary/20 bg-primary/10 text-primary" : "border-warning/30 bg-warning/10 text-warning"
            }`}
          >
            {resultList("sent").length > 0
              ? <CheckCircle2 size={18} className="mt-0.5 shrink-0" aria-hidden="true" />
              : <TriangleAlert size={18} className="mt-0.5 shrink-0" aria-hidden="true" />}
            <div>
              <p>
                {resultList("sent").length > 0
                  ? `${resultList("sent").length} of ${sendResults.length} emailed successfully.`
                  : `No emails were sent (0 of ${sendResults.length}). See the reasons below.`}
              </p>
              {resultList("sent").filter((r) => r.note).map((r, i) => (
                <p key={i} className="mt-1 text-[12px] text-foreground-muted">{r.note}</p>
              ))}
            </div>
          </div>
          {resultList("not_delivered").length > 0 && (
            <div className="rounded-[12px] border border-warning/20 bg-warning/10 px-4 py-3 text-[13px] text-warning">
              <p className="mb-1 font-semibold">Not emailed:</p>
              <ul className="space-y-0.5">
                {resultList("not_delivered").map((r, i) => (
                  <li key={i}>{nameOf(r.employeeId)}{r.email ? ` (${r.email})` : ""} — {r.reason}</li>
                ))}
              </ul>
            </div>
          )}
          {resultList("failed").length > 0 && (
            <div className="rounded-[12px] border border-error/20 bg-error/10 px-4 py-3 text-[13px] text-error">
              <p className="mb-1 font-semibold">Could not send to:</p>
              <ul className="space-y-0.5">
                {resultList("failed").map((r, i) => (
                  <li key={i}>{nameOf(r.employeeId)}{r.email ? ` (${r.email})` : ""} — {r.reason}</li>
                ))}
              </ul>
            </div>
          )}
          {skipped.length > 0 && (
            <p className="text-[12.5px] text-foreground-muted">
              Skipped (no email on file): {skipped.map((e) => e.name).join(", ")}.
            </p>
          )}
          <WizardFooter onCancel={startOver} cancelLabel="Send another form" onNext={onClose} nextLabel="Done" />
        </>
      )}
    </div>
  );
}
