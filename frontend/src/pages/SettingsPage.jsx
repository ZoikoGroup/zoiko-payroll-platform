import React, { useEffect, useState } from "react";
import { Save, RefreshCw, Settings as SettingsIcon } from "lucide-react";

import { apiFetch } from "../api/client";
import { useToast } from "../context/ToastContext";

export default function SettingsPage() {
  const { addToast } = useToast();
  const [settings, setSettings] = useState([]);
  const [edits, setEdits] = useState({});
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const [busyKey, setBusyKey] = useState(null);

  function load() {
    setLoading(true);
    setError("");
    apiFetch("/api/super-admin/settings")
      .then((data) => {
        setSettings(data);
        setEdits(Object.fromEntries(data.map((s) => [s.key, s.value || ""])));
      })
      .catch((err) => setError(err.message))
      .finally(() => setLoading(false));
  }

  useEffect(load, []);

  async function save(key) {
    setBusyKey(key);
    try {
      const res = await apiFetch(`/api/super-admin/settings/${key}`, {
        method: "PUT",
        body: { value: edits[key] },
      });
      setSettings((list) => list.map((s) => (s.key === key ? res : s)));
      addToast?.(`Setting "${key}" saved.`);
    } catch (err) {
      addToast?.(err.message, "error");
    } finally {
      setBusyKey(null);
    }
  }

  return (
    <div>
      <div className="flex items-center justify-between mb-6">
        <h1 className="text-2xl font-bold text-slate-900">Platform Settings</h1>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-slate-300 px-3 py-2 text-sm text-slate-600 hover:bg-slate-100 disabled:opacity-50"
        >
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
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
              <th className="px-4 py-3">Key</th>
              <th className="px-4 py-3">Description</th>
              <th className="px-4 py-3">Value</th>
              <th className="px-4 py-3">Public</th>
              <th className="px-4 py-3"></th>
            </tr>
          </thead>
          <tbody>
            {settings.map((s) => (
              <tr key={s.key} className="border-t border-slate-100 hover:bg-slate-50/60 transition-colors">
                <td className="px-4 py-3 font-mono text-xs text-slate-700">{s.key}</td>
                <td className="px-4 py-3 text-slate-500">{s.description || "—"}</td>
                <td className="px-4 py-3">
                  <input
                    value={edits[s.key] ?? ""}
                    onChange={(e) => setEdits((d) => ({ ...d, [s.key]: e.target.value }))}
                    className="w-64 rounded-lg border border-slate-300 px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-orange-500"
                  />
                </td>
                <td className="px-4 py-3 text-slate-500">{s.is_public ? "Yes" : "No"}</td>
                <td className="px-4 py-3">
                  <button
                    disabled={busyKey === s.key}
                    onClick={() => save(s.key)}
                    className="flex items-center gap-1 rounded-lg bg-slate-100 px-2.5 py-1 text-xs font-medium text-slate-600 hover:bg-slate-200 disabled:opacity-40"
                  >
                    <Save size={12} />
                    Save
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!loading && settings.length === 0 && (
          <div className="flex flex-col items-center justify-center gap-2 px-4 py-14 text-center">
            <SettingsIcon size={28} className="text-slate-300" />
            <p className="text-sm text-slate-400">No settings configured.</p>
          </div>
        )}
      </div>
    </div>
  );
}
