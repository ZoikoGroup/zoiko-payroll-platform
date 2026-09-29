#!/usr/bin/env node
/**
 * Attendance service passthrough validation.
 *
 * Regression coverage for three fields that were produced by the backend and
 * read by AttendancePage.jsx but silently dropped by the payrollService
 * wrappers, so the UI never saw them:
 *
 *   1. firstDate/lastDate  -> History tab working-days span always read 0
 *   2. totals              -> Summary stat cards always read 0
 *   3. search              -> server-side employee search never reached the
 *                             server, so the box filtered nothing
 *
 * Runs as a plain Node script (like phase8cg-minijob-validation.mjs) because
 * vitest/Vite's module-graph resolution OOMs on this machine. Unlike that
 * script's source-text assertions, this one EVALUATES the real wrapper bodies
 * against a stub `api`, so it fails if the passthrough regresses even when the
 * source text still "looks" right.
 */
import { readFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = dirname(fileURLToPath(import.meta.url));
const FRONTEND = resolve(__dirname, "..");

const SERVICE_PATH = resolve(FRONTEND, "src/service/payrollService.js");
const PAGE_PATH = resolve(
  FRONTEND,
  "src/modules/payroll/Attendance/AttendancePage.jsx",
);

const SERVICE_SRC = readFileSync(SERVICE_PATH, "utf-8");
const PAGE_SRC = readFileSync(PAGE_PATH, "utf-8");

/* ── Tiny test harness ──────────────────────────────────────────────── */

let passed = 0;
let failed = 0;
const failures = [];

// `it` and `describe` register onto a queue that is awaited in order below.
// A synchronous try/catch would miss a rejected promise from an async test:
// the test would print as passing and then crash the process as an unhandled
// rejection, which hides which assertion actually failed.
//
// `describe` pushes its header first and then registers its `it`s
// immediately, so a suite's tests always follow its own header instead of
// landing at the end of the queue. Suite bodies are therefore synchronous.
const queue = [];

function describe(label, fn) {
  queue.push(async () => {
    console.log(`\n  ${label}`);
  });
  fn();
}

function it(label, fn) {
  queue.push(async () => {
    try {
      await fn();
      console.log(`    \x1b[32mo\x1b[0m ${label}`);
      passed++;
    } catch (e) {
      console.log(`    \x1b[31mx\x1b[0m ${label}`);
      console.log(`      ${e.message}`);
      failed++;
      failures.push({ label, error: e.message });
    }
  });
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
      if (typeof value !== "string")
        throw new Error("toContain expects a string subject");
      if (!value.includes(expected))
        throw new Error(`Expected source to contain ${JSON.stringify(expected)}`);
    },
    toBeDefined() {
      if (value === undefined || value === null)
        throw new Error("Expected value to be defined");
    },
    toBeNull() {
      if (value !== null)
        throw new Error(`Expected null, got ${JSON.stringify(value)}`);
    },
  };
}

/* ── Load the real wrapper bodies and evaluate them against a stub api ── */

// Slice from the exported declaration to the end of the statement. The
// summary wrapper's parameter list spans multiple lines, so a single-line
// match would not find it.
function extractFunction(name) {
  const marker = `export const ${name} = `;
  const start = SERVICE_SRC.indexOf(marker);
  if (start === -1) throw new Error(`Could not find ${name} in payrollService.js`);
  const end = SERVICE_SRC.indexOf("\n};", start);
  if (end === -1) throw new Error(`Unterminated ${name} in payrollService.js`);
  return SERVICE_SRC.slice(start, end + 3).replace(/^export const /, "const ");
}

// `api` is a module-scope import in the real file; supplying it as a function
// parameter of the same name is what makes these bodies executable in isolation.
function loadWrapper(name) {
  const body = extractFunction(name);
  const factory = new Function("api", `${body}\nreturn { ${name} };`);
  return factory;
}

// Records what was requested so a test can assert on the wire parameters,
// not just the response mapping.
function stubApi(response) {
  const calls = [];
  const api = {
    get: async (path, opts) => {
      calls.push({ path, params: opts?.params });
      if (response instanceof Error) throw response;
      return response;
    },
  };
  return { api, calls };
}

/* ── getAttendanceRecordsPaginated ──────────────────────────────────── */

const PAGE_RESPONSE = {
  items: [{ id: 1 }],
  total: 4312,
  limit: 1,
  offset: 0,
  hasMore: true,
  firstDate: "2026-01-05",
  lastDate: "2026-09-29",
};

describe("getAttendanceRecordsPaginated — date span passthrough", () => {
  it("forwards firstDate from the server response", async () => {
    const { api, calls } = stubApi(PAGE_RESPONSE);
    const { getAttendanceRecordsPaginated } = loadWrapper(
      "getAttendanceRecordsPaginated",
    )(api);
    const out = await getAttendanceRecordsPaginated({ startDate: "2026-01-01" }, 1, 0);
    expect(out.firstDate).toBe("2026-01-05");
    expect(calls[0].path).toBe("/api/payroll/attendance/page");
  });

  it("forwards lastDate from the server response", async () => {
    const { api } = stubApi(PAGE_RESPONSE);
    const { getAttendanceRecordsPaginated } = loadWrapper(
      "getAttendanceRecordsPaginated",
    )(api);
    const out = await getAttendanceRecordsPaginated({}, 1, 0);
    expect(out.lastDate).toBe("2026-09-29");
  });

  it("nulls the span when the server omits it (empty filtered set)", async () => {
    const { api } = stubApi({ items: [], total: 0, limit: 1, offset: 0, hasMore: false });
    const { getAttendanceRecordsPaginated } = loadWrapper(
      "getAttendanceRecordsPaginated",
    )(api);
    const out = await getAttendanceRecordsPaginated({}, 1, 0);
    expect(out.firstDate).toBeNull();
    expect(out.lastDate).toBeNull();
  });

  it("passes limit/offset through to the query string", async () => {
    const { api, calls } = stubApi(PAGE_RESPONSE);
    const { getAttendanceRecordsPaginated } = loadWrapper(
      "getAttendanceRecordsPaginated",
    )(api);
    await getAttendanceRecordsPaginated({ startDate: "2026-01-01" }, 25, 50);
    expect(calls[0].params).toEqual({ startDate: "2026-01-01", limit: 25, offset: 50 });
  });

  it("still reports firstDate/lastDate as null on error", async () => {
    const { api } = stubApi(new Error("boom"));
    const { getAttendanceRecordsPaginated } = loadWrapper(
      "getAttendanceRecordsPaginated",
    )(api);
    const out = await getAttendanceRecordsPaginated({}, 1, 0);
    expect(out.error).toBe(true);
    expect(out.firstDate).toBeNull();
    expect(out.lastDate).toBeNull();
  });
});

/* ── getAttendanceSummaryByEmployee ─────────────────────────────────── */

const TOTALS = {
  totalDays: 1200,
  present: 900,
  absent: 180,
  leave: 120,
  unpaidLeaves: 40,
  paidLeaves: 80,
};

const SUMMARY_RESPONSE = {
  items: [{ employeeId: 7, name: "A" }],
  total: 42,
  limit: 100,
  offset: 0,
  hasMore: false,
  totals: TOTALS,
};

describe("getAttendanceSummaryByEmployee — totals + search passthrough", () => {
  it("forwards org-wide totals for the stat cards", async () => {
    const { api } = stubApi(SUMMARY_RESPONSE);
    const { getAttendanceSummaryByEmployee } = loadWrapper(
      "getAttendanceSummaryByEmployee",
    )(api);
    const out = await getAttendanceSummaryByEmployee({ startDate: "2026-01-01" });
    expect(out.totals).toEqual(TOTALS);
  });

  it("forwards search so the server filters, not just the loaded page", async () => {
    const { api, calls } = stubApi(SUMMARY_RESPONSE);
    const { getAttendanceSummaryByEmployee } = loadWrapper(
      "getAttendanceSummaryByEmployee",
    )(api);
    await getAttendanceSummaryByEmployee({ startDate: "2026-01-01", search: "doe" });
    expect(calls[0].params.search).toBe("doe");
    expect(calls[0].path).toBe("/api/payroll/attendance/summary/by-employee");
  });

  it("forwards limit/offset for paging", async () => {
    const { api, calls } = stubApi(SUMMARY_RESPONSE);
    const { getAttendanceSummaryByEmployee } = loadWrapper(
      "getAttendanceSummaryByEmployee",
    )(api);
    await getAttendanceSummaryByEmployee({ limit: 200, offset: 400 });
    expect(calls[0].params).toEqual({
      startDate: undefined,
      endDate: undefined,
      search: undefined,
      limit: 200,
      offset: 400,
    });
  });

  it("nulls totals on error so the caller falls back instead of showing stale sums", async () => {
    const { api } = stubApi(new Error("boom"));
    const { getAttendanceSummaryByEmployee } = loadWrapper(
      "getAttendanceSummaryByEmployee",
    )(api);
    const out = await getAttendanceSummaryByEmployee({});
    expect(out.error).toBe(true);
    expect(out.totals).toBeNull();
  });
});

/* ── Consumer wiring — the fields must actually be read, not just returned ── */

describe("AttendancePage.jsx wiring", () => {
  it("reads firstDate/lastDate off the paged history response", () => {
    expect(PAGE_SRC).toContain("setHistoryFirstDate(page.firstDate || null)");
    expect(PAGE_SRC).toContain("setHistoryLastDate(page.lastDate || null)");
  });

  it("reads totals off the summary response for the stat cards", () => {
    expect(PAGE_SRC).toContain("setSummaryTotals(res.totals || {");
    expect(PAGE_SRC).toContain("const totalWorkingDays = summaryTotals.totalDays || 0");
  });

  it("passes search on both summary call sites", () => {
    const calls = PAGE_SRC.split("getAttendanceSummaryByEmployee(").length - 1;
    expect(calls).toBe(2);
    expect(PAGE_SRC).toContain("search: search?.trim() || undefined");
    expect(PAGE_SRC).toContain("search, limit: pageSize, offset,");
  });
});

/* ── Summary ────────────────────────────────────────────────────────── */

for (const step of queue) await step();

console.log(
  `\n  ${"=".repeat(64)}`,
);
if (failed > 0) {
  console.log(`  \x1b[31m${failed} FAILED\x1b[0m / ${passed + failed} total`);
  for (const f of failures) console.log(`    x ${f.label}: ${f.error}`);
  process.exit(1);
} else {
  console.log(
    `  \x1b[32m${passed} passed\x1b[0m / ${passed} total — attendance passthrough OK`,
  );
}
