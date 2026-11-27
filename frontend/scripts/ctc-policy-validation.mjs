#!/usr/bin/env node
/**
 * Payroll Policy: "CTC includes employer contributions (India)" switch.
 *
 * The rule lives in the backend (service._india_ctc_monthly_gross, policy
 * ctc_includes_employer_contributions). These checks prove the Policy page
 * shows the switch, explains both states with a worked example, asks before
 * changing pay, and saves the right field. Checked by source.
 */
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const page = readFileSync(resolve(__dirname, "..", "src", "modules", "payroll", "PayrollPolicy", "PayrollPolicyPage.jsx"), "utf-8");

let passed = 0;
const failures = [];
const check = (name, ok) => (ok ? (passed += 1) : failures.push(name));

check("switch is on the Policy page", page.includes("CTC includes employer contributions (India)"));
check("switch reads the policy field", page.includes("checked={!!policy.ctcIncludesEmployerContributions}"));
check("switch saves the policy field", page.includes("handleSaveGeneral({ ctcIncludesEmployerContributions: next })"));
check("changing pay asks first", page.includes("if (window.confirm(msg)) handleSaveGeneral({ ctcIncludesEmployerContributions: next })"));
check("both states explained with an example", page.includes("gross ₹98,200 + employer PF ₹1,800")
  && page.includes("gross ₹1,00,000 + employer PF ₹1,800"));
check("says approved payslips never change", page.includes("approved payslips never change"));

if (failures.length) {
  console.error(`ctc-policy validation: ${failures.length} failed, ${passed} passed`);
  for (const f of failures) console.error(`  ✗ ${f}`);
  process.exit(1);
}
console.log(`ctc-policy validation: ${passed} checks passed`);
