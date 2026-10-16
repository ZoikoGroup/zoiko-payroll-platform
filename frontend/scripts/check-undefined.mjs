// Fails when any file under src/ uses a name that is never defined or
// imported (ESLint no-undef / react/jsx-no-undef).
//
// `vite build` does NOT catch this: an undefined JSX component compiles fine
// and only throws a ReferenceError when the page renders. That is exactly how
// commit 9fc1a36 (App.jsx used <NLStatutoryPage/> without importing it)
// passed CI and blanked every production page until hotfix PR #93.
//
// Only these two rules gate the build; the project's other existing lint
// findings stay advisory (`npm run lint`).
import { ESLint } from "eslint";

const GATED_RULES = new Set(["no-undef", "react/jsx-no-undef"]);

const eslint = new ESLint();
const results = await eslint.lintFiles(["src"]);

const findings = [];
for (const result of results) {
  for (const message of result.messages) {
    if (GATED_RULES.has(message.ruleId)) {
      findings.push(`${result.filePath}:${message.line}:${message.column}  ${message.message}  (${message.ruleId})`);
    }
  }
}

if (findings.length > 0) {
  console.error(`Undefined names found — these crash the page at runtime even though the build passes:\n`);
  for (const line of findings) console.error(`  ${line}`);
  console.error(`\n${findings.length} finding(s). Import or define each name before merging.`);
  process.exit(1);
}
console.log(`check-undefined: ${results.length} files, no undefined names.`);
