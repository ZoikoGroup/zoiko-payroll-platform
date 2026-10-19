import { openMxAguinaldoRun } from "../../../service/payrollService";
import { useAction } from "../../../components/jurisdiction/mexico/mxShared";
import { MiniForm, Panel } from "../../../components/jurisdiction/mexico/employer/employerShared";

// Aguinaldo run (ZP-MX-ENG-001 §17, Phase 9b): one AGUINALDO run per year,
// paid within that year. Each payslip is the labour-policy days (never below
// the statutory minimum) × daily salary × the transcribed proportion for the
// part of the year employed; its withholding is the transcribed special-pay
// rule — never the ordinary tariff. Until those rules are transcribed (S24 /
// S25 / S26) every payslip of the run is blocked, with the reason shown.
export default function MXAguinaldoRunPanel() {
  const { run, error, notice, busy } = useAction(null);
  return (
    <Panel title="Aguinaldo run" testId="mx-aguinaldo-run"
      hint="Creates the year's AGUINALDO run for your Mexican employees; review and approve it in Payroll Runs like any run.">
      <MiniForm
        submitLabel="Open aguinaldo run" busy={busy} error={error} notice={notice}
        fields={[
          { key: "year", label: "Year", required: true },
          { key: "payDate", label: "Pay date", type: "date", required: true },
        ]}
        onSubmit={(s) => run(async () => {
          const out = await openMxAguinaldoRun(Number(s.year), s.payDate);
          return out;
        }, "Aguinaldo run created — open it from Payroll Runs.")}
      />
    </Panel>
  );
}
