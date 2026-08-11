import React, { useEffect, useState, useCallback } from "react";
import { Plus, Pencil, Trash2, RefreshCw, Landmark } from "lucide-react";

import { apiFetch } from "../api/client";
import { useToast } from "../context/ToastContext";
import StatutoryRateModal from "../components/StatutoryRateModal";
import ConfirmDialog from "../components/ConfirmDialog";
import StatusPill from "../components/StatusPill";

export default function StatutoryRatesPage() {
  const { addToast } = useToast();
  const [rates, setRates] = useState([]);
  const [country, setCountry] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [modal, setModal] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError("");
    apiFetch("/api/super-admin/statutory-rates", { params: { country } })
      .then((data) => setRates(data.rates))
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }, [country]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave(payload) {
    setBusy(true);
    try {
      if (modal && modal !== "new") {
        await apiFetch(`/api/super-admin/statutory-rates/${modal.id}`, {
          method: "PUT",
          body: payload,
        });
        addToast?.("Statutory rate updated.");
      } else {
        await apiFetch("/api/super-admin/statutory-rates", {
          method: "POST",
          body: payload,
        });
        addToast?.("Statutory rate created.");
      }
      setModal(null);
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    try {
      await apiFetch(`/api/super-admin/statutory-rates/${deleting.id}`, {
        method: "DELETE",
      });
      addToast?.("Statutory rate deleted.");
      setDeleting(null);
      load();
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div>
      <div className="flex flex-wrap items-center justify-between gap-3 mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Statutory Rates</h1>
        <div className="flex items-center gap-2">
          <input
            value={country}
            onChange={(e) => setCountry(e.target.value)}
            placeholder="Filter by country (IN)…"
            className="rounded-lg border border-slate-300 px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
          />
          <button
            onClick={load}
            disabled={loading}
            className="flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50"
          >
            <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
            Refresh
          </button>
          <button
            onClick={() => setModal("new")}
            className="flex items-center gap-2 rounded-lg bg-orange-500 px-3 py-2 text-sm font-medium text-white hover:bg-orange-600"
          >
            <Plus size={16} />
            Add Rate
          </button>
        </div>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-600">
          {error}
        </p>
      )}

      <div className="bg-white rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500">
            <tr>
              <th className="px-4 py-3">Country</th>
              <th className="px-4 py-3">Key</th>
              <th className="px-4 py-3">Label</th>
              <th className="px-4 py-3">Employee</th>
              <th className="px-4 py-3">Employer</th>
              <th className="px-4 py-3">Total</th>
              <th className="px-4 py-3">Status</th>
              <th className="px-4 py-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {rates.map((r) => (
              <tr key={r.id} className="border-t border-slate-100 hover:bg-slate-50/60 transition-colors">
                <td className="px-4 py-3 text-slate-500">{r.jurisdiction_country}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-600">{r.component_key}</td>
                <td className="px-4 py-3 font-medium text-slate-800">{r.label}</td>
                <td className="px-4 py-3 text-slate-600">{r.employee_share || "—"}</td>
                <td className="px-4 py-3 text-slate-600">{r.employer_share || "—"}</td>
                <td className="px-4 py-3 text-slate-600">{r.total || "—"}</td>
                <td className="px-4 py-3">
                  <StatusPill status={r.is_active ? "active" : "inactive"} />
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setModal(r)}
                      title="Edit rate"
                      className="rounded-lg bg-slate-100 p-1.5 text-slate-600 hover:bg-slate-200"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => setDeleting(r)}
                      title="Delete rate"
                      className="rounded-lg bg-red-50 p-1.5 text-red-600 hover:bg-red-100"
                    >
                      <Trash2 size={14} />
                    </button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && rates.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <Landmark size={28} className="text-slate-300" />
            <p className="text-sm text-slate-400">
              {country ? `No statutory rates found for "${country}".` : "No statutory rates found."}
            </p>
          </div>
        )}
      </div>

      {modal && (
        <StatutoryRateModal
          rate={modal === "new" ? null : modal}
          busy={busy}
          onSave={handleSave}
          onClose={() => setModal(null)}
        />
      )}
      {deleting && (
        <ConfirmDialog
          title="Delete Statutory Rate"
          message={`Delete "${deleting.label}" (${deleting.jurisdiction_country}/${deleting.component_key})? This cannot be undone.`}
          busy={busy}
          onConfirm={handleDelete}
          onClose={() => setDeleting(null)}
        />
      )}
    </div>
  );
}
