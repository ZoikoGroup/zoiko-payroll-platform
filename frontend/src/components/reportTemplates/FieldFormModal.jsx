import { useState, useEffect } from "react";
import Modal from "../Modal";
import { useToast } from "../../context/ToastContext";
import { upsertReportTemplateField } from "../../service/superAdminService";
import { inputClass, labelClass } from "../jurisdiction/constants";
import { FIELD_TYPE_OPTIONS } from "./constants";

// The data-mapping dropdown is populated ONLY from `availableDataFields`
// (fetched by the parent from GET .../available-data-fields, a real,
// backend-owned enumeration of PayslipItem/PayrollRun/EmployerProfile
// columns) — this component never lets a Super Admin free-type a source
// column, per the product spec's "never a fabricated statutory value"
// requirement. Selecting an entry fills dataSourceKind/sourceColumn from
// it directly; label/fieldType stay editable since the same underlying
// data field can be displayed/formatted differently per report.
export default function FieldFormModal({ component, field, availableDataFields, onClose, onSaved }) {
  const { addToast } = useToast() || {};
  const isEdit = Boolean(field);
  const initialDataFieldKey = field
    ? availableDataFields.find((d) => d.dataSourceKind === field.dataSourceKind && d.sourceColumn === field.sourceColumn)?.key || ""
    : "";
  const [form, setForm] = useState({
    dataFieldKey: initialDataFieldKey,
    fieldKey: field?.fieldKey || "",
    label: field?.label || "",
    fieldType: field?.fieldType || "currency",
    aggregation: field?.aggregation || "",
    enumValues: (field?.enumValues || []).join(", "),
    formatHint: field?.formatHint || "",
    isRequired: field?.isRequired || false,
    sortOrder: field?.sortOrder ?? 0,
  });
  const [saving, setSaving] = useState(false);

  const selectedDataField = availableDataFields.find((d) => d.key === form.dataFieldKey);

  // Picking a data field seeds a sensible fieldKey/label/fieldType if the
  // admin hasn't already typed their own — never overwrites a value
  // they've already customized.
  useEffect(() => {
    if (!selectedDataField || isEdit) return;
    setForm((f) => ({
      ...f,
      fieldKey: f.fieldKey || selectedDataField.sourceColumn,
      label: f.label || selectedDataField.label,
      fieldType: f.fieldType && f.fieldType !== "currency" ? f.fieldType : selectedDataField.fieldType,
    }));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [form.dataFieldKey]);

  const set = (key) => (e) => {
    const value = e.target.type === "checkbox" ? e.target.checked : e.target.value;
    setForm((f) => ({ ...f, [key]: value }));
  };

  async function save() {
    if (!selectedDataField) {
      addToast?.("Select a data field to map this field to.", "error");
      return;
    }
    if (!form.fieldKey.trim() || !form.label.trim()) {
      addToast?.("Field Key and Label are required.", "error");
      return;
    }
    if (form.aggregation && !selectedDataField.aggregatable) {
      addToast?.(`${selectedDataField.label} cannot be aggregated.`, "error");
      return;
    }
    setSaving(true);
    try {
      const saved = await upsertReportTemplateField(component.id, {
        id: field?.id,
        fieldKey: form.fieldKey.trim(),
        label: form.label.trim(),
        fieldType: form.fieldType,
        dataSourceKind: selectedDataField.dataSourceKind,
        sourceColumn: selectedDataField.sourceColumn,
        aggregation: form.aggregation || null,
        enumValues: form.fieldType === "enum"
          ? form.enumValues.split(",").map((v) => v.trim()).filter(Boolean)
          : null,
        formatHint: form.formatHint || null,
        isRequired: form.isRequired,
        sortOrder: Number(form.sortOrder) || 0,
      });
      addToast?.("Field saved.", "success");
      onSaved(saved);
    } catch (err) {
      addToast?.(err.message || "Failed to save field.", "error");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal title={isEdit ? "Edit Field" : "Add Field"} onClose={onClose} maxWidth="max-w-xl">
      <div className="grid grid-cols-2 gap-3">
        <div className="col-span-2">
          <label className={labelClass}>Data Field</label>
          <select className={inputClass} value={form.dataFieldKey} onChange={set("dataFieldKey")}>
            <option value="">Select a real data field…</option>
            {availableDataFields.map((d) => (
              <option key={d.key} value={d.key}>{d.label} ({d.dataSourceKind === "PAYSLIP_ITEM" ? "Payslip" : d.dataSourceKind === "PAYROLL_RUN" ? "Payroll Run" : "Employer"})</option>
            ))}
          </select>
        </div>
        <div>
          <label className={labelClass}>Field Key</label>
          <input className={inputClass} value={form.fieldKey} onChange={set("fieldKey")} />
        </div>
        <div>
          <label className={labelClass}>Label</label>
          <input className={inputClass} value={form.label} onChange={set("label")} />
        </div>
        <div>
          <label className={labelClass}>Input Type</label>
          <select className={inputClass} value={form.fieldType} onChange={set("fieldType")}>
            {FIELD_TYPE_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>
        <div>
          <label className={labelClass}>Aggregation</label>
          <select className={inputClass} value={form.aggregation} onChange={set("aggregation")} disabled={!selectedDataField?.aggregatable}>
            <option value="">None (per-employee value)</option>
            <option value="SUM_RUN">Sum for this period</option>
            <option value="SUM_YTD">Year-to-date (per employee)</option>
          </select>
        </div>
        {form.fieldType === "enum" && (
          <div className="col-span-2">
            <label className={labelClass}>Enum Options (comma-separated)</label>
            <input className={inputClass} value={form.enumValues} onChange={set("enumValues")} placeholder="Old, New" />
          </div>
        )}
        <div>
          <label className={labelClass}>Format Hint (optional)</label>
          <input className={inputClass} value={form.formatHint} onChange={set("formatHint")} placeholder="e.g. 2dp" />
        </div>
        <div>
          <label className={labelClass}>Sort Order</label>
          <input type="number" className={inputClass} value={form.sortOrder} onChange={set("sortOrder")} />
        </div>
        <div className="col-span-2 flex items-center gap-2">
          <input type="checkbox" id="field-required" checked={form.isRequired} onChange={set("isRequired")} className="h-4 w-4 rounded border-border-strong" />
          <label htmlFor="field-required" className="text-sm text-foreground-secondary">Required on the generated report</label>
        </div>
      </div>
      <div className="mt-5 flex justify-end gap-2">
        <button onClick={onClose} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
        <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">{saving ? "Saving…" : "Save Field"}</button>
      </div>
    </Modal>
  );
}
