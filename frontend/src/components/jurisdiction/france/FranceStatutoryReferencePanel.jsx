import { useCallback, useEffect, useMemo, useState } from "react";
import { BookOpen, Pencil, Plus, AlertTriangle, Lock, DownloadCloud } from "lucide-react";
import Modal from "../../Modal";
import {
  getCanonicalContributionRates, getEngineFallbackDefaults, upsertCanonicalContributionRate,
  loadFranceStatutoryDefaults,
} from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";
import { useToast } from "../../../context/ToastContext";
import { inputClass } from "../constants";
import { FR_PACK_CATALOG, FR_PACK_CATEGORIES } from "./franceStatutoryConfig";

// France statutory values as PACK DATA (ZP-FR-ENG-001 FR-003). Every row
// engine/countries/france.py reads — rates AND the PASS/SMIC/RGDU/CSG/PAS
// parameters — lives in the selected France JurisdictionPack; the engine
// blocks on any mandatory key the pack lacks (FR-027), so the published
// engine default is shown only for comparison. Rows are editable while the
// pack is not yet live (Draft / In Review / QA / Approved — the backend
// enforces the same list and resets an approval on edit); an Active pack
// is changed through a new pack version.
const EDITABLE_STATUSES = ["Draft", "In Review", "QA", "Approved"];

function valueOf(row, kind) {
  if (!row) return null;
  if (kind === "ee") return row.employeeRatePct;
  if (kind === "er") return row.employerRatePct;
  return row.flatAmount;
}

function formatValue(value, kind) {
  if (value === null || value === undefined || value === "") return "—";
  return kind === "amount" ? String(value) : `${value}%`;
}

function dateWindow(row) {
  if (!row?.effectiveFrom && !row?.effectiveTo) return "whole pack";
  return `${row.effectiveFrom || "…"} → ${row.effectiveTo || "open"}`;
}

export default function FranceStatutoryReferencePanel({ pack, onReload }) {
  const { addToast } = useToast() || {};
  const [rows, setRows] = useState([]);
  const [defaults, setDefaults] = useState({});
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState(null);
  const [editing, setEditing] = useState(null); // { row, entry, value, reason }
  const [saving, setSaving] = useState(false);
  const [loadingDefaults, setLoadingDefaults] = useState(null); // null | { saving, error }

  const editable = Boolean(pack) && EDITABLE_STATUSES.includes(pack.status);

  const load = useCallback(() => {
    if (!pack) return;
    setLoading(true);
    setError(null);
    Promise.all([
      getCanonicalContributionRates({ jurisdictionPackId: pack.id }),
      getEngineFallbackDefaults().catch(() => null),
    ])
      .then(([packRows, fallback]) => {
        setRows(Array.isArray(packRows) ? packRows : []);
        const byKey = {};
        (fallback?.engineConstants || [])
          .filter((c) => c.country === "FR")
          .forEach((c) => { (byKey[c.resolverKey] = byKey[c.resolverKey] || []).push(c.value); });
        setDefaults(byKey);
      })
      .catch((err) => setError(describeLoadError(err)))
      .finally(() => setLoading(false));
  }, [pack]);

  useEffect(() => {
    load(); // eslint-disable-line react-hooks/set-state-in-effect
  }, [load]);

  const rowsByKey = useMemo(() => {
    const map = {};
    rows.forEach((r) => { (map[r.componentKey] = map[r.componentKey] || []).push(r); });
    Object.values(map).forEach((list) => list.sort((a, b) => String(a.effectiveFrom || "").localeCompare(String(b.effectiveFrom || ""))));
    return map;
  }, [rows]);

  const missing = FR_PACK_CATALOG.filter((e) => !rowsByKey[e.key]);
  const otherRows = rows.filter((r) => !FR_PACK_CATALOG.some((e) => e.key === r.componentKey));

  async function save() {
    const { row, entry, value, reason } = editing;
    if (value === "" || Number.isNaN(Number(value)) || Number(value) < 0) {
      addToast?.("Enter a non-negative number.", "error");
      return;
    }
    if (entry.kind !== "amount" && Number(value) > 100) {
      addToast?.("A percentage must be between 0 and 100.", "error");
      return;
    }
    setSaving(true);
    try {
      await upsertCanonicalContributionRate({
        id: row?.id,
        jurisdictionPackId: pack.id,
        jurisdictionCountry: "FR",
        jurisdictionState: row?.jurisdictionState ?? null,
        jurisdictionLocality: row?.jurisdictionLocality ?? null,
        taxRegime: row?.taxRegime ?? null,
        filingStatus: row?.filingStatus ?? null,
        componentKey: entry.key,
        label: row?.label || entry.label,
        employeeSharePct: entry.kind === "ee" ? value : null,
        employerSharePct: entry.kind === "er" ? value : null,
        flatAmount: entry.kind === "amount" ? value : null,
        textValue: row?.textValue ?? null,
        sortOrder: row?.sortOrder ?? 0,
        reason: reason || null,
      });
      addToast?.(`${entry.label} saved.`, "success");
      setEditing(null);
      load();
      onReload?.();
    } catch (err) {
      addToast?.(err.message || "Failed to save.", "error");
    } finally {
      setSaving(false);
    }
  }

  async function loadDefaults() {
    setLoadingDefaults({ saving: true, error: "" });
    try {
      const res = await loadFranceStatutoryDefaults(pack.id);
      addToast?.(res?.message || "Statutory defaults loaded.", "success");
      setLoadingDefaults(null);
      load();
      onReload?.();
    } catch (err) {
      setLoadingDefaults({ saving: false, error: loadErrorText(describeLoadError(err)) });
    }
  }

  const pendingG1Missing = missing.filter((e) => e.pendingG1);

  if (!pack) {
    return <p className="py-8 text-center text-xs text-foreground-disabled">Select a France pack to see its statutory values.</p>;
  }

  return (
    <div className="space-y-4">
      <div>
        <h3 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
          <BookOpen size={15} className="text-primary" /> Statutory values — {pack.packId} v{pack.version}
        </h3>
        <p className="mt-0.5 text-xs text-foreground-muted">
          Every ceiling, SMIC value, rate and RGDU/PAS parameter the France engine reads from this pack. A missing
          mandatory value blocks France payroll — the engine never falls back to its built-in default.
          Percentages are entered as percent (6.90 = 6.90%; RGDU Tdelta 37.81 = 0.3781).
        </p>
        {!editable && (
          <p className="mt-2 flex items-center gap-1.5 rounded-lg border border-border bg-surface-muted px-3 py-2 text-[11px] text-foreground-muted">
            <Lock size={12} /> This pack is {pack.status} — its values are frozen. Create a new version to change them.
          </p>
        )}
      </div>

      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading statutory values…</p>
      ) : error ? (
        <p className="py-8 text-center text-xs text-foreground-muted">{loadErrorText(error)}</p>
      ) : (
        <>
          {missing.length > 0 && (
            <div className="rounded-lg border border-warning/40 bg-warning-light px-3 py-2 text-xs text-foreground">
              <div className="flex flex-wrap items-center justify-between gap-2">
                <p className="flex items-center gap-1.5 font-semibold">
                  <AlertTriangle size={13} /> {missing.length} mandatory value{missing.length === 1 ? "" : "s"} missing — France payroll on this pack is blocked until added.
                </p>
                {editable && (
                  <button
                    onClick={() => setLoadingDefaults({ saving: false, error: "" })}
                    className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover"
                  >
                    <DownloadCloud size={13} /> Load 2026 statutory defaults ({missing.length} missing)
                  </button>
                )}
              </div>
            </div>
          )}

          {FR_PACK_CATEGORIES.map((cat) => {
            const entries = FR_PACK_CATALOG.filter((e) => e.category === cat.key);
            return (
              <div key={cat.key} className="overflow-x-auto rounded-xl border border-border bg-surface">
                <p className="border-b border-border bg-background px-3 py-2 text-xs font-bold text-foreground">{cat.label}</p>
                <table className="w-full text-xs">
                  <thead className="text-left text-foreground-muted">
                    <tr>
                      <th className="px-3 py-2">Parameter</th>
                      <th className="px-3 py-2">Pack value</th>
                      <th className="px-3 py-2">Applies</th>
                      <th className="px-3 py-2">Engine default</th>
                      <th className="px-3 py-2" />
                    </tr>
                  </thead>
                  <tbody>
                    {entries.flatMap((entry) => {
                      const packRows = rowsByKey[entry.key] || [null];
                      return packRows.map((row, i) => {
                        const value = valueOf(row, entry.kind);
                        const engineDefaults = defaults[entry.key] || [];
                        const differs = row && engineDefaults.length > 0
                          && !engineDefaults.some((d) => Number(d) === Number(value)
                            || (entry.kind === "er" && entry.key.startsWith("fr_rgdu_") && Number(d) * 100 === Number(value)));
                        return (
                          <tr key={`${entry.key}-${row?.id ?? i}`} className="border-t border-border-light align-top">
                            <td className="px-3 py-2">
                              <p className="font-semibold text-foreground">{row?.label || entry.label}</p>
                              <p className="font-mono text-[10px] text-foreground-disabled">
                                {entry.key}{entry.pendingG1 && " · pending G1 sign-off"}
                              </p>
                            </td>
                            <td className="px-3 py-2 font-mono text-sm font-bold tabular-nums">
                              {row ? formatValue(value, entry.kind) : <span className="text-error">missing</span>}
                            </td>
                            <td className="px-3 py-2 text-[11px] text-foreground-muted">{row ? dateWindow(row) : "—"}</td>
                            <td className={`px-3 py-2 font-mono text-[11px] ${differs ? "text-warning" : "text-foreground-disabled"}`}>
                              {engineDefaults.length ? engineDefaults.join(" / ") : "—"}
                            </td>
                            <td className="px-3 py-2 text-right">
                              {editable && (
                                <button
                                  onClick={() => setEditing({ row, entry, value: value ?? "", reason: "" })}
                                  className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground-secondary hover:bg-surface-muted"
                                >
                                  {row ? <><Pencil size={11} /> Edit</> : <><Plus size={11} /> Add</>}
                                </button>
                              )}
                            </td>
                          </tr>
                        );
                      });
                    })}
                  </tbody>
                </table>
              </div>
            );
          })}

          {otherRows.length > 0 && (
            <p className="text-[11px] text-foreground-muted">
              {otherRows.length} additional row(s) in this pack are not read by the France engine
              ({otherRows.map((r) => r.componentKey).join(", ")}) — manage them in Contribution Rates.
            </p>
          )}
        </>
      )}

      {loadingDefaults && (
        <Modal title="Load France 2026 statutory defaults" onClose={() => setLoadingDefaults(null)}>
          <p className="text-xs text-foreground-muted">
            Adds the {missing.length} missing value{missing.length === 1 ? "" : "s"} to <b>{pack.packId} v{pack.version}</b> from the
            ZP-FR-ENG-001 2026 catalog (PASS/PMSS, SMIC Jan–May and from 1 June, social security, CSG/CRDS, Agirc-Arrco,
            employer levies, RGDU and PAS parameters). Values already in the pack are never changed, and every added row is audited.
            Each one stays editable afterwards.
          </p>
          {pendingG1Missing.length > 0 && (
            <p className="mt-3 rounded-lg border border-warning/40 bg-warning-light px-3 py-2 text-[11px] text-foreground">
              Pending G1 sign-off (added, but must be confirmed by a French payroll specialist before this pack goes Active):{" "}
              {pendingG1Missing.map((e) => e.label).join(", ")}.
            </p>
          )}
          {pack.approvedById && (
            <p className="mt-2 text-[11px] text-warning">This pack&apos;s current approval will be cleared — adding rows changes its content.</p>
          )}
          {loadingDefaults.error && <p className="mt-2 text-xs text-error">{loadingDefaults.error}</p>}
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setLoadingDefaults(null)} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={loadDefaults} disabled={loadingDefaults.saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
              {loadingDefaults.saving ? "Loading…" : "Load defaults"}
            </button>
          </div>
        </Modal>
      )}

      {editing && (
        <div className="rounded-xl border border-primary/40 bg-surface p-4 shadow-sm">
          <p className="text-xs font-bold text-foreground">
            {editing.row ? "Edit" : "Add"} — {editing.entry.label}
            {editing.row && editing.row.effectiveFrom && ` (${dateWindow(editing.row)})`}
          </p>
          <div className="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-3">
            <label className="text-[11px] font-semibold text-foreground-muted">
              Value {editing.entry.kind === "amount" ? "(amount)" : "(percent)"}
              <input className={inputClass} value={editing.value} autoFocus
                onChange={(e) => setEditing((s) => ({ ...s, value: e.target.value }))} />
            </label>
            <label className="text-[11px] font-semibold text-foreground-muted sm:col-span-2">
              Reason / source (audited)
              <input className={inputClass} value={editing.reason} placeholder="e.g. Urssaf 2026 barème, S1"
                onChange={(e) => setEditing((s) => ({ ...s, reason: e.target.value }))} />
            </label>
          </div>
          <div className="mt-3 flex justify-end gap-2">
            <button onClick={() => setEditing(null)} className="rounded-lg border border-border px-3 py-1.5 text-xs text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={save} disabled={saving} className="rounded-lg bg-primary px-3 py-1.5 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50">
              {saving ? "Saving…" : "Save"}
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
