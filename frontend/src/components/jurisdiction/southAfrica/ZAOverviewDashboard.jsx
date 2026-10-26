import { useMemo } from "react";
import { AlertTriangle, Calculator, FileCheck2, Landmark, RefreshCw, ShieldCheck } from "lucide-react";
import { formatZarAuto } from "./zaComponentConfig";

function MetricCard({ label, value, icon: Icon }) {
  return (
    <div className="rounded-xl border border-border bg-surface p-4">
      <div className="flex items-start justify-between gap-2">
        <div>
          <p className="text-xs text-foreground-muted">{label}</p>
          <p className="mt-1 font-mono text-[15px] font-semibold text-foreground">{value ?? "—"}</p>
        </div>
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary/10">
          <Icon size={18} className="text-primary" />
        </div>
      </div>
    </div>
  );
}

function StatusPill({ status }) {
  const colors = {
    Active: "bg-emerald-500/10 text-emerald-700 border-emerald-500/20",
    Draft: "bg-amber-500/10 text-amber-700 border-amber-500/20",
    Superseded: "bg-slate-500/10 text-slate-700 border-slate-500/20",
    Archived: "bg-neutral-500/10 text-neutral-700 border-neutral-500/20",
  };
  return (
    <span className={`inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold ${colors[status] || "bg-surface-muted text-foreground-muted border-border"}`}>
      {status}
    </span>
  );
}

function pending(row) {
  return String(row?.label || row?.rateLabel || "").includes("[PENDING G1]")
    || String(row?.textValue || "") === "PENDING_G1";
}

export default function ZAOverviewDashboard({ pack, rates, slabs, onReload }) {
  const stats = useMemo(() => {
    if (!pack) return null;
    const rateMap = new Map((rates || []).map((row) => [row.componentKey, row]));
    const amount = (key) => {
      const value = rateMap.get(key)?.flatAmount;
      return value == null ? "Not configured" : formatZarAuto(value);
    };

    const payeBands = (slabs || []).filter((row) => row.ruleType === "ZA_PAYE_BAND").length;
    const etiBands = (slabs || []).filter((row) => row.ruleType === "ZA_ETI_BAND").length;
    const earningClasses = (slabs || []).filter((row) => row.ruleType === "ZA_EARNING_CLASS").length;
    const pendingCount = [...(rates || []), ...(slabs || [])].filter(pending).length;

    return {
      payeBands,
      etiBands,
      earningClasses,
      pendingCount,
      uifCeiling: amount("za_uif_monthly_ceiling"),
      sdlExemption: amount("za_sdl_exemption_threshold"),
      retirementCap: amount("za_retirement_annual_cap"),
      nmw: rateMap.get("za_nmw_hourly")?.flatAmount == null
        ? "Not configured"
        : `${formatZarAuto(rateMap.get("za_nmw_hourly").flatAmount)}/hour`,
      brsVersion: rateMap.get("za_brs_version")?.textValue || "Not configured",
      packWindow: `${pack.effectiveFrom || "—"} to ${pack.effectiveTo || "—"}`,
    };
  }, [pack, rates, slabs]);

  if (!stats) {
    return (
      <div className="rounded-xl border border-dashed border-border bg-surface-muted p-8 text-center">
        <AlertTriangle size={32} className="mx-auto text-foreground-disabled" />
        <p className="mt-3 text-sm text-foreground-muted">Select a South Africa tax pack to see its configuration.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-bold text-foreground">South Africa statutory configuration</h2>
          <p className="mt-1 flex flex-wrap items-center gap-2 text-sm text-foreground-muted">
            <span>Pack <span className="font-mono text-foreground">{pack.version}</span></span>
            <StatusPill status={pack.status} />
            <span>{stats.packWindow}</span>
          </p>
        </div>
        {onReload && (
          <button
            type="button"
            onClick={onReload}
            className="inline-flex items-center gap-1.5 rounded-lg border border-border px-3 py-1.5 text-xs font-semibold text-foreground-secondary hover:bg-surface-muted"
          >
            <RefreshCw size={13} /> Refresh
          </button>
        )}
      </div>

      <div className="rounded-xl border border-warning/40 bg-warning/10 p-3 text-[12px] text-foreground-secondary">
        South Africa remains PLANNED. This pack has {stats.pendingCount} row{stats.pendingCount === 1 ? "" : "s"} marked
        PENDING G1; live payroll stays disabled until every release gate is evidenced and signed.
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <MetricCard label="PAYE bands" value={stats.payeBands} icon={Calculator} />
        <MetricCard label="ETI bands" value={stats.etiBands} icon={Landmark} />
        <MetricCard label="Earning classifications" value={stats.earningClasses} icon={FileCheck2} />
        <MetricCard label="PENDING G1 rows" value={stats.pendingCount} icon={ShieldCheck} />
        <MetricCard label="UIF monthly ceiling" value={stats.uifCeiling} icon={ShieldCheck} />
        <MetricCard label="SDL annual exemption" value={stats.sdlExemption} icon={ShieldCheck} />
        <MetricCard label="Retirement annual cap" value={stats.retirementCap} icon={ShieldCheck} />
        <MetricCard label="National Minimum Wage" value={stats.nmw} icon={Landmark} />
        <MetricCard label="BRS version" value={stats.brsVersion} icon={FileCheck2} />
      </div>

      <div className="rounded-xl border border-border bg-surface p-4 text-[12px] text-foreground-secondary">
        All values above come from this pack&apos;s canonical rows. The tabs alongside show PAYE anchors, contributions,
        ETI, earning classification, labour baselines and the release gates. Nothing on this page calculates payroll.
      </div>
    </div>
  );
}
