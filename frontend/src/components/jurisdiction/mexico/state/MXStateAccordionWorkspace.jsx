import { useState } from "react";
import { listMxIsnStates } from "../../../../service/superAdminService";
import { useLoad } from "../mxShared";
import MXStateAccordionRow from "./MXStateAccordionRow";

// Mexico's state Impuesto Sobre Nóminas surface (spec §15) — cloned from
// AUStateAccordionWorkspace.jsx, not generalised from it (the AU workspace is
// untouched). All 32 federal entities are listed up front; only a state the
// owner confirmed has an ISN pack (CDMX today), every other one is shown as
// unsupported with payroll BLOCKED (MX-045).
export default function MXStateAccordionWorkspace({ initialSelectedState = "" }) {
  const [expanded, setExpanded] = useState(initialSelectedState || null);
  const [data, error, loading, reload] = useLoad(() => listMxIsnStates(), []);
  const states = data || [];

  const supported = states.filter((s) => s.packs.length > 0).length;
  return (
    <div>
      <p className="mb-2 text-xs text-foreground-muted">
        Each state levies its own payroll tax (Impuesto Sobre Nóminas) as an employer liability, on a base independent
        of federal ISR and IMSS SBC. Only states with a certified, Active pack are supported — every other state is
        hard-blocked.
      </p>
      {!loading && (
        <p className="mb-4 text-xs font-semibold text-foreground" data-testid="mx-isn-summary">
          {states.length} federal entities · {supported} with an ISN pack · {states.length - supported} unsupported (payroll BLOCKED)
        </p>
      )}
      {error && <p role="alert" className="mb-3 text-[13px] text-error">{error}</p>}
      {loading ? (
        <p className="py-12 text-center text-xs text-foreground-disabled">Loading state configuration…</p>
      ) : (
        <div className="space-y-2">
          {states.map((state) => (
            <MXStateAccordionRow
              key={state.code} state={state}
              isExpanded={expanded === state.code}
              onToggle={() => setExpanded((prev) => (prev === state.code ? null : state.code))}
              onPackUpdated={reload}
            />
          ))}
        </div>
      )}
    </div>
  );
}
