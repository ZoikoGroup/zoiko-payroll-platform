import React, { useEffect, useMemo, useState } from "react";
import { CheckSquare, Square, Plus, Send, Loader2 } from "lucide-react";
import {
  getCustomFields, createCustomField, createUpdateForm, sendUpdateForm,
} from "../../../service/payrollService";
import { STANDARD_EMPLOYEE_FIELDS } from "./EmployeeBulkEditPanel";
import EmployeeTable from "./EmployeeTable";
import { useToast } from "../ToastContext";

const inputClass =
  "w-full rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] bg-[#F8F7F4] dark:bg-[#1A1816] px-3 py-2 text-[13px] text-[#1A1816] dark:text-[#F0EDE8] placeholder:text-[#9E9690] focus:outline-none focus:border-[#19C58A] focus:ring-2 focus:ring-[#19C58A]/20 transition-all duration-200";

const CUSTOM_FIELD_TYPES = [
  { value: "text", label: "Text" },
  { value: "number", label: "Number" },
  { value: "date", label: "Date" },
  { value: "select", label: "Dropdown" },
];

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

export default function SendTemplateBuilder({ employees, selectedIds, onClose, onSent, currencyInfo }) {
  const { addToast } = useToast();
  const [step, setStep] = useState("build"); // build | send | done
  const [formName, setFormName] = useState("");
  const [checkedStandard, setCheckedStandard] = useState({});
  const [customFields, setCustomFields] = useState([]);
  const [checkedCustom, setCheckedCustom] = useState({});
  const [showAddField, setShowAddField] = useState(false);
  const [newFieldLabel, setNewFieldLabel] = useState("");
  const [newFieldType, setNewFieldType] = useState("text");
  const [newFieldOptions, setNewFieldOptions] = useState("");
  const [addingField, setAddingField] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [savedForm, setSavedForm] = useState(null);

  const [pickedIds, setPickedIds] = useState(() => new Set(selectedIds || []));
  const [sending, setSending] = useState(false);
  const [sendResults, setSendResults] = useState(null);

  useEffect(() => {
    getCustomFields().then(setCustomFields).catch(() => {});
  }, []);

  const targetIds = useMemo(() => [...pickedIds], [pickedIds]);

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
    setAddingField(true);
    setError("");
    try {
      const options = newFieldType === "select"
        ? newFieldOptions.split(",").map((o) => o.trim()).filter(Boolean)
        : null;
      const created = await createCustomField({ label: newFieldLabel.trim(), fieldType: newFieldType, selectOptions: options });
      setCustomFields((prev) => [...prev, created]);
      setCheckedCustom((prev) => ({ ...prev, [created.fieldKey]: true }));
      setNewFieldLabel("");
      setNewFieldType("text");
      setNewFieldOptions("");
      setShowAddField(false);
      addToast?.(`Custom field "${created.label}" added — it now applies to every employee.`, "success");
    } catch (err) {
      setError(err.message || "Could not add custom field.");
    } finally {
      setAddingField(false);
    }
  }

  async function handleSaveForm() {
    setError("");
    if (!formName.trim()) {
      setError("Give this form a name.");
      return;
    }
    const fields = [
      ...STANDARD_EMPLOYEE_FIELDS.filter((f) => checkedStandard[f.key]).map((f) => toFieldConfig(f, "standard")),
      ...customFields.filter((f) => checkedCustom[f.fieldKey]).map((f) => toFieldConfig(f, "custom")),
    ];
    if (fields.length === 0) {
      setError("Select at least one field for the form to ask for.");
      return;
    }
    setSaving(true);
    try {
      const form = await createUpdateForm({ name: formName.trim(), fields });
      setSavedForm(form);
      setStep("send");
    } catch (err) {
      setError(err.message || "Could not save the form.");
    } finally {
      setSaving(false);
    }
  }

  async function handleSend() {
    if (targetIds.length === 0) {
      setError("Select at least one employee to send this form to.");
      return;
    }
    setSending(true);
    setError("");
    try {
      const res = await sendUpdateForm(savedForm.id, targetIds);
      setSendResults(res.results || []);
      setStep("done");
      const sentCount = (res.results || []).filter((r) => r.status === "sent").length;
      addToast?.(`Sent to ${sentCount} of ${targetIds.length} employee(s).`, sentCount > 0 ? "success" : "error");
      onSent?.();
    } catch (err) {
      setError(err.message || "Could not send the form.");
    } finally {
      setSending(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h3 className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Send Template</h3>
        <p className="text-[13px] text-[#9E9690] mt-1">
          Build a form, email it to employees with a no-login link, and review what they submit before it changes anything.
        </p>
      </div>

      {step === "build" && (
        <>
          <div>
            <span className="mb-1.5 block text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Form name</span>
            <input
              className={inputClass}
              value={formName}
              onChange={(e) => setFormName(e.target.value)}
              placeholder="e.g. Bank Details Update"
            />
          </div>

          <div>
            <span className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Standard fields</span>
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {STANDARD_EMPLOYEE_FIELDS.map((field) => {
                const isChecked = Boolean(checkedStandard[field.key]);
                return (
                  <button
                    type="button"
                    key={field.key}
                    onClick={() => toggleStandard(field.key)}
                    className={`flex items-center gap-2.5 rounded-[12px] border px-3.5 py-3 text-left text-[13px] font-semibold transition-all duration-200 ${
                      isChecked ? "border-[#19C58A] bg-[#19C58A]/5 text-[#19C58A]" : "border-[#E5E0D9] dark:border-[#38312D] text-[#1A1816] dark:text-[#F0EDE8]"
                    }`}
                  >
                    {isChecked ? <CheckSquare size={16} className="flex-shrink-0" /> : <Square size={16} className="text-[#9E9690] flex-shrink-0" />}
                    {field.label}
                  </button>
                );
              })}
            </div>
          </div>

          <div>
            <div className="flex items-center justify-between mb-2">
              <span className="block text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">Custom fields (permanent, org-wide)</span>
              <button
                type="button"
                onClick={() => setShowAddField((v) => !v)}
                className="flex items-center gap-1 text-[12px] font-semibold text-[#19C58A] hover:text-[#15B07A] transition-colors duration-200"
              >
                <Plus size={13} /> Add field
              </button>
            </div>

            {customFields.length > 0 && (
              <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 mb-3">
                {customFields.map((field) => {
                  const isChecked = Boolean(checkedCustom[field.fieldKey]);
                  return (
                    <button
                      type="button"
                      key={field.fieldKey}
                      onClick={() => toggleCustom(field.fieldKey)}
                      className={`flex items-center gap-2.5 rounded-[12px] border px-3.5 py-3 text-left text-[13px] font-semibold transition-all duration-200 ${
                        isChecked ? "border-[#9D7BF2] bg-[#9D7BF2]/5 text-[#9D7BF2]" : "border-[#E5E0D9] dark:border-[#38312D] text-[#1A1816] dark:text-[#F0EDE8]"
                      }`}
                    >
                      {isChecked ? <CheckSquare size={16} className="flex-shrink-0" /> : <Square size={16} className="text-[#9E9690] flex-shrink-0" />}
                      {field.label}
                      <span className="ml-auto text-[10.5px] font-bold uppercase text-[#9E9690]">{field.fieldType}</span>
                    </button>
                  );
                })}
              </div>
            )}

            {showAddField && (
              <div className="rounded-[12px] border border-[#E5E0D9] dark:border-[#38312D] p-4 space-y-3">
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                  <input
                    className={inputClass}
                    placeholder="Field label, e.g. Emergency Contact"
                    value={newFieldLabel}
                    onChange={(e) => setNewFieldLabel(e.target.value)}
                  />
                  <select className={inputClass} value={newFieldType} onChange={(e) => setNewFieldType(e.target.value)}>
                    {CUSTOM_FIELD_TYPES.map((t) => (
                      <option key={t.value} value={t.value}>{t.label}</option>
                    ))}
                  </select>
                </div>
                {newFieldType === "select" && (
                  <input
                    className={inputClass}
                    placeholder="Comma-separated options, e.g. Yes, No, Not sure"
                    value={newFieldOptions}
                    onChange={(e) => setNewFieldOptions(e.target.value)}
                  />
                )}
                <div className="flex justify-end gap-2">
                  <button type="button" onClick={() => setShowAddField(false)} className="text-[12.5px] font-semibold text-[#9E9690] hover:text-[#6B6560] px-3 py-1.5">
                    Cancel
                  </button>
                  <button
                    type="button"
                    onClick={handleAddCustomField}
                    disabled={addingField}
                    className="rounded-[10px] bg-[#9D7BF2] text-white px-4 py-1.5 text-[12.5px] font-bold hover:bg-[#8A65E8] transition-all duration-200 disabled:opacity-60"
                  >
                    {addingField ? "Adding…" : "Add field"}
                  </button>
                </div>
                <p className="text-[11px] text-[#9E9690]">This field will show up for every employee in this organization going forward, not just on this form.</p>
              </div>
            )}
          </div>

          {error && (
            <div className="rounded-[12px] bg-[#FF6E86]/10 px-4 py-3 text-[13px] text-[#FF6E86] border border-[#FF6E86]/20">{error}</div>
          )}

          <div className="flex justify-end gap-3 border-t border-[#E5E0D9] dark:border-[#38312D] pt-6">
            <button type="button" onClick={onClose} className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]">
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSaveForm}
              disabled={saving}
              className="bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)] disabled:opacity-60"
            >
              {saving ? "Saving…" : "Continue to send"}
            </button>
          </div>
        </>
      )}

      {step === "send" && (
        <>
          <div>
            <span className="mb-2 block text-[11px] font-bold uppercase tracking-widest text-[#9E9690]">
              Send "{savedForm?.name}" to — {pickedIds.size} selected
            </span>
            <EmployeeTable
              employees={employees}
              selectedIds={pickedIds}
              onSelectionChange={setPickedIds}
              currencyInfo={currencyInfo}
            />
            <p className="mt-2 text-[11.5px] text-[#9E9690]">
              Check the header box to select every employee. Employees without an email on file will be skipped. Each link expires in 7 days and can only be used once.
            </p>
          </div>

          {error && (
            <div className="rounded-[12px] bg-[#FF6E86]/10 px-4 py-3 text-[13px] text-[#FF6E86] border border-[#FF6E86]/20">{error}</div>
          )}

          <div className="flex justify-end gap-3 border-t border-[#E5E0D9] dark:border-[#38312D] pt-6">
            <button type="button" onClick={() => setStep("build")} className="border border-[#E5E0D9] dark:border-[#38312D] bg-white dark:bg-[#2A2520] rounded-[12px] px-5 py-2.5 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] transition-all duration-200 hover:border-[#19C58A] hover:text-[#19C58A]">
              Back
            </button>
            <button
              type="button"
              onClick={handleSend}
              disabled={sending}
              className="flex items-center gap-1.5 bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)] disabled:opacity-60"
            >
              {sending ? <Loader2 size={14} className="animate-spin" /> : <Send size={14} />}
              {sending ? "Sending…" : `Send to ${targetIds.length} employee${targetIds.length === 1 ? "" : "s"}`}
            </button>
          </div>
        </>
      )}

      {step === "done" && (
        <>
          <div className="rounded-[12px] bg-[#19C58A]/10 px-4 py-3 text-[13px] text-[#19C58A] border border-[#19C58A]/20">
            {sendResults.filter((r) => r.status === "sent").length} of {sendResults.length} sent successfully.
          </div>
          {sendResults.some((r) => r.status === "failed") && (
            <div className="rounded-[12px] bg-[#FF6E86]/10 px-4 py-3 text-[13px] text-[#FF6E86] border border-[#FF6E86]/20">
              <p className="font-semibold mb-1">Could not send to:</p>
              <ul className="space-y-0.5">
                {sendResults.filter((r) => r.status === "failed").map((r, i) => {
                  const emp = employees.find((e) => e.id === r.employeeId);
                  return <li key={i}>{emp?.name || `#${r.employeeId}`} — {r.reason}</li>;
                })}
              </ul>
            </div>
          )}
          <div className="flex justify-end border-t border-[#E5E0D9] dark:border-[#38312D] pt-6">
            <button type="button" onClick={onClose} className="bg-[#19C58A] rounded-[12px] px-5 py-2.5 text-[13px] font-bold text-white transition-all duration-200 hover:bg-[#15B07A] shadow-[0_2px_8px_rgba(25,197,138,0.3)]">
              Done
            </button>
          </div>
        </>
      )}
    </div>
  );
}
