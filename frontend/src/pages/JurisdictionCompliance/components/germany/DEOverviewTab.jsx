import PackOverviewSummary from "../../../../components/jurisdiction/PackOverviewSummary";
import { useLoad } from "../../../../components/jurisdiction/japan/jpFormat";
import { getGermanyPackContributions, getGermanyWageTaxTariff } from "../../../../service/superAdminService";
import DEOverviewDashboard from "./DEOverviewDashboard";
import { GERMANY_TAB_ALIASES, loadPapWarning } from "./deShared";

// Germany Overview on the shared layout: the shared pack summary (status
// chips, the four summary cards, Needs attention), with the cards counted from
// Germany's own Contributions view and tariff (the pack has no generic slab
// rows), the wage-tax warning under Needs attention, and the existing German
// area cards below as quick links into the new tabs. Counts only.

function countStats(view, tariff) {
  if (!view) {
    return ["Employee deductions", "Employer contributions", "Parameters & thresholds", "Tax zones"]
      .map((label) => ({ label, value: "…", hint: "loading" }));
  }
  const rows = view.sections.flatMap((s) => s.rows);
  const engine = (list) => list.filter((r) => r.origin === "engine").length;
  const employee = rows.filter((r) => r.employeeRatePct != null);
  const employer = rows.filter((r) => r.employerRatePct != null);
  const parameters = rows.filter((r) => r.employeeRatePct == null && r.employerRatePct == null);
  const current = tariff?.versions?.find((v) => v.inForceToday);
  return [
    { label: "Employee deductions", value: employee.length, hint: `${engine(employee)} built into the engine` },
    { label: "Employer contributions", value: employer.length, hint: `${engine(employer)} built into the engine` },
    { label: "Parameters & thresholds", value: parameters.length, hint: `${engine(parameters)} built into the engine` },
    { label: "Tax zones", value: current ? current.zones.length : "—", hint: current ? `§32a ${current.taxYear}, not BMF-certified` : "no tariff in force" },
  ];
}

export default function DEOverviewTab({ pack, refreshKey, onNavigateTab }) {
  const [view] = useLoad(() => getGermanyPackContributions(pack.id));
  const [tariff] = useLoad(getGermanyWageTaxTariff);
  const [warning] = useLoad(loadPapWarning);
  return (
    <div className="mb-5 space-y-5" data-testid="de-overview">
      <PackOverviewSummary pack={pack} refreshKey={refreshKey} stats={countStats(view, tariff)} attention={[warning]} />
      <DEOverviewDashboard onSelectSection={(key) => onNavigateTab(GERMANY_TAB_ALIASES[key] || key)} />
    </div>
  );
}
