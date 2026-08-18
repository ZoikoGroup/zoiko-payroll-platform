// DEPRECATION NOTICE (Phase 9 cleanup inventory, see
// backend/scripts/HIERARCHY_V2_CLEANUP_INVENTORY.md): per the hierarchy
// engine plan, "Enterprise" is meant to eventually become a derived UI
// state (an org with >1 active jurisdiction assignment) rather than this
// standalone tab/mode, once the hierarchy engine's org-assignment UI
// exists and organizations are cut over to it. NOT removed or changed
// here — this is exactly what today's live Enterprise-mode Compliance
// page runs on, and zero organizations are on the hierarchy engine yet.
import { useState, useEffect, useCallback } from "react";
import { Rocket } from "lucide-react";
import { useAuth } from "../../../../context/AuthContext";
import { ROLES } from "../../../../config/roles";
import { useToast } from "../../ToastContext";
import JurisdictionList from "./JurisdictionList";
import JurisdictionConfigPanel from "./JurisdictionConfigPanel";
import EnterpriseActivationDialog from "./EnterpriseActivationDialog";
import EnterpriseComplianceDashboard from "./EnterpriseComplianceDashboard";
import { getEnterpriseJurisdictions } from "../../../../service/payrollService";

export default function EnterpriseJurisdictionsTab({ enterpriseStatus, onEnterpriseChanged }) {
  const { hasRole } = useAuth();
  const { addToast } = useToast();
  const canEdit = hasRole([ROLES.ADMIN, ROLES.SUPER_ADMIN]);

  const [jurisdictions, setJurisdictions] = useState([]);
  const [loading, setLoading] = useState(true);
  const [configuring, setConfiguring] = useState(null); // { meta, existing }
  const [showActivation, setShowActivation] = useState(false);
  const [dashboardKey, setDashboardKey] = useState(0);

  const load = useCallback(async () => {
    setLoading(true);
    const data = await getEnterpriseJurisdictions();
    setJurisdictions(Array.isArray(data) ? data : []);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleConfigSaved = () => {
    load();
    setDashboardKey((k) => k + 1);
    onEnterpriseChanged?.();
  };

  const handleActivated = () => {
    setShowActivation(false);
    addToast?.("Enterprise Payroll activated.", "success");
    load();
    setDashboardKey((k) => k + 1);
    onEnterpriseChanged?.();
  };

  const canActivate = jurisdictions.length > 0 && jurisdictions.every((j) => j.status !== "draft") && enterpriseStatus !== "active";

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h3 className="text-[15px] font-bold text-foreground">Enterprise Jurisdictions</h3>
          <p className="text-[12px] text-foreground-muted mt-0.5">
            Select and configure the countries your organization operates payroll in.
          </p>
        </div>
        {canActivate && (
          <button
            onClick={() => setShowActivation(true)}
            disabled={!canEdit}
            className="flex items-center gap-2 rounded-[12px] bg-category-teal px-4 py-2 text-[13px] font-bold text-white hover:bg-category-teal shadow-[0_2px_8px_rgba(157,123,242,0.3)] transition-colors disabled:opacity-50"
          >
            <Rocket size={14} />
            Activate Enterprise Payroll
          </button>
        )}
      </div>

      {!loading && (
        <JurisdictionList
          jurisdictions={jurisdictions}
          canEdit={canEdit}
          onConfigure={(meta, existing) => setConfiguring({ meta, existing })}
        />
      )}

      {jurisdictions.length > 0 && (
        <EnterpriseComplianceDashboard refreshKey={dashboardKey} />
      )}

      {configuring && (
        <JurisdictionConfigPanel
          meta={configuring.meta}
          jurisdiction={configuring.existing}
          canEdit={canEdit}
          onClose={() => setConfiguring(null)}
          onSaved={handleConfigSaved}
        />
      )}

      {showActivation && (
        <EnterpriseActivationDialog
          onClose={() => setShowActivation(false)}
          onActivated={handleActivated}
        />
      )}
    </div>
  );
}
