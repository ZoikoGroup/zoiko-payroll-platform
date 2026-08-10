import React, { useEffect, useState, useCallback } from "react";
import { Plus, Pencil, Trash2, RefreshCw } from "lucide-react";

import { apiFetch } from "../api/client";
import StatutoryRateModal from "../components/StatutoryRateModal";
import ConfirmDialog from "../components/ConfirmDialog";

export default function StatutoryRatesPage() {
  const [rates, setRates] = useState([]);
  const [country, setCountry] = useState("");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [modal, setModal] = useState(null);
  const [deleting, setDeleting] = useState(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(() => {
    apiFetch("/api/super-admin/statutory-rates", { params: { country } })
      .then((data) => setRates(data.rates))
      .catch((err) => setError(err.message));
  }, [country]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleSave(payload) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      if (modal) {
        await apiFetch(`/api/super-admin/statutory-rates/${modal.id}`, {
          method: "PUT",
          body: payload,
        });
        setNotice("Statutory rate updated.");
      } else {
        await apiFetch("/api/super-admin/statutory-rates", {
          method: "POST",
          body: payload,
        });
        setNotice("Statutory rate created.");
      }
      setModal(null);
      load();
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  async function handleDelete() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await apiFetch(`/api/super-admin/statutory-rates/${deleting.id}`, {
        method: "DELETE",
      });
      setNotice("Statutory rate deleted.");
      setDeleting(null);
      load();
    } catch (err) {
      setError(err.message);
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
            className="flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100"
          >
            <RefreshCw size={15} />
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

      {error && <p className="mb-3 text-sm text-red-600">{error}</p>}
      {notice && <p className="mb-3 text-sm text-green-600">{notice}</p>}

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
              <tr key={r.id} className="border-t border-slate-100">
                <td className="px-4 py-3 text-slate-500">{r.jurisdiction_country}</td>
                <td className="px-4 py-3 font-mono text-xs text-slate-600">{r.component_key}</td>
                <td className="px-4 py-3 font-medium text-slate-800">{r.label}</td>
                <td className="px-4 py-3 text-slate-600">{r.employee_share || "—"}</td>
                <td className="px-4 py-3 text-slate-600">{r.employer_share || "—"}</td>
                <td className="px-4 py-3 text-slate-600">{r.total || "—"}</td>
                <td className="px-4 py-3">
                  <span
                    className={`inline-block rounded-full px-2 py-0.5 text-xs font-medium ${
                      r.is_active ? "bg-green-100 text-green-700" : "bg-red-100 text-red-700"
                    }`}
                  >
                    {r.is_active ? "Active" : "Inactive"}
                  </span>
                </td>
                <td className="px-4 py-3">
                  <div className="flex items-center gap-2">
                    <button
                      onClick={() => setModal(r)}
                      className="rounded-lg bg-slate-100 p-1.5 text-slate-600 hover:bg-slate-200"
                    >
                      <Pencil size={14} />
                    </button>
                    <button
                      onClick={() => setDeleting(r)}
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
        {rates.length === 0 && (
          <p className="px-4 py-6 text-sm text-slate-400">No statutory rates found.</p>
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
