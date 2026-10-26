# Brazil golden vectors (ZP-BR-ENG-001 §24)

Golden-vector regression harness input for the Brazil (CLT) calculator. The
runner lives in `service.run_pack_golden_vectors` / `run_golden_test_certification`
and is reachable from Super Admin → Compliance > Brazil (golden check) and the
Test Certification page.

Status: **Phase 5 (in progress).** The Phase 5 calculation engine (BR-ENGINE-
2026.2) exists and `F1` (ordinary monthly wage) and `F6` (minimum-wage floor,
a BLOCKED case) are `PROVISIONAL` engineering controls. `F2` (variable/premium
components) lands with the Phase 5b labour helper; `F3`–`F5` (13th-salary,
vacation, termination) are Phase 7 and live in
`_F3_F4_F5_phase7_placeholders.json` (the leading `_` keeps them out of
certification). No vector is written from memory — every fixture must be
sourced and independently reviewed before it can make a Brazilian pack Active
(BR-003, BR-004).

Planned vectors (ZP-BR-ENG-001 §18):

| ID | Case | Phase |
|----|------|-------|
| F1 | Ordinary CLT monthly wage (INSS, IRRF with reduction, FGTS) | 5a (landed, PROVISIONAL) |
| F2 | Wage with variable/premium components | 5b |
| F3 | 13th-salary (décimo terceiro) | 7 |
| F4 | Vacation (férias + one-third) | 7 |
| F5 | Termination (rescisão) with FGTS fine | 7 |
| F6 | Minimum-wage floor case | 5a (landed, PROVISIONAL BLOCKED case) |

Each fixture carries `status` (`PROVISIONAL` engineering control or `OFFICIAL`
certified vector), the `source`/`description` with the hand calculation, the
harness `context` (with the full `brazil_inputs` dict), and `expected` (or
`expected_blocked_key`), exactly like the other `*_golden/` directories.
