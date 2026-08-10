import { Settings2 } from "lucide-react";
import { ENTERPRISE_JURISDICTIONS } from "../../../../service/payrollService";

function StatusPill({ status }) {
  const map = {
    draft: "bg-[#9E9690]/10 text-[#9E9690]",
    configured: "bg-[#35B6F5]/10 text-[#35B6F5]",
    verified: "bg-[#19C58A]/10 text-[#19C58A]",
  };
  const labels = { draft: "Draft", configured: "Configured", verified: "Verified" };
  if (!status) {
    return (
      <span className="inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold bg-[#F0EDE8] dark:bg-[#38312D] text-[#9E9690]">
        Not Configured
      </span>
    );
  }
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold ${map[status] || map.draft}`}>
      {labels[status] || status}
    </span>
  );
}

export default function JurisdictionList({ jurisdictions = [], onConfigure, canEdit = true }) {
  const byCode = Object.fromEntries(jurisdictions.map((j) => [j.countryCode, j]));

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
      {ENTERPRISE_JURISDICTIONS.map((meta) => {
        const existing = byCode[meta.code];
        return (
          <div
            key={meta.code}
            className="bg-white dark:bg-[#221D1A] border border-[#E5E0D9] dark:border-[#38312D] rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] flex flex-col gap-4"
          >
            <div className="flex items-center gap-3">
              <span
                className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-[#F0EDE8] dark:bg-[#38312D] text-[20px] leading-none text-[#1A1816] dark:text-[#F0EDE8]"
                title={meta.code}
              >
                {meta.flag}
              </span>
              <p className="text-[15px] font-bold text-[#1A1816] dark:text-[#F0EDE8]">{meta.name}</p>
            </div>
            <dl className="space-y-1.5 text-[12px]">
              <div className="flex items-center justify-between">
                <dt className="text-[#9E9690]">Currency</dt>
                <dd className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{meta.currency}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-[#9E9690]">Financial Year</dt>
                <dd className="font-semibold text-[#1A1816] dark:text-[#F0EDE8]">{meta.financialYear}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-[#9E9690]">Status</dt>
                <dd><StatusPill status={existing?.status} /></dd>
              </div>
            </dl>
            <button
              onClick={() => onConfigure(meta, existing)}
              disabled={!canEdit}
              className="flex items-center justify-center gap-2 rounded-[10px] border border-[#E5E0D9] dark:border-[#38312D] px-4 py-2 text-[12px] font-bold text-[#1A1816] dark:text-[#F0EDE8] hover:border-[#9D7BF2] hover:text-[#9D7BF2] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
            >
              <Settings2 size={13} />
              Configure
            </button>
          </div>
        );
      })}
    </div>
  );
}
