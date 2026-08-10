import { useState, useEffect, useCallback } from "react";
import { Loader2, CheckCircle2, AlertCircle, Globe2 } from "lucide-react";
import { getEnterpriseValidation, activateEnterprise, ENTERPRISE_JURISDICTIONS } from "../../../../service/payrollService";

export default function EnterpriseActivationDialog({ onClose, onActivated }) {
  const [validation, setValidation] = useState(null);
  const [loading, setLoading] = useState(true);
  const [activating, setActivating] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    const v = await getEnterpriseValidation();
    setValidation(v);
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleActivate = async () => {
    setActivating(true);
    setError("");
    try {
      await activateEnterprise();
      onActivated?.();
    } catch {
      setError("Failed to activate Enterprise Payroll. Please try again.");
    } finally {
      setActivating(false);
    }
  };

  const jurisdictionName = (label) => {
    const meta = ENTERPRISE_JURISDICTIONS.find((j) => j.name === label);
    return meta ? `${meta.flag} ${label}` : label;
  };

  return (
    <div className="fixed inset-0 z-[9998] flex items-center justify-center bg-[#1A1816]/40 backdrop-blur-sm" onClick={onClose}>
      <div
        className="bg-white dark:bg-[#221D1A] rounded-[18px] shadow-[0_24px_48px_rgba(0,0,0,0.15)] p-6 w-full max-w-md"
        onClick={(e) => e.stopPropagation()}
      >
        <div className="flex items-center gap-3 mb-4">
          <div className="h-10 w-10 rounded-[12px] bg-[#9D7BF2] flex items-center justify-center">
            <Globe2 size={20} className="text-white" />
          </div>
          <h3 className="text-[16px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">Activate Enterprise Payroll</h3>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-10">
            <Loader2 size={20} className="animate-spin text-[#9D7BF2]" />
          </div>
        ) : validation?.canActivate ? (
          <>
            <p className="text-[13px] text-[#6B6560] dark:text-[#A69B93] mb-3">Enterprise Payroll is ready.</p>
            <p className="text-[11px] font-bold uppercase tracking-widest text-[#9E9690] mb-2">Selected Jurisdictions</p>
            <ul className="mb-5 space-y-1.5">
              {validation.configuredJurisdictions.map((name) => (
                <li key={name} className="flex items-center gap-2 text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8]">
                  <CheckCircle2 size={13} className="text-[#19C58A]" />
                  {jurisdictionName(name)}
                </li>
              ))}
            </ul>
            <p className="text-[13px] font-semibold text-[#1A1816] dark:text-[#F0EDE8] mb-5">
              Activate Enterprise Payroll?
            </p>
          </>
        ) : (
          <div className="mb-5 space-y-2">
            {validation?.blockingReasons?.map((reason, i) => (
              <div key={i} className="flex items-start gap-2 rounded-[10px] bg-[#FF6E86]/10 px-3.5 py-2.5 text-[12px] text-[#FF6E86]">
                <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
                {reason}
              </div>
            ))}
          </div>
        )}

        {error && (
          <div className="mb-4 flex items-start gap-2 rounded-[10px] bg-[#FF6E86]/10 px-3.5 py-2.5 text-[12px] text-[#FF6E86]">
            <AlertCircle size={14} className="mt-0.5 flex-shrink-0" />
            {error}
          </div>
        )}

        <div className="flex justify-end gap-3">
          <button
            onClick={onClose}
            className="rounded-[10px] px-4 py-2 text-[13px] font-semibold text-[#6B6560] dark:text-[#A69B93] hover:bg-[#F0EDE8] dark:hover:bg-[#38312D] transition-colors"
          >
            Cancel
          </button>
          {validation?.canActivate && (
            <button
              onClick={handleActivate}
              disabled={activating}
              className="flex items-center gap-2 rounded-[10px] bg-[#9D7BF2] px-4 py-2 text-[13px] font-bold text-white hover:bg-[#8A65E0] transition-colors disabled:opacity-60"
            >
              {activating ? <Loader2 size={14} className="animate-spin" /> : <CheckCircle2 size={14} />}
              Activate
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
