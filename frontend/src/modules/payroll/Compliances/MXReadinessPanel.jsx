import MXEmployerReadiness from "../../../components/jurisdiction/mexico/employer/MXEmployerReadiness";
import { ReadinessDateBar } from "../../../components/jurisdiction/mexico/employer/employerShared";

// Panel H for the organisation: a date bar (your local date by default, any
// date via the picker) whose value is sent as `on` with the readiness call.
export default function MXReadinessPanel({ on, setOn, readiness, employerId }) {
  const mine = readiness?.employers?.find((e) => e.employerId === employerId);
  return (
    <div className="flex flex-col gap-3">
      <ReadinessDateBar on={on} onChange={setOn} />
      {mine ? <MXEmployerReadiness readiness={mine} gates={readiness.gates} /> : null}
    </div>
  );
}
