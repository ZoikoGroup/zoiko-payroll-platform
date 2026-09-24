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
        <h1 className="text-2xl font-bold text-foreground">Platform Settings</h1>
        <button
          onClick={load}
          disabled={loading}
          className="flex items-center gap-2 rounded-lg border border-border px-3 py-2 text-sm text-foreground-secondary hover:bg-surface-muted disabled:opacity-50"
        >
          <RefreshCw size={15} className={loading ? "animate-spin" : ""} />
          Refresh
        </button>
      </div>

      {error && (
        <p className="mb-4 rounded-lg border border-error/30 bg-error-light px-4 py-3 text-sm text-error">
          {error}
        </p>
      )}

      <div className="bg-surface rounded-xl shadow-sm overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-background text-left text-xs text-foreground-muted">
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
              <tr key={s.key} className="border-t border-border-light hover:bg-surface-muted/60 transition-colors">
                <td className="px-4 py-3 font-mono text-xs text-foreground-secondary">{s.key}</td>
                <td className="px-4 py-3 text-foreground-muted">{s.description || "—"}</td>
                <td className="px-4 py-3">
                  <input
                    value={edits[s.key] ?? ""}
                    onChange={(e) => setEdits((d) => ({ ...d, [s.key]: e.target.value }))}
                    className="w-64 rounded-lg border border-border bg-surface text-foreground px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-focus-ring"
                  />
                </td>
                <td className="px-4 py-3 text-foreground-muted">{s.is_public ? "Yes" : "No"}</td>
                <td className="px-4 py-3">
                  <button
                    disabled={busyKey === s.key}
                    onClick={() => save(s.key)}
                    className="flex items-center gap-1 rounded-lg bg-surface-muted px-2.5 py-1 text-xs font-medium text-foreground-secondary hover:bg-border-light disabled:opacity-40"
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
            <SettingsIcon size={28} className="text-foreground-disabled" />
            <p className="text-sm text-foreground-disabled">No settings configured.</p>
          </div>
        )}
      </div>
    </div>
  );
}
