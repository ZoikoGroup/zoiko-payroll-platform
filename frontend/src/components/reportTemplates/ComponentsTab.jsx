import { useState } from "react";
import { Plus, Trash2, Pencil } from "lucide-react";
import ConfirmDialog from "../ConfirmDialog";
import { useToast } from "../../context/ToastContext";
import {
  upsertReportTemplateComponent, deleteReportTemplateComponent, deleteReportTemplateField,
} from "../../service/superAdminService";
import { inputClass } from "../jurisdiction/constants";
import FieldFormModal from "./FieldFormModal";

// Select Jurisdiction -> Select Report Template -> load supported
// components -> display actual components -> configure selected
// component -> display only relevant fields. `availableComponents` is
// fetched by the parent from the backend's available-components endpoint
// (keyed by this template's report type) — the "Add Component" dropdown
// below only ever offers entries from that list, filtered to ones not
// already added, never a generic unrelated option.
export default function ComponentsTab({ template, components, availableComponents, availableDataFields, editable, onChanged }) {
  const { addToast } = useToast() || {};
  const [addingKey, setAddingKey] = useState("");
  const [adding, setAdding] = useState(false);
  const [fieldModal, setFieldModal] = useState(null); // { component, field? } | null
  const [deletingComponent, setDeletingComponent] = useState(null);
  const [deletingField, setDeletingField] = useState(null);

  const addedKeys = new Set(components.map((c) => c.componentKey));
  const addableOptions = availableComponents.filter((c) => !addedKeys.has(c.key));

  async function handleAddComponent() {
    const option = availableComponents.find((c) => c.key === addingKey);
    if (!option) return;
    setAdding(true);
    try {
      await upsertReportTemplateComponent(template.id, { componentKey: option.key, label: option.label, sortOrder: components.length });
      addToast?.("Component added.", "success");
      setAddingKey("");
      onChanged();
    } catch (err) {
      addToast?.(err.message || "Failed to add component.", "error");
    } finally {
      setAdding(false);
    }
  }

  async function handleDeleteComponent() {
    try {
      await deleteReportTemplateComponent(deletingComponent.id);
      addToast?.("Component deleted.", "success");
    } catch (err) {
      addToast?.(err.message || "Failed to delete component.", "error");
    } finally {
      setDeletingComponent(null);
      onChanged();
    }
  }

  async function handleDeleteField() {
    try {
      await deleteReportTemplateField(deletingField.id);
      addToast?.("Field deleted.", "success");
    } catch (err) {
      addToast?.(err.message || "Failed to delete field.", "error");
    } finally {
      setDeletingField(null);
      onChanged();
    }
  }

  return (
    <div className="space-y-4">
      {editable && (
        <div className="flex items-center gap-2">
          <select className={inputClass + " w-auto min-w-[220px]"} value={addingKey} onChange={(e) => setAddingKey(e.target.value)}>
            <option value="">Add a component…</option>
            {addableOptions.map((c) => <option key={c.key} value={c.key}>{c.label}</option>)}
          </select>
          <button
            onClick={handleAddComponent} disabled={!addingKey || adding}
            className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
          >
            <Plus size={13} /> Add Component
          </button>
        </div>
      )}

      {components.length === 0 ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">No components configured yet.</p>
      ) : (
        components.map((component) => (
          <div key={component.id} className="rounded-lg border border-border-light p-3">
            <div className="mb-2 flex items-center justify-between">
              <p className="text-sm font-semibold text-foreground">{component.label}</p>
              {editable && (
                <div className="flex items-center gap-1.5">
                  <button
                    onClick={() => setFieldModal({ component })}
                    className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
                  >
                    <Plus size={12} /> Add Field
                  </button>
                  <button onClick={() => setDeletingComponent(component)} className="rounded-lg border border-border p-1.5 text-error hover:bg-error-light">
                    <Trash2 size={12} />
                  </button>
                </div>
              )}
            </div>
            {(component.fields || []).length === 0 ? (
              <p className="py-2 text-xs text-foreground-disabled">No fields configured for this component yet.</p>
            ) : (
              <div className="space-y-1">
                {component.fields.map((field) => (
                  <div key={field.id} className="flex items-center justify-between rounded-md bg-surface-muted px-2.5 py-1.5 text-xs">
                    <div className="flex items-center gap-2">
                      <span className="font-medium text-foreground">{field.label}</span>
                      <span className="text-foreground-disabled">{field.fieldType}</span>
                      <span className="text-foreground-disabled">·</span>
                      <span className="font-mono text-foreground-muted">{field.sourceColumn}{field.aggregation ? ` (${field.aggregation})` : ""}</span>
                    </div>
                    {editable && (
                      <div className="flex items-center gap-1">
                        <button onClick={() => setFieldModal({ component, field })} className="rounded p-1 text-foreground-muted hover:bg-surface hover:text-foreground">
                          <Pencil size={11} />
                        </button>
                        <button onClick={() => setDeletingField(field)} className="rounded p-1 text-error hover:bg-error-light">
                          <Trash2 size={11} />
                        </button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        ))
      )}

      {fieldModal && (
        <FieldFormModal
          component={fieldModal.component} field={fieldModal.field} availableDataFields={availableDataFields}
          onClose={() => setFieldModal(null)}
          onSaved={() => { setFieldModal(null); onChanged(); }}
        />
      )}
      {deletingComponent && (
        <ConfirmDialog
          title="Delete Component" message={`Delete "${deletingComponent.label}" and all of its fields? This cannot be undone.`}
          onConfirm={handleDeleteComponent} onClose={() => setDeletingComponent(null)}
        />
      )}
      {deletingField && (
        <ConfirmDialog
          title="Delete Field" message={`Delete the "${deletingField.label}" field? This cannot be undone.`}
          onConfirm={handleDeleteField} onClose={() => setDeletingField(null)}
        />
      )}
    </div>
  );
}
