import { Settings2 } from "lucide-react";
import { ENTERPRISE_JURISDICTIONS } from "../../../../service/payrollService";

function StatusPill({ status }) {
  const map = {
    draft: "bg-foreground-muted/10 text-foreground-muted",
    configured: "bg-info/10 text-info",
    verified: "bg-primary/10 text-primary",
  };
  const labels = { draft: "Draft", configured: "Configured", verified: "Verified" };
  if (!status) {
    return (
      <span className="inline-flex items-center rounded-full px-2.5 py-1 text-[11px] font-bold bg-surface-muted text-foreground-muted">
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
            className="bg-surface border border-border rounded-[18px] p-5 shadow-[0_1px_3px_rgba(0,0,0,0.04)] flex flex-col gap-4"
          >
            <div className="flex items-center gap-3">
              <span
                className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-surface-muted text-[20px] leading-none text-foreground"
                title={meta.code}
              >
                {meta.flag}
              </span>
              <p className="text-[15px] font-bold text-foreground">{meta.name}</p>
            </div>
            <dl className="space-y-1.5 text-[12px]">
              <div className="flex items-center justify-between">
                <dt className="text-foreground-muted">Currency</dt>
                <dd className="font-semibold text-foreground">{meta.currency}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-foreground-muted">Financial Year</dt>
                <dd className="font-semibold text-foreground">{meta.financialYear}</dd>
              </div>
              <div className="flex items-center justify-between">
                <dt className="text-foreground-muted">Status</dt>
                <dd><StatusPill status={existing?.status} /></dd>
              </div>
            </dl>
            <button
              onClick={() => onConfigure(meta, existing)}
              disabled={!canEdit}
              className="flex items-center justify-center gap-2 rounded-[10px] border border-border px-4 py-2 text-[12px] font-bold text-foreground hover:border-category-teal hover:text-category-teal transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
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
