import { useEffect, useState } from "react";
import { Percent, CheckCircle2, AlertTriangle } from "lucide-react";
import { listFrancePASRates, ingestFrancePASRate } from "../../../../service/superAdminService";
import { getEmployees } from "../../../../service/payrollService";
import { describeLoadError } from "../../../../service/errorClassification";
import { PAS_RATE_STATUS_CHIP } from "./franceOverviewSummaries";

const SOURCES = ["CRM", "NEUTRAL_GRID"];

// PAS (prélèvement à la source) rate intake (FR-008/FR-010). PERSONALIZED
// rows carry the DGFiP CRM percentage with authority provenance; NEUTRAL
// rows carry no percentage (the engine resolves the statutory neutral grid
// from the payroll date). A replacement with correctionOfId supersedes the
// prior ACTIVE row (status → STALE, never deleted), preserving lineage.
export default function FrancePASRatesTab({ organizationId }) {
  const [state, setState] = useState({ loading: true, rates: [], employees: null, error: null });
  const [form, setForm] = useState({
    employeeId: "", rateType: "PERSONALIZED", ratePct: "", dgfipRateId: "",
    source: "CRM", receivedDate: new Date().toISOString().slice(0, 10), effectiveFrom: "", correctionOfId: "",
  });
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState(null);

  function loadRates() {
    if (!organizationId) {
      setState((s) => ({ ...s, loading: false, rates: [] }));
      return;
    }
    setState((s) => ({ ...s, loading: true }));
    listFrancePASRates({ organizationId })
      .then((rates) => setState((s) => ({ ...s, loading: false, rates: Array.isArray(rates) ? rates : [], error: null })))
      .catch((err) => setState((s) => ({ ...s, loading: false, error: describeLoadError(err) })));
  }

  useEffect(() => {
    loadRates();
    // Best-effort employee list for the picker — /payroll/employees is an
    // org-operator endpoint, so on the Super Admin canvas this may 403; we
    // fall back to a manual employeeId input rather than block the tab.
    if (organizationId) {
      Promise.all([getEmployees({ limit: 500, country: "FR" }), getEmployees({ limit: 500 })])
        .then(([fr, all]) => {
          const source = Array.isArray(fr) ? fr : fr?.data || fr?.employees || [];
          const allList = Array.isArray(all) ? all : all?.data || all?.employees || [];
          const picked = source.length ? source : allList.filter((e) => e.countryCode === "FR");
          setState((s) => ({ ...s, employees: picked.length ? picked : null }));
        })
        .catch(() => setState((s) => ({ ...s, employees: null })));
    }
  }, [organizationId]);

  function setField(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  }

  async function ingest() {
    setSaving(true);
    setSaveError(null);
    const isNeutral = form.rateType === "NEUTRAL";
    const payload = {
      employeeId: Number(form.employeeId),
      rateType: form.rateType,
      ratePct: isNeutral ? null : form.ratePct === "" ? null : Number(form.ratePct),
      dgfipRateId: form.dgfipRateId || null,
      source: form.source,
      receivedDate: form.receivedDate || null,
      effectiveFrom: form.effectiveFrom,
      correctionOfId: form.correctionOfId === "" ? null : Number(form.correctionOfId),
    };
    try {
      await ingestFrancePASRate(payload, { organizationId });
      setForm((f) => ({ ...f, correctionOfId: "", dgfipRateId: "" }));
      setSaved(true);
      loadRates();
    } catch (err) {
      setSaveError(describeLoadError(err));
    } finally {
      setSaving(false);
    }
  }

  if (!organizationId) {
    return <p className="py-10 text-sm text-foreground-muted">Select an organization to manage its PAS rates.</p>;
  }

  const activeRates = state.rates.filter((r) => r.status === "ACTIVE");
  const activeIds = new Set(activeRates.map((r) => r.employeeId));
  const latestOf = (employeeId) =>
    state.rates.filter((r) => r.employeeId === employeeId).sort((a, b) => String(a.effectiveFrom).localeCompare(String(b.effectiveFrom))).slice(-1)[0];

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Percent size={16} className="text-primary" />
        <h2 className="text-sm font-bold text-foreground">PAS rates (prélèvement à la source)</h2>
      </div>

      <div className="rounded-lg border border-border bg-surface p-4">
        <p className="text-xs font-bold text-foreground mb-2">Ingest a rate (DGFiP CRM supply / neutral grid)</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Employee *</span>
            {state.employees ? (
              <select
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.employeeId}
                onChange={(e) => setField("employeeId", e.target.value)}
              >
                <option value="">Select France employee…</option>
                {state.employees.map((e) => (
                  <option
                    key={e.id}
                    value={e.id}
                    className={activeIds.has(e.id) ? "" : "text-warning"}
                  >
                    {e.name} ({e.employeeCode}){activeIds.has(e.id) ? "" : ` — no active rate (${latestOf(e.id)?.status || "none"})`}
                  </option>
                ))}
              </select>
            ) : (
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                placeholder="PayrollEmployee id (France employee)"
                value={form.employeeId}
                inputMode="numeric"
                onChange={(e) => setField("employeeId", e.target.value)}
              />
            )}
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Rate type</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.rateType}
              onChange={(e) => setField("rateType", e.target.value)}
            >
              <option value="PERSONALIZED">PERSONALIZED (DGFiP CRM %)</option>
              <option value="NEUTRAL">NEUTRAL (statutory grid)</option>
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Effective from *</span>
            <input
              type="date"
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.effectiveFrom}
              onChange={(e) => setField("effectiveFrom", e.target.value)}
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Rate % (PERSONALIZED only)</span>
            <input
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.ratePct}
              inputMode="decimal"
              disabled={form.rateType === "NEUTRAL"}
              onChange={(e) => setField("ratePct", e.target.value)}
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">DGFiP CRM rate id</span>
            <input
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.dgfipRateId}
              onChange={(e) => setField("dgfipRateId", e.target.value)}
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Source</span>
            <select
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.source}
              onChange={(e) => setField("source", e.target.value)}
            >
              {SOURCES.map((s) => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Received date</span>
            <input
              type="date"
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              value={form.receivedDate}
              onChange={(e) => setField("receivedDate", e.target.value)}
            />
          </label>
          <label className="block">
            <span className="text-xs font-semibold text-foreground-muted">Replaces rate id (correction lineage)</span>
            <input
              className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
              placeholder="FrancePASRate id being corrected"
              value={form.correctionOfId}
              inputMode="numeric"
              onChange={(e) => setField("correctionOfId", e.target.value)}
            />
          </label>
        </div>
        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={ingest}
            disabled={saving || !form.employeeId || !form.effectiveFrom}
            className="rounded-md bg-primary px-3.5 py-1.5 text-xs font-bold text-white disabled:opacity-40"
          >
            {saving ? "Ingesting…" : "Ingest PAS rate"}
          </button>
          {saved && (
            <span className="inline-flex items-center gap-1 text-xs font-semibold text-green-600">
              <CheckCircle2 size={13} /> Ingested
            </span>
          )}
          {saveError && (
            <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-600">
              <AlertTriangle size={13} /> {saveError}
            </span>
          )}
        </div>
        <p className="mt-2 text-[11px] text-foreground-disabled">
          PERSONALIZED requires the authority percentage; NEUTRAL forbids one (ratePct must stay null — the engine resolves the
          grid from the payroll date). A replacement supersedes the active row to STALE; history is never overwritten.
        </p>
      </div>

      <div className="rounded-lg border border-border bg-surface p-4">
        <p className="text-xs font-bold text-foreground mb-2">
          Rate ledger ({state.rates.length} — {activeRates.length} active)
        </p>
        {state.rates.length ? (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-foreground-muted">
                <th className="py-1 pr-3 font-semibold">Employee</th>
                <th className="py-1 pr-3 font-semibold">Type</th>
                <th className="py-1 pr-3 font-semibold">Rate</th>
                <th className="py-1 pr-3 font-semibold">Effective</th>
                <th className="py-1 pr-3 font-semibold">Source</th>
                <th className="py-1 pr-3 font-semibold">Corrects</th>
                <th className="py-1 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {state.rates.map((r) => (
                <tr key={r.id} className="border-t border-border">
                  <td className="py-1.5 pr-3">#{r.employeeId}</td>
                  <td className="py-1.5 pr-3">{r.rateType}</td>
                  <td className="py-1.5 pr-3">{r.ratePct != null ? `${r.ratePct}%` : "grid"}</td>
                  <td className="py-1.5 pr-3">{r.effectiveFrom} → {r.effectiveTo || "open"}</td>
                  <td className="py-1.5 pr-3">{r.source}{r.dgfipRateId ? ` · ${r.dgfipRateId}` : ""}</td>
                  <td className="py-1.5 pr-3">{r.correctionOfId ? `#${r.correctionOfId}` : "—"}</td>
                  <td className="py-1.5">
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${PAS_RATE_STATUS_CHIP[r.status] || "bg-surface-muted text-foreground-muted"}`}>
                      {r.status}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-xs text-foreground-muted">No PAS rates ingested yet.</p>
        )}
      </div>
    </div>
  );
}