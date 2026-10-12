import useConfiguredUSStates from "./useConfiguredUSStates";
import { inputClass, labelClass } from "../../../../components/jurisdiction/constants";

// Shared "which pack am I looking at" selector for the Organizations /
// Versions / Audit sections — Federal plus every REAL configured state
// (from useConfiguredUSStates, same source as Overview/State-District),
// never a hardcoded 50-state list.
export default function ScopePicker({ scope, onChange }) {
  const { states } = useConfiguredUSStates();
  return (
    <div className="mb-4 max-w-xs">
      <label className={labelClass}>Viewing</label>
      <select className={inputClass} value={scope} onChange={(e) => onChange(e.target.value)}>
        <option value="">Federal</option>
        {states.map((s) => <option key={s} value={s}>{s}</option>)}
      </select>
    </div>
  );
}
