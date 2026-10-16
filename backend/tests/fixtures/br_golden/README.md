# Brazil golden vectors (ZP-BR-ENG-001 §24)

Golden-vector regression harness input for the Brazil (CLT) calculator. The
runner lives in `service.run_pack_golden_vectors` / `run_golden_test_certification`
and is reachable from Super Admin → Compliance > Brazil (golden check) and the
Test Certification page.

Status: **folder only (Phase 2).** The F1–F6 vectors land in Phase 5, once the
calculation engine and rubric-incidence bases exist (BRAZIL_IMPLEMENTATION_PLAN.md
§8). No vector is written from memory here — every fixture must be sourced and
independently reviewed before it can make a Brazilian pack Active (BR-003,
BR-004).

Planned vectors (ZP-BR-ENG-001 §18):

| ID | Case |
|----|------|
| F1 | Ordinary CLT monthly wage (INSS, IRRF with reduction, FGTS) |
| F2 | Wage with variable/premium components |
| F3 | 13th-salary (décimo terceiro) |
| F4 | Vacation (férias + one-third) |
| F5 | Termination (rescisão) with FGTS fine |
| F6 | Minimum-wage floor case |

Each fixture will carry `status` (`PROVISIONAL` engineering control or
`OFFICIAL` certified vector), the `source` spec/formula with the hand
calculation, `periods[].inputs`, `periods[].expected`, and `traceCodes`, exactly
like `tests/fixtures/nl_golden/`.
