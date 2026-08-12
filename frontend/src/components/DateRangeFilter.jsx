import { useState, useEffect } from "react";
import { Calendar } from "lucide-react";
import { DATE_RANGE_PRESETS, resolveDateRange } from "../utils/dateRangePresets";

// Shared by every Super Admin module that filters by date (Finance,
// Reports, Dashboard) — one implementation instead of three copies.
// `value` is { preset, startDate, endDate }; `onChange` receives the same
// shape with startDate/endDate always resolved to concrete ISO dates.
export default function DateRangeFilter({ value, onChange, className = "" }) {
  const preset = value?.preset || "thisMonth";
  const [customStart, setCustomStart] = useState(value?.startDate || "");
  const [customEnd, setCustomEnd] = useState(value?.endDate || "");

  useEffect(() => {
    if (preset === "custom") {
      setCustomStart(value?.startDate || "");
      setCustomEnd(value?.endDate || "");
    }
  }, [preset]); // eslint-disable-line react-hooks/exhaustive-deps

  function handlePresetChange(presetId) {
    if (presetId === "custom") {
      onChange({ preset: presetId, startDate: customStart, endDate: customEnd });
      return;
    }
    onChange({ preset: presetId, ...resolveDateRange(presetId) });
  }

  return (
    <div className={`flex flex-wrap items-center gap-2 ${className}`}>
      <div className="relative">
        <select
          value={preset}
          onChange={(e) => handlePresetChange(e.target.value)}
          className="appearance-none rounded-lg border border-slate-300 dark:border-[#38312D] bg-white dark:bg-[#221D1A] py-2 pl-3 pr-8 text-sm text-slate-700 dark:text-[#F0EDE8] focus:outline-none focus:ring-2 focus:ring-orange-500/30"
        >
          {DATE_RANGE_PRESETS.map((p) => (
            <option key={p.id} value={p.id}>{p.label}</option>
          ))}
        </select>
        <Calendar size={14} className="pointer-events-none absolute right-2.5 top-1/2 -translate-y-1/2 text-slate-400 dark:text-[#9E9690]" />
      </div>
      {preset === "custom" && (
        <div className="flex items-center gap-1.5">
          <input
            type="date"
            value={customStart}
            onChange={(e) => setCustomStart(e.target.value)}
            className="rounded-lg border border-slate-300 dark:border-[#38312D] bg-white dark:bg-[#221D1A] px-2.5 py-2 text-sm text-slate-700 dark:text-[#F0EDE8] focus:outline-none focus:ring-2 focus:ring-orange-500/30"
          />
          <span className="text-sm text-slate-400 dark:text-[#9E9690]">to</span>
          <input
            type="date"
            value={customEnd}
            onChange={(e) => setCustomEnd(e.target.value)}
            className="rounded-lg border border-slate-300 dark:border-[#38312D] bg-white dark:bg-[#221D1A] px-2.5 py-2 text-sm text-slate-700 dark:text-[#F0EDE8] focus:outline-none focus:ring-2 focus:ring-orange-500/30"
          />
          <button
            type="button"
            onClick={() => onChange({ preset: "custom", startDate: customStart, endDate: customEnd })}
            disabled={!customStart || !customEnd}
            className="rounded-lg bg-orange-500 px-3 py-2 text-sm font-medium text-white hover:bg-orange-600 disabled:opacity-50"
          >
            Apply
          </button>
        </div>
      )}
    </div>
  );
}
