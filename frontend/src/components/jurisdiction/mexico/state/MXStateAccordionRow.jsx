import { useState } from "react";
import { ChevronDown, ChevronRight, FileCheck2, History, MapPin, Percent, ShieldCheck } from "lucide-react";
import StatusPill from "../../../StatusPill";
import { useToast } from "../../../../context/ToastContext";
import { approveCompliancePolicy, setCompliancePolicyStatus } from "../../../../service/superAdminService";
import { inputClass, STATUS_OPTIONS, STATUS_PILL_MAP } from "../../constants";
import MXStateIsnTab from "./MXStateIsnTab";
// Reused as-is, exactly as the Australia state accordion does — both are
// fully generic (pack-only / linkTo-only props).
import USStateVersionAuditSection from "../../usa/state/USStateVersionAuditSection";
import USStateSourceEvidenceNote from "../../usa/state/USStateSourceEvidenceNote";

const TABS = [
  { key: "isn", label: "State ISN", icon: Percent },
  { key: "sourceEvidence", label: "Source Evidence", icon: FileCheck2 },
  { key: "versionAudit", label: "Version / Audit", icon: History },
];

// One federal entity's summary row + detail — cloned from
// AUStateAccordionRow.jsx. A state with no ISN pack is unsupported: its
// payroll BLOCKS (MX-045) and no pack can be created here.
export default function MXStateAccordionRow({ state, isExpanded, onToggle, onPackUpdated }) {
  const { addToast } = useToast() || {};
  const pack = state.packs[0] || null;
  // The pack as last returned by a status / approval action, while it is still
  // this state's pack; otherwise the pack from the registry listing.
  const [updated, setUpdated] = useState(null);
  const selectedPack = updated && pack && updated.id === pack.id ? updated : pack;
  const setSelectedPack = setUpdated;
  const [tab, setTab] = useState("isn");

  async function changeStatus(newStatus) {
    try {
      const updated = await setCompliancePolicyStatus(selectedPack.id, newStatus);
      addToast?.(`Status set to ${newStatus}.`, "success");
      setSelectedPack(updated);
      onPackUpdated?.();
    } catch (err) {
      addToast?.(err.message || "Failed to change status.", "error");
    }
  }

  async function handleApprove() {
    try {
      const updated = await approveCompliancePolicy(selectedPack.id);
      addToast?.("You're now recorded as this pack's approver.", "success");
      setSelectedPack(updated);
      onPackUpdated?.();
    } catch (err) {
      addToast?.(err.message || "Failed to record approval.", "error");
    }
  }

  const summary = pack ? `${pack.packId} · v${pack.version} · ${pack.contributionRates} parameter(s)` : "Not supported — payroll BLOCKED";
  return (
    <div className="rounded-xl border border-border bg-surface" data-testid={`mx-isn-${state.code}`}>
      <button onClick={onToggle} className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left">
        <div className="flex min-w-0 items-center gap-3">
          {isExpanded ? <ChevronDown size={16} className="shrink-0 text-foreground-muted" /> : <ChevronRight size={16} className="shrink-0 text-foreground-muted" />}
          <MapPin size={14} className="shrink-0 text-foreground-muted" />
          <div className="min-w-0">
            <p className="truncate text-sm font-semibold text-foreground">{state.name} ({state.code})</p>
            <p className={`truncate text-xs ${pack ? "text-foreground-muted" : "text-error"}`}>{summary}</p>
          </div>
        </div>
        {pack
          ? <StatusPill status={STATUS_PILL_MAP[pack.status] || "pending"} label={pack.status} />
          : <span className="rounded bg-error/10 px-2 py-0.5 text-[11px] font-semibold text-error">BLOCKED</span>}
      </button>

      {isExpanded && (
        <div className="border-t border-border p-4">
          {!selectedPack ? (
            <p className="py-4 text-center text-xs text-foreground-muted">
              {state.name} has no certified ISN content pack. Payroll for employees working here is BLOCKED
              (MX-045). A pack is added only after the owner confirms this state and its current fiscal code is
              saved and verified.
            </p>
          ) : (
            <>
              <div className="mb-4 flex flex-wrap items-start justify-between gap-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="text-base font-bold text-foreground">{selectedPack.packId}</h3>
                    <StatusPill status={STATUS_PILL_MAP[selectedPack.status] || "pending"} label={selectedPack.status} />
                  </div>
                  <p className="mt-0.5 text-xs text-foreground-muted">
                    v{selectedPack.version} · {state.name}
                    {selectedPack.effectiveFrom ? ` · ${selectedPack.effectiveFrom} → ${selectedPack.effectiveTo || "open"}` : ""}
                    {state.readiness ? ` · readiness ${state.readiness.program} / ${state.readiness.legalStatus}` : ""}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-2">
                  <button onClick={handleApprove}
                          className="flex items-center gap-1.5 rounded-lg border border-border px-3 py-2 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted">
                    <ShieldCheck size={13} /> Approve
                  </button>
                  <select className={inputClass + " w-auto"} value={selectedPack.status} onChange={(e) => changeStatus(e.target.value)}
                          aria-label="Pack status">
                    {STATUS_OPTIONS.map((s) => <option key={s} value={s}>{s}</option>)}
                  </select>
                </div>
              </div>
              <div className="mb-4 flex items-center gap-1 overflow-x-auto border-b border-border">
                {TABS.map((t) => (
                  <button key={t.key} onClick={() => setTab(t.key)}
                          className={`flex items-center gap-1.5 whitespace-nowrap border-b-2 px-3 py-2 text-xs font-medium ${
                            tab === t.key ? "border-primary text-primary" : "border-transparent text-foreground-muted hover:text-foreground"}`}>
                    <t.icon size={13} /> {t.label}
                  </button>
                ))}
              </div>
              {tab === "isn" && <MXStateIsnTab packId={selectedPack.id} />}
              {tab === "sourceEvidence" && (
                <USStateSourceEvidenceNote linkTo="/super-admin/compliance/mexico" linkLabel="View Source Evidence (Sources tab) →" />
              )}
              {tab === "versionAudit" && <USStateVersionAuditSection pack={selectedPack} />}
            </>
          )}
        </div>
      )}
    </div>
  );
}
