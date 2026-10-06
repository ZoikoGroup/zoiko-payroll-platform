import RatesTab from "../RatesTab";
import { IE_EMERGENCY_COMPONENT_KEYS } from "./ieComponentConfig";

// Emergency PAYE basis (IE-008/IE-031) and the reference single-person
// figures.
//
// The Emergency basis applies only when Revenue has issued no RPN for the
// employee. Two distinct treatments live here, and which one applies is
// decided by whether a PPSN was supplied — not by a payroll setting:
//
//   • PPSN supplied  — the prescribed initial standard-rate treatment,
//     stepped up by whole weeks of emergency employment.
//   • No PPSN         — the higher rate with no credit, for the whole period.
//
// The engine blocks rather than defaulting: a PPSN-supplied employee with
// no emergency week counter, or no recorded reason, stops the run.
export default function IEEmergencyTab({ pack, rates, onAddRate, onEditRate, onDeleteRate }) {
  const filtered = (rates || []).filter((r) => IE_EMERGENCY_COMPONENT_KEYS.includes(r.componentKey));
  return (
    <div className="space-y-3">
      <p className="text-xs text-foreground-muted">
        Emergency PAYE weekly cutoff, increment, week step and weekly tax credit (IE-008/IE-031),
        plus the reference single-person band and credit. Used only when Revenue has issued no
        RPN for the employee. The engine requires a recorded emergency reason and week counter
        and blocks rather than defaulting, and applies the higher rate with no credit when no
        PPSN was supplied.
      </p>
      <RatesTab
        pack={pack}
        rates={filtered}
        onAdd={onAddRate}
        onEdit={onEditRate}
        onDelete={onDeleteRate}
      />
    </div>
  );
}
