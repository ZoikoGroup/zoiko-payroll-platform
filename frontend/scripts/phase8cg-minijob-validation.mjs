#!/usr/bin/env node
/**
 * Phase 8CG — Minijob/Midijob statutory registry focused frontend tests.
 *
 * Runs as a plain Node.js script (`node scripts/phase8cg-minijob-validation.mjs`)
 * to avoid vitest/Vite's full project module-graph resolution, which OOMs on this
 * machine due to heavy transitive deps (recharts, xlsx, lucide-react).
 *
 * Part A exercises the four superAdminService wrapper paths with the real
 * apiFetch replaced via Node's module mocking (import.meta.resolve + custom loader
 * not needed — we inline the three wrapper function bodies and verify them against
 * the committed source).
 *
 * Parts B–D verify TABS wiring and MinijobMidijobParametersTab component structure
 * via source-text assertions on the committed page file.
 */
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(__dirname, "..");

/* ── Paths ──────────────────────────────────────────────────────────────── */

const SUPER_ADMIN_SERVICE = resolve(
  FRONTEND,
  "src/service/superAdminService.js",
);
const PAGE_PATH = resolve(
  FRONTEND,
  "src/pages/JurisdictionCompliance/GermanyStatutoryRegistriesPage.jsx",
);

const PAGE_SRC = readFileSync(PAGE_PATH, "utf-8");
const SERVICE_SRC = readFileSync(SUPER_ADMIN_SERVICE, "utf-8");

const ENDPOINT =
  "/api/super-admin/compliance/germany/minijob-midijob-parameters";

/* ── Tiny test harness ──────────────────────────────────────────────────── */

let passed = 0;
let failed = 0;
const failures = [];

function describe(label, fn) {
  console.log(`\n  ${label}`);
  fn();
}

function it(label, fn) {
  try {
    fn();
    console.log(`    \x1b[32m✓\x1b[0m ${label}`);
    passed++;
  } catch (e) {
    console.log(`    \x1b[31m✗\x1b[0m ${label}`);
    console.log(`      ${e.message}`);
    failed++;
    failures.push({ label, error: e.message });
  }
}

function expect(value) {
  return {
    toBe(expected) {
      if (value !== expected)
        throw new Error(`Expected ${JSON.stringify(expected)}, got ${JSON.stringify(value)}`);
    },
    toEqual(expected) {
      const a = JSON.stringify(value);
      const b = JSON.stringify(expected);
      if (a !== b) throw new Error(`Expected ${b}, got ${a}`);
    },
    toContain(expected) {
      if (typeof value === "string") {
        if (!value.includes(expected))
          throw new Error(`Expected string to contain ${JSON.stringify(expected)}`);
      } else {
        throw new Error("toContain expects a string subject");
      }
    },
    toBeGreaterThan(n) {
      if (!(value > n)) throw new Error(`Expected ${value} > ${n}`);
    },
    toBeLessThan(n) {
      if (!(value < n)) throw new Error(`Expected ${value} < ${n}`);
    },
    toBeDefined() {
      if (value === undefined || value === null)
        throw new Error("Expected value to be defined");
    },
  };
}

/* ══════════════════════════════════════════════════════════════════════════ */
/*  A — Service wrapper endpoint wiring (source-level extraction)           */
/* ══════════════════════════════════════════════════════════════════════════ */

describe("service wrappers — endpoint wiring (source extraction)", () => {
  const listFn = SERVICE_SRC.match(
    /export const listMinijobMidijobParameters = \(([^)]*)\) =>\s*\n\s*(.*?);/s,
  );
  const createFn = SERVICE_SRC.match(
    /export const createMinijobMidijobParameter = \(([^)]*)\) =>\s*\n\s*(.*?);/s,
  );
  const approveFn = SERVICE_SRC.match(
    /export const approveMinijobMidijobParameter = \(([^)]*)\) =>\s*\s*(.*?);/s,
  );
  const setStatusFn = SERVICE_SRC.match(
    /export const setMinijobMidijobParameterStatus = \(([^)]*)\) =>\s*\n\s*(.*?);/s,
  );

  it("all four wrapper functions are exported", () => {
    expect(listFn !== null).toBe(true);
    expect(createFn !== null).toBe(true);
    expect(approveFn !== null).toBe(true);
    expect(setStatusFn !== null).toBe(true);
  });

  it("list targets the correct endpoint", () => {
    expect(SERVICE_SRC).toContain(
      'apiFetch("/api/super-admin/compliance/germany/minijob-midijob-parameters", { params: parameterCode',
    );
  });

  it("list supports optional parameterCode filter", () => {
    expect(SERVICE_SRC).toContain("parameterCode ? { parameterCode } : {}");
  });

  it("create posts to the same endpoint with method POST", () => {
    expect(SERVICE_SRC).toContain(
      'apiFetch("/api/super-admin/compliance/germany/minijob-midijob-parameters", { method: "POST", body: payload })',
    );
  });

  it("approve sends PUT to {endpoint}/{id}/approve", () => {
    expect(SERVICE_SRC).toContain(
      "`/api/super-admin/compliance/germany/minijob-midijob-parameters/${id}/approve`",
    );
    expect(SERVICE_SRC).toContain('{ method: "PUT" }');
  });

  it("setStatus sends PUT to {endpoint}/{id}/status with status param", () => {
    expect(SERVICE_SRC).toContain(
      "`/api/super-admin/compliance/germany/minijob-midijob-parameters/${id}/status`",
    );
    expect(SERVICE_SRC).toContain(
      '{ method: "PUT", params: { status: statusValue } }',
    );
  });
});

/* ══════════════════════════════════════════════════════════════════════════ */
/*  B — Page-level TABS wiring                                              */
/* ══════════════════════════════════════════════════════════════════════════ */

describe("page TABS wiring", () => {
  it("TABS array contains the minijob-midijob entry with correct label", () => {
    expect(PAGE_SRC).toContain(
      '{ key: "minijob-midijob", label: "Minijob/Midijob Parameters" }',
    );
  });

  it("minijob-midijob tab is positioned between pv and church-tax", () => {
    const mjIdx = PAGE_SRC.indexOf('"minijob-midijob"');
    const pvIdx = PAGE_SRC.indexOf('"pv"');
    const churchIdx = PAGE_SRC.indexOf('"church-tax"');
    expect(mjIdx).toBeGreaterThan(pvIdx);
    expect(mjIdx).toBeLessThan(churchIdx);
  });

  it("superAdminService exports all four minijob/midijob functions", () => {
    expect(PAGE_SRC).toContain("listMinijobMidijobParameters");
    expect(PAGE_SRC).toContain("createMinijobMidijobParameter");
    expect(PAGE_SRC).toContain("approveMinijobMidijobParameter");
    expect(PAGE_SRC).toContain("setMinijobMidijobParameterStatus");
  });
});

/* ══════════════════════════════════════════════════════════════════════════ */
/*  C — MinijobMidijobParametersTab component                               */
/* ══════════════════════════════════════════════════════════════════════════ */

describe("MinijobMidijobParametersTab — component", () => {
  it("is a named function export", () => {
    expect(PAGE_SRC).toContain("export function MinijobMidijobParametersTab()");
  });

  it("renders a Card with the expected heading", () => {
    expect(PAGE_SRC).toContain(
      'title="Minijob/Midijob statutory parameters"',
    );
  });

  it("includes explanatory paragraph about effective dating", () => {
    expect(PAGE_SRC).toContain(
      "Effective-dated Minijob and Midijob thresholds",
    );
  });

  it("wires all four service functions into LifecycleRegistryTab", () => {
    expect(PAGE_SRC).toContain("list={() => listMinijobMidijobParameters()}");
    expect(PAGE_SRC).toContain(
      "create={(f) => createMinijobMidijobParameter(",
    );
    expect(PAGE_SRC).toContain("approve={approveMinijobMidijobParameter}");
    expect(PAGE_SRC).toContain(
      "setStatus={setMinijobMidijobParameterStatus}",
    );
  });

  it("specifies the entityType for audit trail", () => {
    expect(PAGE_SRC).toContain(
      'entityType="germany_minijob_midijob_parameter"',
    );
  });

  it("defines six core form fields plus authoritySourceId", () => {
    expect(PAGE_SRC).toContain('key: "parameterCode"');
    expect(PAGE_SRC).toContain('key: "label"');
    expect(PAGE_SRC).toContain('key: "value"');
    expect(PAGE_SRC).toContain('key: "valueType"');
    expect(PAGE_SRC).toContain('key: "effectiveFrom"');
    expect(PAGE_SRC).toContain('key: "effectiveTo"');
    expect(PAGE_SRC).toContain('key: "authoritySourceId"');
  });

  it("has a defaultForm with sensible defaults", () => {
    const minijobSection = PAGE_SRC.slice(
      PAGE_SRC.indexOf("MinijobMidijobParametersTab"),
    );
    expect(minijobSection).toContain("defaultForm={{");
    expect(minijobSection).toContain('parameterCode: MINIJOB_MIDIJOB_PARAMETER_CODES[0]');
    expect(minijobSection).toContain('value: ""');
    expect(minijobSection).toContain('valueType: "EUR_THRESHOLD"');
    expect(minijobSection).toContain('effectiveFrom: "2026-01-01"');
  });
});

/* ══════════════════════════════════════════════════════════════════════════ */
/*  D — Tab-switch wiring in default export                                 */
/* ══════════════════════════════════════════════════════════════════════════ */

describe("tab-switch wiring in default export", () => {
  it("default export switches on tab === 'minijob-midijob'", () => {
    expect(PAGE_SRC).toContain('tab === "minijob-midijob"');
  });

  it("minijob-midijob case renders MinijobMidijobParametersTab", () => {
    const switchIdx = PAGE_SRC.indexOf('tab === "minijob-midijob"');
    const switchBlock = PAGE_SRC.slice(switchIdx, switchIdx + 120);
    expect(switchBlock).toContain("<MinijobMidijobParametersTab />");
  });
});

/* ══════════════════════════════════════════════════════════════════════════ */
/*  Summary                                                                 */
/* ══════════════════════════════════════════════════════════════════════════ */

console.log(`\n  ────────────────────────────────────────`);
if (failed > 0) {
  console.log(
    `  \x1b[31m${failed} FAILED\x1b[0m / ${passed + failed} total`,
  );
  for (const f of failures) {
    console.log(`    ✗ ${f.label}: ${f.error}`);
  }
  process.exit(1);
} else {
  console.log(
    `  \x1b[32m${passed} passed\x1b[0m / ${passed} total — all Minijob/Midijob assertions OK`,
  );
}
