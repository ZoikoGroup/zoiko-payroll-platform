import { useMemo, useState } from "react";
import { Percent, Plus } from "lucide-react";
import StatusPill from "../../StatusPill";
import { useToast } from "../../../context/ToastContext";
import { listFrancePASRates, getReportsEmployees } from "../../../service/superAdminService";
import { loadErrorText } from "../../../service/errorClassification";
import FrancePASRateFormModal from "./FrancePASRateFormModal";
import { PAS_RATE_STATUS_TONE, pasRateType } from "./franceStatutoryConfig";
import { useFranceOrgData } from "./useFranceOrgData";

const FILTERS = [
  { key: "all", label: "All" },
  { key: "ACTIVE", label: "Active" },
  { key: "PENDING", label: "Pending" },
  { key: "SUPERSEDED", label: "Superseded / corrected" },
];

// The rates AND the employee list are loaded for the SELECTED organization
// (the cross-org reports endpoint, filtered by org) — never the signed-in
// super admin's own organization.
const loadAll = (params) => Promise.all([
  listFrancePASRates(params),
  getReportsEmployees({ organization_id: params.organizationId, limit: 200 }),
]).then(([rates, employees]) => ({ rates: rates || [], employees: employees?.items || [] }));

// PAS ledger (FR-008/FR-010): every DGFiP rate recorded for the org's France
// employees, with its provenance. History is never deleted.
export default function FrancePASRatesPanel({ organizationId }) {
  const { addToast } = useToast() || {};
  const { data, error, loading, reload } = useFranceOrgData(organizationId, loadAll);
  const [filter, setFilter] = useState("all");
  const [showModal, setShowModal] = useState(false);

  const rates = useMemo(() => data?.rates || [], [data]);
  const employees = useMemo(() => data?.employees || [], [data]);
  const employeeName = useMemo(() => new Map(employees.map((e) => [e.id, `${e.name} (${e.employeeCode})`])), [employees]);

  const visible = useMemo(() => {
    if (filter === "all") return rates;
    if (filter === "SUPERSEDED") return rates.filter((r) => ["STALE", "CORRECTED"].includes(r.status));
    return rates.filter((r) => r.status === filter);
  }, [rates, filter]);
  const counts = {
    all: rates.length,
    ACTIVE: rates.filter((r) => r.status === "ACTIVE").length,
    PENDING: rates.filter((r) => r.status === "PENDING").length,
    SUPERSEDED: rates.filter((r) => ["STALE", "CORRECTED"].includes(r.status)).length,
  };

  if (!organizationId) {
    return <p className="py-10 text-xs text-foreground-muted">Select a France organization to manage its PAS rates.</p>;
  }

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <h2 className="flex items-center gap-1.5 text-sm font-bold text-foreground">
            <Percent size={15} className="text-primary" /> PAS rates (prélèvement à la source)
          </h2>
          <p className="mt-0.5 text-xs text-foreground-muted">
            DGFiP personalized rates with their CRM provenance, and neutral-grid rows. An older period always uses the rate
            that governed it.
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)} disabled={loading}
          className="flex items-center gap-1.5 rounded-lg bg-primary px-3 py-2 text-xs font-semibold text-white hover:bg-primary-hover disabled:opacity-50"
        >
          <Plus size={13} /> Record DGFiP rate
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {FILTERS.map((f) => (
          <button key={f.key} onClick={() => setFilter(f.key)}
            className={`rounded-full px-3 py-1 text-xs font-semibold ${filter === f.key ? "bg-primary text-white" : "bg-surface-muted text-foreground-muted hover:text-foreground"}`}>
            {f.label} <span className="opacity-70">{counts[f.key]}</span>
          </button>
        ))}
      </div>

      {loading ? (
        <p className="py-8 text-center text-xs text-foreground-disabled">Loading PAS rates…</p>
      ) : error ? (
        <p className="py-8 text-center text-xs text-foreground-muted">{loadErrorText(error)}</p>
      ) : visible.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border bg-surface-muted py-10 text-center">
          <p className="text-xs text-foreground-disabled">No PAS rates{filter === "all" ? "" : " in this filter"} yet.</p>
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-border bg-surface">
          <table className="w-full text-xs">
            <thead>
              <tr className="border-b border-border-light text-left text-foreground-muted">
                <th className="px-4 py-2 font-semibold">ID</th>
                <th className="px-4 py-2 font-semibold">Employee</th>
                <th className="px-4 py-2 font-semibold">Type</th>
                <th className="px-4 py-2 font-semibold">Rate</th>
                <th className="px-4 py-2 font-semibold">Effective</th>
                <th className="px-4 py-2 font-semibold">DGFiP id · CRM · received</th>
                <th className="px-4 py-2 font-semibold">Corrects</th>
                <th className="px-4 py-2 font-semibold">Status</th>
              </tr>
            </thead>
            <tbody>
              {visible.map((r) => (
                <tr key={r.id} className="border-b border-border-light last:border-0">
                  <td className="px-4 py-2.5 font-mono text-foreground-disabled">#{r.id}</td>
                  <td className="px-4 py-2.5 font-medium text-foreground">{employeeName.get(r.employeeId) || `#${r.employeeId}`}</td>
                  <td className="px-4 py-2.5">{pasRateType(r.rateType)?.label || r.rateType}</td>
                  <td className="px-4 py-2.5 font-mono tabular-nums">{r.ratePct != null ? `${r.ratePct}%` : "neutral grid"}</td>
                  <td className="px-4 py-2.5 font-mono tabular-nums text-foreground-secondary">{r.effectiveFrom} → {r.effectiveTo || "open"}</td>
                  <td className="px-4 py-2.5 text-foreground-muted">{[r.dgfipRateId, r.crmReference, r.receivedDate].filter(Boolean).join(" · ") || "—"}</td>
                  <td className="px-4 py-2.5 font-mono text-foreground-disabled">{r.correctionOfId ? `#${r.correctionOfId}` : "—"}</td>
                  <td className="px-4 py-2.5"><StatusPill status={PAS_RATE_STATUS_TONE[r.status] || "inactive"} label={r.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {showModal && (
        <FrancePASRateFormModal
          organizationId={organizationId}
          rates={rates}
          employees={employees}
          onClose={() => setShowModal(false)}
          onSaved={() => {
            setShowModal(false);
            addToast?.("PAS rate recorded.", "success");
            reload();
          }}
        />
      )}
    </div>
  );
}
