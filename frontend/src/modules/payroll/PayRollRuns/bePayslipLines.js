// Belgium payslip lines (ZP-BE-ENG-001 spec §11; Block B3), read straight from
// a payslip's frozen be_calculation_snapshot. Nothing is computed here: every
// amount is the engine's own figure, and the employee lines, the employer
// contribution composition (base / special / holiday / reduction) and the
// obligation deltas are kept apart. The English text is the operator view;
// `key` is the content key the nl / fr / de payslip labels use (D10).

const EMPLOYER_LINE_LABELS = {
  BASE: ["Employer ONSS — base", "be.payslip.employer.onss.base"],
  WAGE_MODERATION: ["Employer ONSS — special (wage moderation)", "be.payslip.employer.onss.wage_moderation"],
  SPECIAL_160: ["Employer ONSS — special (workforce test)", "be.payslip.employer.onss.special_workforce"],
};
const OBLIGATION_LABELS = {
  HOLIDAY_FUND_QUARTERLY: ["Holiday fund contribution — holiday (manual workers)", "be.payslip.obligation.holiday_fund"],
  HOLIDAY_FUND_ANNUAL_DEBIT: ["Holiday fund annual debit — holiday", "be.payslip.obligation.holiday_fund_annual"],
};

const nonZero = ([, , amount]) => amount !== undefined && amount !== null && Number(amount) !== 0;

export function beEmployeeLines(snapshot) {
  const s = snapshot || {};
  const exceptional = Object.entries(s.be_withholding_exceptional || {}).map(([group, line]) => [
    `Professional withholding — exceptional (${group.toLowerCase().replace(/_/g, " ")})`,
    `be.payslip.withholding.exceptional.${group.toLowerCase()}`, line?.withholding]);
  return [
    ["Employee ONSS — base", "be.payslip.employee.onss.base", s.be_onss_employee],
    ["Social work bonus — reduction", "be.payslip.employee.onss.work_bonus", s.be_social_work_bonus],
    ["Employee ONSS after reduction", "be.payslip.employee.onss.total", s.be_employee_total],
    ["Professional withholding — regular", "be.payslip.withholding.regular", s.be_withholding_regular],
    ["Fiscal work bonus — reduction (already in the withholding)", "be.payslip.withholding.work_bonus",
      s.be_fiscal_work_bonus],
    ...exceptional,
  ].filter(nonZero).map(([label, key, amount]) => ({ label, key, amount }));
}

export function beEmployerLines(snapshot) {
  const s = snapshot || {};
  const lines = Object.entries(s.be_onss_employer || {}).map(([name, amount]) => {
    const [label, key] = EMPLOYER_LINE_LABELS[name] || [`Employer ONSS — special (${name})`, `be.payslip.employer.${name}`];
    return [label, key, amount];
  });
  const funds = Object.entries(s.be_funds || {}).map(([name, amount]) => [
    `Employer fund — special (${name.toLowerCase().replace(/_/g, " ")})`, `be.payslip.employer.fund.${name.toLowerCase()}`,
    amount]);
  return [
    ...lines,
    ...funds,
    ["Occupational pension — special", "be.payslip.employer.pension_special", s.be_pension_special],
  ].filter(nonZero).map(([label, key, amount]) => ({ label, key, amount }));
}

export function beObligationLines(snapshot) {
  return Object.entries(snapshot?.obligationDeltas || {}).map(([name, amount]) => {
    const [label, key] = OBLIGATION_LABELS[name] || [name, `be.payslip.obligation.${name.toLowerCase()}`];
    return { label, key, amount };
  }).filter((r) => Number(r.amount) !== 0);
}

export function beBaseLines(snapshot) {
  return Object.entries(snapshot?.bases || {}).map(([name, amount]) => ({
    label: name.toLowerCase().replace(/_/g, " "), key: `be.payslip.base.${name.toLowerCase()}`, amount,
  }));
}
