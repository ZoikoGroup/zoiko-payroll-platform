import { useEffect, useState } from "react";
import { Layers, CheckCircle2, AlertTriangle } from "lucide-react";
import { listFranceEstablishmentRatePacks, upsertFranceEstablishmentRatePack } from "../../../../service/superAdminService";
import { describeLoadError } from "../../../../service/errorClassification";
import { FNAL_CLASS_LABELS, CFP_CLASS_LABELS } from "./franceOverviewSummaries";

const FNAL_CLASSES = ["UNDER_50", "OVER_50"];
const CFP_CLASSES = ["UNDER_11", "OVER_11"];
const BLANK = {
  siret: "",
  communeInsee: "",
  workplaceLabel: "",
  atMpRatePct: "",
  atMpRiskCode: "",
  atMpEvidence: "",
  atMpSource: "",
  vmRatePct: "",
  vmThresholdApplies: false,
  vmSource: "",
  fnalClass: "UNDER_50",
  cfpClass: "UNDER_11",
  effectif: "",
  effectiveFrom: "",
};

// Effective-dated per-SIRET establishment rate pack (FR-002/FR-013).
// Every write APPENDS a new period row (Jan/Jul history is never
// rewritten); the unique (org, siret, effectiveFrom) collision surfaces as
// a batch-style error instead of an overwrite.
export default function FranceEstablishmentRatePacksTab({ organizationId }) {
  const [state, setState] = useState({ loading: true, packs: [], error: null });
  const [form, setForm] = useState(BLANK);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [saveError, setSaveError] = useState(null);

  function load() {
    if (!organizationId) {
      setState({ loading: false, packs: [], error: null });
      return;
    }
    setState({ loading: true, packs: [], error: null });
    listFranceEstablishmentRatePacks({ organizationId })
      .then((packs) => setState({ loading: false, packs: Array.isArray(packs) ? packs : [], error: null }))
      .catch((err) => setState({ loading: false, packs: [], error: describeLoadError(err) }));
  }

  useEffect(load, [organizationId]);

  function setField(key, value) {
    setForm((f) => ({ ...f, [key]: value }));
    setSaved(false);
  }

  async function append() {
    setSaving(true);
    setSaveError(null);
    const payload = {
      siret: form.siret,
      communeInsee: form.communeInsee || null,
      workplaceLabel: form.workplaceLabel || null,
      atMpRatePct: form.atMpRatePct === "" ? null : Number(form.atMpRatePct),
      atMpRiskCode: form.atMpRiskCode || null,
      atMpEvidence: form.atMpEvidence || null,
      atMpSource: form.atMpSource || null,
      vmRatePct: form.vmRatePct === "" ? null : Number(form.vmRatePct),
      vmThresholdApplies: form.vmThresholdApplies,
      vmSource: form.vmSource || null,
      fnalClass: form.fnalClass,
      cfpClass: form.cfpClass,
      effectif: form.effectif === "" ? null : Number(form.effectif),
      effectiveFrom: form.effectiveFrom,
    };
    try {
      await upsertFranceEstablishmentRatePack(payload, { organizationId });
      setForm(BLANK);
      setSaved(true);
      load();
    } catch (err) {
      setSaveError(describeLoadError(err));
    } finally {
      setSaving(false);
    }
  }

  if (!organizationId) {
    return <p className="py-10 text-sm text-foreground-muted">Select an organization to manage its establishment rate packs.</p>;
  }

  const active = state.packs.filter((p) => !p.effectiveTo);
  const usedSirets = [...new Set(state.packs.map((p) => p.siret))];

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        <Layers size={16} className="text-primary" />
        <h2 className="text-sm font-bold text-foreground">Establishment rate packs (FR-002/FR-013)</h2>
      </div>
      {usedSirets.map((siret) => {
        const row = active.find((p) => p.siret === siret);
        return (
          <div key={siret} className="rounded-lg border border-border bg-surface p-3 text-xs">
            <span className="font-bold text-foreground">{siret}</span>
            {row ? (
              <span className="ml-2 text-foreground-muted">
                · effective from {row.effectiveFrom} · AT/MP {row.atMpRatePct != null ? `${row.atMpRatePct}%` : "—"} ·{" "}
                {FNAL_CLASS_LABELS[row.fnalClass] || "FNAL —"} · {CFP_CLASS_LABELS[row.cfpClass] || "CFP —"}
              </span>
            ) : (
              <span className="ml-2 text-warning">· no effective pack ·</span>
            )}
          </div>
        );
      })}

      {state.loading ? (
        <p className="py-6 text-sm text-foreground-disabled">Loading rate packs…</p>
      ) : (
        <div className="rounded-lg border border-border bg-surface p-4">
          <p className="text-xs font-bold text-foreground mb-2">Append a new rate-pack period row</p>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-3">
            <label className="block">
              <span className="text-xs font-semibold text-foreground-muted">SIRET (14 digits) *</span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.siret}
                inputMode="numeric"
                onChange={(e) => setField("siret", e.target.value)}
              />
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
              <span className="text-xs font-semibold text-foreground-muted">INSEE commune</span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.communeInsee}
                onChange={(e) => setField("communeInsee", e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-foreground-muted">AT/MP rate % (Urssaf decision)</span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.atMpRatePct}
                inputMode="decimal"
                onChange={(e) => setField("atMpRatePct", e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-foreground-muted">AT/MP evidence</span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.atMpEvidence}
                onChange={(e) => setField("atMpEvidence", e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-foreground-muted">AT/MP source</span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.atMpSource}
                onChange={(e) => setField("atMpSource", e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-foreground-muted">VM rate %</span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.vmRatePct}
                inputMode="decimal"
                onChange={(e) => setField("vmRatePct", e.target.value)}
              />
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-foreground-muted">FNAL class</span>
              <select
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.fnalClass}
                onChange={(e) => setField("fnalClass", e.target.value)}
              >
                {FNAL_CLASSES.map((c) => (
                  <option key={c} value={c}>
                    {FNAL_CLASS_LABELS[c]}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-foreground-muted">CFP class</span>
              <select
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.cfpClass}
                onChange={(e) => setField("cfpClass", e.target.value)}
              >
                {CFP_CLASSES.map((c) => (
                  <option key={c} value={c}>
                    {CFP_CLASS_LABELS[c]}
                  </option>
                ))}
              </select>
            </label>
            <label className="block">
              <span className="text-xs font-semibold text-foreground-muted">Pack effectif</span>
              <input
                className="mt-1 w-full rounded-md border border-border bg-surface px-2.5 py-1.5 text-xs"
                value={form.effectif}
                inputMode="numeric"
                onChange={(e) => setField("effectif", e.target.value)}
              />
            </label>
          </div>
          <div className="mt-3 text-xs">
            <label className="inline-flex items-center gap-2 font-semibold text-foreground-muted">
              <input
                type="checkbox"
                checked={form.vmThresholdApplies}
                onChange={(e) => setField("vmThresholdApplies", e.target.checked)}
              />
              VM threshold applies
            </label>
          </div>
          <div className="mt-4 flex items-center gap-3">
            <button
              onClick={append}
              disabled={saving || !form.siret || !form.effectiveFrom}
              className="rounded-md bg-primary px-3.5 py-1.5 text-xs font-bold text-white disabled:opacity-40"
            >
              {saving ? "Appending…" : "Append rate pack"}
            </button>
            {saved && (
              <span className="inline-flex items-center gap-1 text-xs font-semibold text-green-600">
                <CheckCircle2 size={13} /> Appended — previous period auto-closed
              </span>
            )}
            {saveError && (
              <span className="inline-flex items-center gap-1 text-xs font-semibold text-red-600">
                <AlertTriangle size={13} /> {saveError}
              </span>
            )}
          </div>
        </div>
      )}

      <div className="rounded-lg border border-border bg-surface p-4">
        <p className="text-xs font-bold text-foreground mb-2">Rate pack history ({state.packs.length})</p>
        {state.error ? (
          <p className="text-xs text-foreground-muted">{state.error}</p>
        ) : (
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-foreground-muted">
                <th className="py-1 pr-3 font-semibold">SIRET</th>
                <th className="py-1 pr-3 font-semibold">Effective</th>
                <th className="py-1 pr-3 font-semibold">AT/MP</th>
                <th className="py-1 pr-3 font-semibold">FNAL</th>
                <th className="py-1 pr-3 font-semibold">CFP</th>
                <th className="py-1 font-semibold">Effectif</th>
              </tr>
            </thead>
            <tbody>
              {state.packs.map((p) => (
                <tr key={p.id} className="border-t border-border">
                  <td className="py-1.5 pr-3 font-medium text-foreground">{p.siret}</td>
                  <td className="py-1.5 pr-3">{p.effectiveFrom} → {p.effectiveTo || "open"}</td>
                  <td className="py-1.5 pr-3">{p.atMpRatePct != null ? `${p.atMpRatePct}%` : "—"}</td>
                  <td className="py-1.5 pr-3">{FNAL_CLASS_LABELS[p.fnalClass] || p.fnalClass || "—"}</td>
                  <td className="py-1.5 pr-3">{CFP_CLASS_LABELS[p.cfpClass] || p.cfpClass || "—"}</td>
                  <td className="py-1.5">{p.effectif ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}