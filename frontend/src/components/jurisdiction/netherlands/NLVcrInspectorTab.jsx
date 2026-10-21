import WorkerDataLocked from "../../WorkerDataLocked";

// VCR inspector (NL-012). ZP-PRIV: the committed VCR series is one employee's
// cumulative wages — worker-level data that needs a live, organization-
// approved Support Access grant. The Super Admin route is retired.
export default function NLVcrInspectorTab() {
  return <WorkerDataLocked variant="support" />;
}
