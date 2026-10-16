# Brazil (BR) — Phase 1 Implementation Report (statutory content and canonical pack)

Date: 2026-10-16. Branch: `venu` (on top of `640d24b`, Phase 2). Not pushed. No real database written.

## 1. What Phase 1 delivers

- **Saved official evidence** in `docs/brazil/sources/`, with `SOURCES_MANIFEST.csv` recording code, URL, file, SHA-256, size, retrieval time, status and what was checked. `.gitattributes` there marks every file `-text`, so git never alters the bytes the hashes pin.

| Code | Source | Status | Verified in the saved file |
|---|---|---|---|
| S1 | INSS — Tabela de contribuição mensal (updated 13/01/2026) | VERIFIED | Bands 7.5 / 9 / 12 / 14 % to R$ 1.621,00 / 2.902,84 / 4.354,27 / 8.475,55, by competence. Concurrent jobs summed within the maximum; 13th assessed separately |
| S2 | Receita Federal — Tributação de 2026 | VERIFIED | IRRF table, deductions 189,59 / 607,20, reduction table indexed by "Rendimentos tributáveis" |
| S3 | Receita Federal — Exemplos de aplicação da Lei 15.270/2025 | VERIFIED | **D2 decided**: reduction on the salary, "e não o da base de cálculo"; 5 worked examples |
| S4 | Decreto 12.797/2025 | VERIFIED | Minimum wage 1.621,00 / 54,04 / 7,37 from 1/1/2026 |
| S5 | INSS — salário-família limit | VERIFIED | Up to 1.980,38 → cota 67,54; remuneration includes concurrent jobs |
| S8 | Lei 14.973/2024 | VERIFIED | 2026 CPRB transition: 60% of the CPRB rates, 50% of the art. 22 I and III rates |
| A1 | Lei 15.270/2025 (art. 3-A of Lei 9.250) | VERIFIED | Reduction table and formula |
| A2 | Lei 8.212/1991 art. 22 | VERIFIED | CPP 20%; §1 financial add-on 2,5% |
| A3 | Lei 8.036/1990 art. 15 | VERIFIED | FGTS 8%; §7 apprentice 2%. Its deposit *day* predates FGTS Digital and is NOT used |
| A4 | Portaria Interministerial MPS/MF nº 13/2026 | SAVED_NO_TEXT | Scanned PDF, no text layer; S1/S5 reproduce it. Needs human review |

- **Content as sourced, dated rows** (`engine/countries/brazil_content.py`):
  - 23 `ContentRow`s, each with `rule_type` / `key` / band / `rate_pct` (a percent, never a fraction) / flat amount / validity / `source`.
  - Every row is marked `[PENDING G1]` until the human G1 review.
  - `rows_in_force(rule, as_of)` / `row_in_force(rule, key, as_of)` raise `BrazilContentMissing` (`BR_CONTENT_YEAR_UNAVAILABLE`) outside 2026 — no silent reuse of another year.
  - The old constant names are now **derived from the rows**, so existing callers are unchanged.
- **Defects fixed:**

| Key | Fix |
|---|---|
| BR-K1 | `MAX_INSS_CONTRIBUTION = inss_maximum()` = 988.09 (all bands to the ceiling, rounded once), with an import-time guard against `PUBLISHED_INSS_MAXIMUM_2026` |
| BR-K10 | INSS = exact progressive total rounded once (D1). Concurrent jobs: table(combined) − table(other jobs), within the maximum (S1) |
| BR-K2 | IRRF reduction computed on gross taxable income (S3, D2); `reduction_basis` is in the trace |
| BR-K7 | `CONTENT_HASH` = SHA-256 over every row and every rubric (canonical JSON) |
| BR-K8 | Content is a single pure module (Phase 2) and carries the canonical-pack rule types |

- **Seeder** `scripts/seed_brazil_canonical_packs.py` (Mexico pattern):
  - creates the Draft `BR-PAYROLL-2026` pack with 23 TaxSlab rows, each linked to its SourceArtifact;
  - the pack's primary evidence is S1, and its change summary carries the content hash;
  - creates the PLANNED registry row and a seed audit entry.
- **What the seeder refuses:**
  - a source not marked VERIFIED;
  - a saved file whose SHA-256 changed;
  - rewriting a pack that left Draft;
  - running without `ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND` plus an interactive `CONFIRM`.

  It never seeds the rubric catalogue (BR-K3 still open).

## 2. Activation stays locked

Checked on a throwaway local database: `PUT …/policies/{id}/hotfix-activate` on the Draft BR pack was refused with "Brazil packs need a passing golden-vector certification run…", and the pack stayed Draft. Even after golden vectors exist, the gated status setter still runs Brazil's `pack_activation_refusal` hook, which refuses until G1–G8. Hotfix skips only the distinct-approver check.

## 3. Browser re-check of the Phase 2 workspace with the real Draft pack

Local only (throwaway SQLite, local Super Admin; real `seed_brazil` output, no synthetic rows):

- `BR-PAYROLL-2026 · v1.0 · FY 2026 · Draft` is listed.
- The shared **Tax Slabs** editor shows all 23 rows with their `[PENDING G1]` labels.
- The Brazil INSS tab says "No Active Brazil pack", because a Draft pack is never served as live.
- No errors.

**Observation (shared layout, not Brazil code):** the Tax Slabs grid has no flat-amount column, so R$ amounts such as 312,89 / 978,62 / 189,59 / 1.621,00 / 67,54 are visible only in the row labels. The Brazil statutory tabs do show "Amount (R$)" once a pack is Active.

## 4. Still open

| Item | Phase |
|---|---|
| S6, S7 (Tabela 04 / FPAS), S9–S20 not yet saved (eSocial, FGTS Digital, MTE) | 3 / 9 / 10 |
| Rubric incidence codes against the official eSocial Tabela 03 (BR-K3) | needs S10–S12 saved |
| A4 human review (scanned PDF) and the G1 statutory sign-off of every `[PENDING G1]` row | G1 |
| Golden vectors in `tests/fixtures/br_golden/` (the 5 Receita examples are already in the engine tests) | 5 |
| Engine still blocks every calculation; the context dates (payment vs competence) and `rows_in_force` wiring | 5 / 6 |
| Seeding any real database | separate go-ahead |

## 5. Verification

| Check | Result |
|---|---|
| Brazil tests (scaffolding, foundation, engine, router, Phase 1 content/seed) | 124 passed, **0 xfailed** — every former strict-xfail now passes as an ordinary test |
| Receita Federal worked examples 1–5 | reproduced to the cent |
| Full suite | see the commit message |
