// Netherlands payslip lines (NL-048), read straight from a payslip's frozen
// nl_calculation_snapshot — employee deductions and employer cost kept apart.
// Shared by the run breakdown and the payslip stub; nothing is computed here.
export function nlEmployeeLines(snapshot) {
  const t = snapshot?.totals || {};
  return [
    ["Loonheffing (wage tax)", t.wageTax],
    ["Pension (employee share)", t.pensionEmployee],
    ["Zvw contribution (employee)", t.zvwEmployee],
    ["WGA premium recovered (Whk)", t.whkEmployee],
  ].filter(([, v]) => Number(v) > 0);
}

export function nlEmployerLines(snapshot) {
  const ei = snapshot?.employeeInsurance || {};
  const t = snapshot?.totals || {};
  return [
    [`AWf — unemployment (${ei.awfClass || "class n/a"} rate)`, ei.awf],
    ["Aof — disability fund", ei.aof],
    ["Wko — childcare", ei.wko],
    ["Whk — return-to-work fund", ei.whk],
    ["Zvw employer levy", snapshot?.zvw?.employerLevy],
    ["Pension (employer share)", t.pensionEmployer],
  ].filter(([, v]) => Number(v) > 0);
}
