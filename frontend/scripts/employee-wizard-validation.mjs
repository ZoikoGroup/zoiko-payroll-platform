#!/usr/bin/env node
/**
 * Employee workflow validation (Update Employees / Send Template refactor).
 * Plain Node source checks, like the other scripts here: the workflows must
 * follow "select employees -> choose fields -> review -> act", only call the
 * write API from the final step, and keep the shared parts in one place.
 */
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const DIR = resolve(__dirname, "..", "src", "modules", "payroll", "Payroll_Employees");
const read = (f) => readFileSync(resolve(DIR, f), "utf-8");

let passed = 0;
const failures = [];
function check(name, fn) {
  try {
    if (fn() === false) failures.push(`${name}: assertion returned false`);
    else passed += 1;
  } catch (err) {
    failures.push(`${name}: ${err.message}`);
  }
}

const parts = read("EmployeeWizardParts.jsx");
const bulk = read("EmployeeBulkEditPanel.jsx");
const list = read("EmployeeListPage.jsx");
const table = read("EmployeeTable.jsx");

// ── Shared parts ────────────────────────────────────────────────────────────
for (const name of ["WizardSteps", "EmployeePicker", "FieldChecklist", "WizardFooter", "WizardError"]) {
  check(`EmployeeWizardParts exports ${name}`, () => new RegExp(`export function ${name}\\b`).test(parts));
}
check("step indicator marks the current step for assistive tech", () => parts.includes('aria-current={isCurrent ? "step" : undefined}'));
check("picker keeps hidden selections when filtering (merge, not replace)", () =>
  // Only visible rows produce adds/removes; hidden selected ids are untouched.
  /const added = \[\.\.\.nextVisibleSelection\]\.filter\(\(id\) => visibleIds\.has\(id\)/.test(parts)
  && /const removed = \[\.\.\.visibleIds\]/.test(parts));
check("picker applies selection changes as updaters (quick clicks are not lost)", () =>
  /function toggleRow[\s\S]*?onSelectionChange\(\(prev\) =>/.test(parts)
  && /function mergeVisible[\s\S]*?onSelectionChange\(\(prev\) =>/.test(parts));
check("EmployeeTable email column is opt-in", () => /showEmail = false/.test(table));

// ── Update Employees ────────────────────────────────────────────────────────
check("Update Employees uses the shared picker, steps and checklist", () =>
  ["EmployeePicker", "WizardSteps", "FieldChecklist", "WizardFooter"].every((n) => bulk.includes(`<${n}`)));
check("Update Employees step order: employees -> fields -> review", () => {
  const ids = [...bulk.matchAll(/\{ id: "(\w+)", label:/g)].map((m) => m[1]);
  return ids.join(",") === "employees,fields,review";
});
check("Update Employees cannot continue with no employees selected", () => bulk.includes("nextDisabled={employeeCount === 0}"));
check("bulkUpdateEmployees is only called from the review step's apply", () => {
  const calls = bulk.match(/await bulkUpdateEmployees\(/g) || [];
  const apply = bulk.slice(bulk.indexOf("async function handleApply"), bulk.indexOf("function startOver"));
  return calls.length === 1 && apply.includes("await bulkUpdateEmployees(");
});
check("Update Employees sends only the selected employees", () => bulk.includes("selectedEmployees.map((e) => e.id)"));
check("Update Employees has its own selection (does not mutate the list's)", () =>
  bulk.includes("useState(() => new Set(selectedIds || []))") && !/setSelectedIds/.test(bulk));
check("failures are read from the API's row.id shape", () => bulk.includes("f.row?.id"));
check("the old non-interactive scope buttons are gone", () => !bulk.includes("Selected employees ("));
check("result screen is not unmounted by the parent after saving", () => {
  const fn = list.slice(list.indexOf("function handleEmployeesBulkUpdated"), list.indexOf("function handleExportEmployees"));
  return !fn.includes('setActiveTab("list")');
});

// ── Send Template ───────────────────────────────────────────────────────────
const send = read("SendTemplateBuilder.jsx");
check("Send Template uses the shared picker (with email column), steps and checklist", () =>
  ["EmployeePicker", "WizardSteps", "FieldChecklist", "WizardFooter"].every((n) => send.includes(`<${n}`))
  && /<EmployeePicker[\s\S]*?showEmail/.test(send));
check("Send Template step order: employees -> form -> review", () => {
  const ids = [...send.matchAll(/\{ id: "(\w+)", label:/g)].map((m) => m[1]);
  return ids.join(",") === "employees,form,review";
});
check("the form is created only inside the final send", () => {
  const calls = send.match(/await createUpdateForm\(/g) || [];
  const fn = send.slice(send.indexOf("async function handleSend"), send.indexOf("function startOver"));
  return calls.length === 1 && fn.includes("await createUpdateForm(") && fn.includes("await sendUpdateForm(");
});
check("a retry reuses the form created by a failed attempt when nothing changed", () =>
  send.includes("created && created.signature === signature ? created.form : null"));
check("the form is sent only to selected employees who have an email", () =>
  send.includes("pickedIds.has(e.id)") && send.includes("recipients.map((e) => e.id)"));
check("Send Template cannot continue without a recipient", () => send.includes("nextDisabled={recipients.length === 0}"));
check("existing org-wide custom fields and Add field are kept", () =>
  send.includes("getCustomFields()") && send.includes("createCustomField("));
check("delivery outcomes (sent / not delivered / failed) are still shown", () =>
  ["sent", "not_delivered", "failed"].every((s) => send.includes(`resultList("${s}")`)));

// ── Employee List toolbar ───────────────────────────────────────────────────
for (const tab of ["bulk-import", "bulk-update", "send-template", "review-submissions"]) {
  check(`toolbar highlights the open "${tab}" view`, () => list.includes(`aria-pressed={activeTab === "${tab}"}`));
}

if (failures.length) {
  console.error(`employee-wizard-validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`employee-wizard-validation: ${passed} checks passed`);
