import { useState } from "react";
import { Layers, Plus, ChevronDown, Pencil, CalendarX } from "lucide-react";
import Modal from "../../Modal";
import { useToast } from "../../../context/ToastContext";
import {
  listFranceEstablishmentRatePacks, listFranceEstablishments, closeFranceEstablishmentRatePack,
} from "../../../service/superAdminService";
import { describeLoadError, loadErrorText } from "../../../service/errorClassification";
import { inputClass, labelClass } from "../constants";
import FranceEstablishmentRateFormModal from "./FranceEstablishmentRateFormModal";
import { fnalReference, cfpReference } from "./franceStatutoryConfig";
import { useFranceOrgData } from "./useFranceOrgData";

const loadAll = (params) => Promise.all([listFranceEstablishmentRatePacks(params), listFranceEstablishments(params)])
  .then(([packs, establishments]) => ({ packs: packs || [], establishments: establishments || [] }));

// Employer rates per establishment (FR-002/FR-013, §11 panel E). Periods
// are effective-dated: a new period closes the open one; a period that has
// not started yet can be edited; an open period can be closed (e.g. the
// establishment shut). In-force history is never rewritten.
export default function FranceEstablishmentRatePacksPanel({ organizationId }) {
  const { addToast } = useToast() || {};
  const { data, error, loading, reload } = useFranceOrgData(organizationId, loadAll);
  const [collapsed, setCollapsed] = useState({});
  const [modal, setModal] = useState(null);        // { establishmentId?, period? }
  const [closing, setClosing] = useState(null);    // { period, date, error, saving }

  const today = new Date().toISOString().slice(0, 10);
  const packs = data?.packs || [];
  const establishments = data?.establishments || [];
  const activeEstablishments = establishments.filter((e) => e.isActive);

  if (!organizationId) {
    return <p className="py-10 text-xs text-foreground-muted">Select a France organization to manage its employer rates.</p>;
  }

  // Group by SIRET — registry establishments first, then any legacy SIRET
  // that only exists on a rate-pack row.
  const sirets = [...new Set([...establishments.map((e) => e.siret), ...packs.map((p) => p.siret)])];
  const periodsOf = (siret) => packs.filter((p) => p.siret === siret)
    .sort((a, b) => String(b.effectiveFrom).localeCompare(String(a.effectiveFrom)));

  async function confirmClose() {
    if (!closing.date) return setClosing((c) => ({ ...c, error: "Choose the last day of the period." }));
    setClosing((c) => ({ ...c, saving: true, error: "" }));
    try {
      await closeFranceEstablishmentRatePack(closing.period.id, { effectiveTo: closing.date }, { organizationId });
      addToast?.("Period closed.", "success");
      setClosing(null);
      reload();
    } catch (err) {
      setClosing((c) => ({ ...c, saving: false, error: loadErrorText(describeLoadError(err)) }));
    }
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
            <Layers size={15} className="text-primary" /> Employer rates (§11 panel E, FR-002/FR-013)
          </h2>
          <p className="mt-0.5 text-xs text-foreground-muted">
            AT/MP, versement mobilité, FNAL/CFP class and AGS status per establishment and effective period.
          </p>
        </div>
        <button
          onClick={() => setModal({})}
          disabled={loading || activeEstablishments.length === 0}
          title={activeEstablishments.length === 0 ? "Register an establishment first" : undefined}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          <Plus size={13} /> Add period
        </button>
      </div>

      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading employer rates…</p>
      ) : error ? (
        <p className="py-8 text-center text-xs text-foreground-muted">{loadErrorText(error)}</p>
      ) : sirets.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-surface-muted py-10 text-center">
          <p className="text-xs text-foreground-disabled">No establishment yet — register one under Establishments, then add its rates here.</p>
        </div>
      ) : (
        <div className="space-y-3">
          {sirets.map((siret) => {
            const est = establishments.find((e) => e.siret === siret);
            const periods = periodsOf(siret);
            const effectiveNow = periods.find((p) => p.effectiveFrom <= today && (!p.effectiveTo || p.effectiveTo >= today));
            const isCollapsed = collapsed[siret];
            return (
              <div key={siret} className="rounded-xl border border-border bg-surface">
                <div className="flex items-center justify-between gap-3 px-4 py-3">
                  <button onClick={() => setCollapsed((c) => ({ ...c, [siret]: !c[siret] }))} className="flex items-center gap-2 text-left">
                    <ChevronDown size={15} className={`text-foreground-muted transition-transform ${isCollapsed ? "-rotate-90" : ""}`} />
                    <span className="font-mono text-sm font-bold text-foreground">{siret}</span>
                    {est?.name && <span className="text-xs text-foreground-muted">{est.name}</span>}
                    <span className={`rounded-full px-2 py-0.5 text-[10px] font-bold ${effectiveNow ? "bg-primary/10 text-primary" : "bg-warning-light text-warning"}`}>
                      {effectiveNow ? "Rates in force" : "No rates in force today"}
                    </span>
                    {!est && <span className="text-[10px] text-foreground-disabled">(not in the establishment registry)</span>}
                    {est && !est.isActive && <span className="text-[10px] text-foreground-disabled">(inactive)</span>}
                  </button>
                  {est?.isActive && (
                    <button onClick={() => setModal({ establishmentId: est.id })}
                      className="flex items-center gap-1 rounded-lg border border-border px-2.5 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
                      <Plus size={12} /> Add period
                    </button>
                  )}
                </div>
                {!isCollapsed && periods.length > 0 && (
                  <div className="border-t border-border-light">
                    {periods.map((p) => {
                      const fnal = fnalReference(p.fnalClass);
                      const cfp = cfpReference(p.cfpClass);
                      const future = p.effectiveFrom > today;
                      return (
                        <div key={p.id} className="flex flex-wrap items-center gap-x-5 gap-y-1 border-b border-border-light last:border-0 px-4 py-2.5 text-xs">
                          <span className="font-mono tabular-nums text-foreground-secondary">{p.effectiveFrom} → {p.effectiveTo || "open"}</span>
                          <span className="tabular-nums text-foreground">AT/MP {p.atMpRatePct != null ? `${p.atMpRatePct}%` : "—"}</span>
                          <span className="tabular-nums text-foreground-muted">
                            VM {p.vmRatePct != null ? `${p.vmRatePct}%` : p.vmThresholdApplies === false ? "not due (< 11)" : "missing"}
                          </span>
                          <span className="text-foreground-muted">FNAL {fnal ? `${fnal.pct}%` : p.fnalClass || "—"}</span>
                          <span className="text-foreground-muted">CFP {cfp ? `${cfp.pct}%` : p.cfpClass || "—"}</span>
                          {p.agsSpecialStatus && <span className="text-foreground-muted">AGS {p.agsSpecialStatus}</span>}
                          <span className="text-foreground-disabled">
                            {[p.atMpEvidence && `AT/MP ref ${p.atMpEvidence}`, p.atMpSource, p.vmEvidence && `VM ref ${p.vmEvidence}`].filter(Boolean).join(" · ")}
                          </span>
                          <span className="ml-auto flex gap-1">
                            {future && (
                              <button onClick={() => setModal({ period: p })}
                                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground-secondary hover:bg-surface-muted">
                                <Pencil size={11} /> Edit
                              </button>
                            )}
                            {!p.effectiveTo && (
                              <button onClick={() => setClosing({ period: p, date: "", error: "", saving: false })}
                                className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-1 text-[11px] font-semibold text-foreground-secondary hover:bg-surface-muted">
                                <CalendarX size={11} /> Close
                              </button>
                            )}
                          </span>
                        </div>
                      );
                    })}
                  </div>
                )}
              </div>
            );
          })}
        </div>
      )}

      {modal && (
        <FranceEstablishmentRateFormModal
          organizationId={organizationId}
          establishments={activeEstablishments}
          defaultEstablishmentId={modal.establishmentId}
          period={modal.period}
          onClose={() => setModal(null)}
          onSaved={() => {
            addToast?.(modal.period ? "Future period updated." : "Rate period added.", "success");
            setModal(null);
            reload();
          }}
        />
      )}

      {closing && (
        <Modal title={`Close period from ${closing.period.effectiveFrom}`} onClose={() => setClosing(null)}>
          <label className={labelClass}>Last day of this period</label>
          <input type="date" className={inputClass} min={closing.period.effectiveFrom} value={closing.date}
            onChange={(e) => setClosing((c) => ({ ...c, date: e.target.value }))} />
          <p className="mt-2 text-[11px] text-foreground-muted">After this date the establishment has no rates in force until a new period is added — France payroll for it will block.</p>
          {closing.error && <p className="mt-2 text-xs text-error">{closing.error}</p>}
          <div className="mt-5 flex justify-end gap-2">
            <button onClick={() => setClosing(null)} className="rounded-lg border border-border px-4 py-2 text-sm text-foreground-secondary hover:bg-surface-muted">Cancel</button>
            <button onClick={confirmClose} disabled={closing.saving} className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-white hover:bg-primary-hover disabled:opacity-50">
              {closing.saving ? "Closing…" : "Close period"}
            </button>
          </div>
        </Modal>
      )}
    </div>
  );
}
