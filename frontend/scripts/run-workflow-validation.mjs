// Payroll run workflow UI stays true to the backend.
//
// The progress panel / run detail tracker (PayRollRuns/runWorkflow.js) shows
// the run lifecycle and explains each step. This fails when:
//   * the frontend status order drifts from backend PAYROLL_STATUS_ORDER;
//   * a status has no guidance, or the guidance names a dialog title / button
//     label that ApprovalDialog.jsx no longer shows;
//   * the "who may act" roles drift from get_current_payroll_operator;
//   * a screen re-declares its own copy of the status order.
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const FRONTEND = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const SRC = join(FRONTEND, "src");
const BACKEND = resolve(FRONTEND, "..", "backend", "app");
const read = (p) => readFileSync(p, "utf-8").replace(/\r\n/g, "\n");

let passed = 0;
const failures = [];
function check(name, fn) {
  try {
    const ok = fn();
    if (ok === false) throw new Error("assertion returned false");
    passed += 1;
  } catch (err) {
    failures.push(`${name}: ${err.message}`);
  }
}
const assert = (cond, msg) => { if (!cond) throw new Error(msg); };

// Backend order: PAYROLL_STATUS_ORDER = [PayrollStatus.X, ...] + enum values.
const models = read(join(BACKEND, "modules", "payroll", "models.py"));
const enumBlock = models.match(/class PayrollStatus\(str, enum\.Enum\):([\s\S]*?)\n\n/)[1];
const enumValues = Object.fromEntries([...enumBlock.matchAll(/(\w+)\s*=\s*"([^"]+)"/g)].map((m) => [m[1], m[2]]));
const orderBlock = models.match(/^PAYROLL_STATUS_ORDER = \[([\s\S]*?)\]/m)[1];
const backendOrder = [...orderBlock.matchAll(/PayrollStatus\.(\w+)/g)].map((m) => enumValues[m[1]]);

const service = read(join(SRC, "service", "payrollService.js"));
const frontendOrder = JSON.parse(service.match(/export const PAYROLL_STATUS_ORDER = (\[[^\]]*\])/)[1]);
const workflow = read(join(SRC, "modules", "payroll", "PayRollRuns", "runWorkflow.js"));
const dialog = read(join(SRC, "modules", "payroll", "PayRollRuns", "ApprovalDialog.jsx"));
const table = read(join(SRC, "modules", "payroll", "PayRollRuns", "RunsTable.jsx"));

check("frontend status order equals backend PAYROLL_STATUS_ORDER", () => {
  assert(backendOrder.length === 6, `backend order parsed as ${JSON.stringify(backendOrder)}`);
  assert(JSON.stringify(frontendOrder) === JSON.stringify(backendOrder),
    `frontend ${JSON.stringify(frontendOrder)} != backend ${JSON.stringify(backendOrder)}`);
});

check("runWorkflow.js uses the shared order instead of its own copy", () =>
  /import \{ PAYROLL_STATUS_ORDER \} from "..\/..\/..\/service\/payrollService"/.test(workflow)
  && !/export const PAYROLL_STATUS_ORDER = \[/.test(workflow));

check("every status has guidance (meaning; how-to and action except the final status)", () => {
  for (const status of backendOrder) {
    const block = workflow.match(new RegExp(`\\n  ${status}: \\{([\\s\\S]*?)\\n  \\},`));
    assert(block, `no STEP_GUIDE entry for ${status}`);
    assert(/meaning:/.test(block[1]), `${status} has no meaning`);
    const last = status === backendOrder[backendOrder.length - 1];
    assert(last ? /action: null/.test(block[1]) : /action: "/.test(block[1]), `${status} action wrong`);
  }
});

check("guidance quotes the real dialog titles and confirm buttons", () => {
  for (const [title, verb] of [["Approve Payroll Run", "Approve"], ["Authorize Payroll Run", "Authorize"],
    ["Mark Payroll Run as Paid", "Mark as Paid"]]) {
    assert(dialog.includes(`title: "${title}"`) && dialog.includes(`verb: "${verb}"`), `ApprovalDialog lost "${title}"/"${verb}"`);
    assert(dialog.includes("`Confirm ${meta.verb}`"), "ApprovalDialog confirm label changed");
    assert(workflow.includes(title) && workflow.includes(`Confirm ${verb}`), `guidance doesn't quote "${title}" / "Confirm ${verb}"`);
  }
});

check("the Actions column still labels the advance button \"Advance to <status>\"", () =>
  table.includes("`Advance to ${nextStatusLabel(run.status)}`") && workflow.includes("Advance (✓, \\\"Advance to Review\\\")"));

check("operator roles match backend get_current_payroll_operator", () => {
  const deps = read(join(BACKEND, "core", "dependencies.py"));
  const fn = deps.match(/def get_current_payroll_operator[\s\S]*?if role not in \(([^)]*)\)/);
  assert(fn && /ROLE_ORG_ADMIN/.test(fn[1]) && /ROLE_PAYROLL_ADMIN/.test(fn[1]) && fn[1].split(",").filter((x) => x.trim()).length === 2,
    "backend operator roles changed");
  assert(/PAYROLL_OPERATOR_ROLES = \[ROLES\.ORG_ADMIN, ROLES\.PAYROLL_ADMIN\]/.test(workflow), "frontend operator roles changed");
});

check("no Payroll Runs screen re-declares the status order", () => {
  const dir = join(SRC, "modules", "payroll", "PayRollRuns");
  const offenders = readdirSync(dir).filter((f) => statSync(join(dir, f)).isFile() && /\.(jsx?|mjs)$/.test(f))
    .filter((f) => /\["Draft",\s*"Review",\s*"Approved",\s*"Authorized"/.test(read(join(dir, f))));
  assert(offenders.length === 0, `own copy in ${offenders.join(", ")}`);
});

if (failures.length) {
  console.error(`run-workflow-validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`run-workflow-validation: ${passed} checks passed`);
