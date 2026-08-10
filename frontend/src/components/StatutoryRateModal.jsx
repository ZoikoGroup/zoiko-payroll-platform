import React, { useState } from "react";
import { X } from "lucide-react";

const EMPTY = {
  jurisdiction_country: "IN",
  component_key: "",
  label: "",
  employee_share: "",
  employer_share: "",
  total: "",
  employee_rate_pct: "",
  employer_rate_pct: "",
  flat_amount: "",
  sort_order: 0,
  is_active: true,
};

function toForm(rate) {
  if (!rate) return EMPTY;
  return {
    jurisdiction_country: rate.jurisdiction_country,
    component_key: rate.component_key,
    label: rate.label,
    employee_share: rate.employee_share || "",
    employer_share: rate.employer_share || "",
    total: rate.total || "",
    employee_rate_pct: rate.employee_rate_pct ?? "",
    employer_rate_pct: rate.employer_rate_pct ?? "",
    flat_amount: rate.flat_amount ?? "",
    sort_order: rate.sort_order ?? 0,
    is_active: rate.is_active ?? true,
  };
}

function toPayload(form) {
  const num = (v) => (v === "" || v === null || v === undefined ? null : Number(v));
  return {
    jurisdiction_country: form.jurisdiction_country,
    component_key: form.component_key,
    label: form.label,
    employee_share: form.employee_share || "",
    employer_share: form.employer_share || "",
    total: form.total || "",
    employee_rate_pct: num(form.employee_rate_pct),
    employer_rate_pct: num(form.employer_rate_pct),
    flat_amount: num(form.flat_amount),
    sort_order: form.sort_order === "" ? 0 : Number(form.sort_order),
    is_active: form.is_active,
  };
}

const INPUT =
  "w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500";

export default function StatutoryRateModal({ rate, onSave, onClose, busy }) {
  const [form, setForm] = useState(toForm(rate));
  const set = (key) => (e) =>
    setForm((f) => ({ ...f, [key]: e.target.type === "checkbox" ? e.target.checked : e.target.value }));

  return (
    <div className="fixed inset-0 bg-black/40 flex items-center justify-center z-50">
      <div className="bg-white rounded-xl shadow-lg w-full max-w-lg p-6 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-lg font-semibold text-slate-900">
            {rate ? "Edit Statutory Rate" : "Add Statutory Rate"}
          </h3>
          <button onClick={onClose} className="text-slate-400 hover:text-slate-600">
            <X size={20} />
          </button>
        </div>

        <div className="grid grid-cols-2 gap-4">
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Country</span>
            <input className={INPUT} value={form.jurisdiction_country} onChange={set("jurisdiction_country")} />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Component Key *</span>
            <input className={INPUT} value={form.component_key} onChange={set("component_key")} placeholder="pf, esi, gratuity…" />
          </label>
          <label className="block col-span-2">
            <span className="text-xs font-medium text-slate-600">Label *</span>
            <input className={INPUT} value={form.label} onChange={set("label")} />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Employee Share</span>
            <input className={INPUT} value={form.employee_share} onChange={set("employee_share")} placeholder="12% of Basic" />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Employer Share</span>
            <input className={INPUT} value={form.employer_share} onChange={set("employer_share")} />
          </label>
          <label className="block col-span-2">
            <span className="text-xs font-medium text-slate-600">Total</span>
            <input className={INPUT} value={form.total} onChange={set("total")} />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Employee Rate (%)</span>
            <input className={INPUT} type="number" step="any" value={form.employee_rate_pct} onChange={set("employee_rate_pct")} />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Employer Rate (%)</span>
            <input className={INPUT} type="number" step="any" value={form.employer_rate_pct} onChange={set("employer_rate_pct")} />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Flat Amount</span>
            <input className={INPUT} type="number" step="any" value={form.flat_amount} onChange={set("flat_amount")} />
          </label>
          <label className="block">
            <span className="text-xs font-medium text-slate-600">Sort Order</span>
            <input className={INPUT} type="number" value={form.sort_order} onChange={set("sort_order")} />
          </label>
          <label className="col-span-2 flex items-center gap-2 text-sm text-slate-700">
            <input type="checkbox" checked={form.is_active} onChange={set("is_active")} />
            Active
          </label>
        </div>

        {form.component_key.trim() && form.label.trim() && form.jurisdiction_country.trim() && rate === null ? (
          <p className="mt-3 text-xs text-amber-600">
            Creating for {form.jurisdiction_country}/{form.component_key} — duplicates are rejected by the backend.
          </p>
        ) : null}

        <div className="mt-6 flex justify-end gap-3">
          <button
            onClick={onClose}
            disabled={busy}
            className="px-4 py-2 rounded-lg text-sm font-medium text-slate-700 bg-slate-100 hover:bg-slate-200 disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            onClick={() => onSave(toPayload(form))}
            disabled={busy || !form.component_key.trim() || !form.label.trim()}
            className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-orange-500 hover:bg-orange-600 disabled:opacity-50"
          >
            {busy ? "Saving…" : rate ? "Save Changes" : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
