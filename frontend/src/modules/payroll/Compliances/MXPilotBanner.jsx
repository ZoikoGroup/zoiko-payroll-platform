import { useEffect, useState } from "react";
import { getMxPilotStatus } from "../../../service/payrollService";

// Phase 10e: a pilot organisation's Mexico output is NON-BINDING. Shown on its
// Mexico screens while the pilot grant is active; nothing renders otherwise
// (including when Mexico is closed for this organisation).
export default function MXPilotBanner() {
  const [status, setStatus] = useState(null);
  useEffect(() => {
    let active = true;
    getMxPilotStatus().then((s) => active && setStatus(s)).catch(() => active && setStatus(null));
    return () => { active = false; };
  }, []);
  if (!status?.pilot) return null;
  return (
    <div role="status" data-testid="mx-pilot-banner"
      className="rounded-lg border border-warning bg-warning/10 p-3 text-[12px] text-foreground">
      <p className="font-semibold">PILOT — parallel run. Nothing produced here is binding.</p>
      <p className="mt-1 text-foreground-muted">
        {status.active ? `Pilot grant active until ${String(status.expiresAt).slice(0, 10)}. ` : "The pilot grant is no longer active. "}
        Rules: {status.rules.join("; ")}.
      </p>
    </div>
  );
}
