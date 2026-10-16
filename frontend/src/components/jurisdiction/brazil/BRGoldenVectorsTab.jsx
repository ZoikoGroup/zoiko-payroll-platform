import { useState } from "react";
import { runBrGoldenCheck } from "../../../service/superAdminService";
import { Messages, Table, card, btnPrimary, useAction } from "./brShared";

// Golden vectors (ZP-BR-ENG-001) — runs the backend's golden-check, which
// replays the committed vectors in tests/fixtures/br_golden/ against the Brazil
// engine and records a certification run. Nothing is edited; a failure means
// the engine output does not match a vector's expected values. The check is
// global (not per organisation), mirroring the other jurisdictions.
export default function BRGoldenVectorsTab() {
  const [result, setResult] = useState(null);
  const { run, error, notice, busy } = useAction();

  const check = () => run(async () => setResult(await runBrGoldenCheck()));

  const failures = Array.isArray(result?.failure_details) ? result.failure_details : [];
  const failureRows = failures.flatMap((f) =>
    (f.diffs && f.diffs.length ? f.diffs : [{ field: "—", expected: "—", actual: "—" }])
      .map((d) => ({ case: f.case, field: d.field, expected: d.expected, actual: d.actual })));

  return (
    <div className="flex flex-col gap-4">
      <Messages error={error} notice={notice} />
      <div className={card}>
        <p className="mb-3 text-[12px] text-foreground-muted">
          Replays the committed golden vectors in tests/fixtures/br_golden/ against the Brazil engine. Nothing is
          edited; a failure means the engine output does not match the vector&apos;s expected values.
        </p>
        <button type="button" className={btnPrimary} disabled={busy} onClick={check}>Run golden check</button>
      </div>
      {result && (
        <div className={card}>
          <h3 className="mb-2 text-[14px] font-semibold text-foreground">
            Result — {result.status ?? "—"}
            {result.total_cases != null
              ? ` — ${result.passed_cases ?? 0} / ${result.total_cases} passed${result.failed_cases ? `, ${result.failed_cases} failed` : ""}`
              : ""}
          </h3>
          <Table rows={failureRows} empty="No failing vectors — every vector passed." columns={[
            { key: "case", label: "Vector" },
            { key: "field", label: "Field" },
            { key: "expected", label: "Expected" },
            { key: "actual", label: "Actual" },
          ]} />
        </div>
      )}
    </div>
  );
}
