import BREmployerReadiness from "../../../components/jurisdiction/brazil/employer/BREmployerReadiness";
import { ReadinessDateBar } from "../../../components/jurisdiction/brazil/employer/brEmployerShared";

// Readiness for the organisation: a date bar (your local date by default, any
// date via the picker) whose value is sent as `on` with the readiness call.
export default function BRReadinessPanel({ on, setOn, readiness, employerId }) {
  const mine = readiness?.employers?.find((e) => e.employerId === employerId);
  return (
    <div className="flex flex-col gap-3">
      <ReadinessDateBar on={on} onChange={setOn} />
      {mine ? <BREmployerReadiness readiness={mine} gates={readiness.gates} /> : null}
    </div>
  );
}
