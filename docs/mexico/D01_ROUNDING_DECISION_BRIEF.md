# D-01 — Monetary rounding rule: decision brief

**For:** the G1 owner.
**Written:** 2026-10-28, final mile X7.
**This brief makes no recommendation.** It sets out the candidate readings, what each source says, and what the sandbox computes under each. The decision is yours, recorded in the Super Admin → Mexico → **Decisions** tab (four-eyes).

## Why it matters first

Nothing in Mexico calculates until `mx_rounding_rule` exists. Every sandbox run stops at `MX_ROUNDING_RULE_MISSING`, and pack activation requires the key (`MX_REQUIRED_TEXT_KEYS`). With D-01 alone, every run then stops at **D-03** (`mx_ceav_lowest_band_min_wage_ref`). **D-03 (the G2 owner's) is the second decision on the critical path.**

## The question

How is each monetary amount rounded (**mode** and **quantum**), and **when** (each emitted line, or only totals)? The engine keeps full precision internally and rounds each emitted amount: each IMSS branch total, ISR, the subsidy, INFONAVIT and ISN.

## What the sources say (from `MEXICO_TRANSCRIPTION_BATCH_2_REPORT.md` §4)

| Source | Says |
|---|---|
| S30 catCFDI `c_Moneda` | MXN: **2 decimals** |
| S30 Anexo 20, p. 71 | Amounts "deben ser redondeados hasta esa cantidad de decimales" |
| S30 Guía de llenado Q37 / Q39 (pp. 88, 90) | Concepts up to 6 decimals; "**redondear al final del cálculo y no antes**". **No tie-breaking rule** (what happens at exactly ½ centavo) |
| S30 `tdCFDI.xsd` / S28 `nomina12.xsd` | `t_ImporteMXN`: at most 2 decimals |
| **S35** CFF Art. 20 ¶10, PDF p. 31 | Contributions are computed "inclusive, las fracciones del peso"; **for paying them**, 1–50 centavos go down to the peso and 51–99 go up. It governs **payment to the authority**, not payslip lines. Art. 17-A: factors "hasta el diezmilésimo" |
| S2, S3, S1 (RMF), S10 (LSS) | No payroll rounding provision found |
| S4 | Two-decimal examples; field-specific rules only |

## Candidate readings

| Reading | Value in the register | Basis | Open point |
|---|---|---|---|
| **A** | `HALF_UP:0.01` | CFDI sources: 2 decimals | The sources give no tie-break; this one is the owner's choice |
| **B** | `HALF_EVEN:0.01` | Same as A | Same as A |
| **C** | `HALF_DOWN:1` | CFF Art. 20 ¶10 | Written for paying contributions, not payslip lines. Also: an amount with fractions of a centavo just above 0.50 (for example 0.505) rounds **up** under `HALF_DOWN`, while the text speaks only of whole centavos |

Readings A and B also leave open the "when" question ("al final del cálculo"): whether intermediate totals (for example the sum of IMSS branches) are rounded once at the end or per line. The current grammar (`MODE:QUANTUM`) records mode and quantum only. **If the owner's answer is "only totals", say so in the rationale. It needs a code change, not a value.**

## What-if results (X2 sandbox)

> **SANDBOX — SYNTHETIC INPUTS — NOT A PAYSLIP · CANDIDATE — NOT APPROVED — NOT A GOLDEN VECTOR**

**Setup:**
- run on 2026-10-28 on a scratch database;
- the real **Draft** packs (`seed_mexico_canonical_packs`);
- the spec §21 fixtures, with CDMX, pay frequency 04 (fifteen days) and seniority 2026-01-01;
- D-03 held at the candidate `GENERAL` for every row (it must be set for anything to calculate);
- script: `final-mile-evidence/harness/d01_whatif.py` (run with `PAYROLL_DATABASE_URL` set to a scratch SQLite file); raw output `final-mile-evidence/D01_WHATIF_RESULTS.json`.

The amounts are in MXN for one fifteen-day period.

| Fixture | Reading | ISR withheld | IMSS employee | IMSS employer | ISN | Employer total |
|---|---|---|---|---|---|---|
| F1 January (UMA 113.14), 600/day | A / B | 726.08 | 241.69 | 1,768.80 | 360.00 | 2,600.99 |
| | C | 726 | 241 | 1,768 | 360 | 2,600 |
| F1 February (UMA 117.31), F2 first-year SBC, 600/day | A / B | 726.36 | 240.94 | 1,779.49 | 360.00 | 2,611.68 |
| | C | 727 | 241 | 1,779 | 360 | 2,611 |
| F3 CEAV high band, 1,000/day | A / B | 2,272.26 | 415.65 | 2,765.21 | 600.00 | 4,152.20 |
| | C | 2,272 | 415 | 2,765 | 600 | 4,152 |
| F4 general zone, 400/day | A / B | 211.41 | 153.60 | 1,229.97 | 240.00 | 1,784.76 |
| | C | 212 | 154 | 1,229 | 240 | 1,784 |
| F4 ZLFN, 400/day | all | **Blocked**: `MX_BELOW_MINIMUM_WAGE` (ZLFN floor 440.87) | | | | |
| F4 ZLFN, 500/day | A / B | 445.56 | 197.27 | 1,533.05 | 300.00 | 2,226.54 |
| | C | 446 | 198 | 1,534 | 300 | 2,227 |

Gross is 9,000 / 15,000 / 6,000 / 7,500 in every reading.

**What the numbers show (facts, not advice):**
- **A and B are identical on every fixture.** None of these amounts lands on an exact half centavo, so the tie-break only matters on other inputs.
- **C changes every amount**, by up to 0.99 per line. The employer total under C is the sum of whole-peso branch totals, not a rounded sum (the "when" question above).
- **Without D-01**, every fixture stops at `MX_ROUNDING_RULE_MISSING`.

## After the decision

The flow runs: approved in the register, then transcribed into the `mx_rounding_rule` row of the 2026 pack with the cited source, then G1. Approval alone changes no calculation.

## Next decisions for the G1 / G5 owners, with what each unblocks

| Order | Decision | Owner | Clears |
|---|---|---|---|
| 0 | **D-03**: CEAV lowest band reference (GENERAL / ZONE / UMA) | G2 | `MX_CONTENT_MISSING` (`mx_ceav_lowest_band_min_wage_ref`) on **every** calculation; `MX_CEAV_LOWEST_BAND_PENDING_G2` |
| 1 | **D-07**: unit of the LISR Art. 93 exempt limits (and D-07b, the Art. 486 cap): UMA or minimum wage | G1 (D-07b: G5) | `MX_EXEMPTION_WAGE_REFERENCE_UNDECIDED` (every special payment); `MX_SENIORITY_PREMIUM_WAGE_REFERENCE_UNDECIDED` |
| 2 | **D-08**: withholding method for a special payment in its own run | G1 | `MX_SPECIAL_PAY_METHOD_UNDECIDED` (aguinaldo and PTU runs) |
| 3 | **D-09**: monthly ordinary income from a daily salary | G1 | `MX_MONTHLY_ORDINARY_INCOME_UNDECIDED` (RLISR 174 and separation withholding) |
| 4 | **D-17**: overtime hourly rate (daily salary ÷ the Art. 61 day length?) | G5 | `MX_HOURLY_RATE_RULE_MISSING` (every overtime line) |
| 5 | **D-12**: indemnity salary (LFT Art. 89 integrated salary; gap C4) | G1 / G5 | `MX_INDEMNITY_SALARY_UNDECIDED` |
| 6 | **D-13**: does "por cada año de servicios" count a part year? | G5 | `MX_SERVICE_YEARS_COUNT_UNDECIDED` (Arts. 50, 54, 162) |

The order follows reach: D-07 to D-09 affect every special-pay or separation run, and D-17 every overtime line. D-12 and D-13 affect terminations only. **The order is a suggestion for sequencing, not a recommendation of any answer.**
