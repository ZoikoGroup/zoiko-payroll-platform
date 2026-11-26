# Gate removal: JP, NZ, PL, MY, ZA, BE go live like Spain

**Owner decision, 2026-11-25.** Japan, New Zealand, Poland, Malaysia, South Africa and Belgium no longer have go-live gates. Like Spain, India, the UK and the other ordinary countries, a country opens for registration once its compliance pack is **Active**, approved by a Super Admin other than the pack's last editor.

The documented statutory content is kept and calculates. A value no document gives is never invented: it blocks only the calculation that needs it, with a named reason, until a Super Admin enters it in the pack.

Per-country registers: `docs/<country>/<COUNTRY>_GAPS_AND_DECISIONS.md` (Belgium: the "Gate removal" section at the top of `docs/belgium/BELGIUM_GAPS_AND_DECISIONS.md`). Row-by-row inventories: `docs/<country>/GATE_REMOVAL_INVENTORY.md`.

## What was removed

| Layer | Before | Now |
|---|---|---|
| Dormancy | `<CC>_TENANT_ONBOARDING_ENABLED` + `<CC>_CANARY_ORG_IDS`; every country API, country change and employee validator refused while off | Removed. Old environment variables are ignored (`extra="ignore"`). |
| Registry | Registry row required; PLANNED → AVAILABLE only when release gates G0–G8 passed with reviewed `<CC>-GATE-*` evidence, `<CC>-SIGNOFF-*`, owner decisions, parallel cycles and keyrings | Row optional (like Spain). PLANNED → AVAILABLE needs a reason and a named Super Admin, and is audited. A PLANNED row still blocks registration until it is moved. |
| Readiness / evidence UI and API | Readiness tabs, gate evidence, activation readiness, owner-decision records, 19 routes | Removed. The DB tables are kept, unused; there is no migration. |
| Pack activation | Refused while any row was unsigned (`[PENDING G1]`), unsourced or empty, an authority table was empty, or (BE) golden certification had not passed; extra four-eyes lists for PL, MY, ZA, BE | Structural checks only: the pack has content; NZ-ELA-2028 not before 2028-08-06; PL has a PIT scale; BE demo packs never activate. Only the platform-wide rules remain (approver ≠ last editor, no overlapping Active packs). |
| Signing | Rows carried `[PENDING G1]` until a second Super Admin signed them against a reviewed source; the engine refused unsigned rows | No signing step. The marker no longer blocks and is never written. A source document is optional provenance, and a change reason is still required. The "Signing status" tabs became "Missing content". |
| Report templates | Country hooks refused activation (G3/G4, BRS catalogue) | Normal template governance. |
| Japan run approval | Second-person approval of every run exception | Exceptions are listed but do not block. The frozen-calculation snapshot and fingerprint are kept. |

Kept on purpose:
- Retention: employee deletion waits for a recorded retention decision. This keeps data and fails safe.
- Record-level second approval of employer registrations, worker profiles and tax codes.
- Belgium's ONSS rate-table four-eyes (`BE_ONSS_RATE_UNSIGNED`). Its removal is an open question.

## Content written (owner approved all proposed values, 2026-11-25)

| Country | Calculates | Still blocked (needs a source or new engine logic) |
|---|---|---|
| South Africa | PAYE, UIF, SDL, ETI (offset against PAYE), BCEA OT/Sunday/holiday, 25% damage cap | — |
| Poland | Full payroll, F1 worked example: PIT, ZUS, health, funds, PPK, overtime, sick pay | Fund-exemption workers, PIT due date, leave pay |
| New Zealand | ACC, KiwiSaver, ESCT, student loan, child support, annual leave pay | PAYE and lump-sum authority tables (IRD), payday-filing rows |
| Malaysia | EPF, PERKESO, EIS, HRD, overtime, leave (3 territories) | PCB (HASiL spec), minimum-wage day/hour rules, HRD base, EPF/SOCSO/HRD due dates, leave pay |
| Japan | Pension, employment, care and child-support insurance; YEA rounding and 2.1% surtax; resident-tax due day; additive premiums | NTA withholding / YEA tables, prefectural health rates, SMR grades, minimum wages, non-business-day due-date rule |
| Belgium | 25 spec values (ONSS 13.07%, RMMMG 2,233.61 from 2026-07-01, OT 50/100%, holiday pay, absence) | Annex III withholding, employer ONSS bands, 6 range/table values, 46 rows with no spec value, ONSS rate-table signing |

Japanese employees now have an ordinary validator (`JPEmployeeValidation`; My Number stays in its vault). Japan and New Zealand are in the employee form. Neither has salary bank-routing fields yet.

## Rollout (P8, one step at a time, owner's go-ahead for each)

1. **Dry run** (read-only) against the target database: `python -m scripts.gate_removal_update_packs`. Review which packs would change.
2. **Apply** to Draft packs: `python -m scripts.gate_removal_update_packs --apply`. Then, for Belgium's Approved pack: `--apply --include-approved --country BE`, and repeat its approval. The script strips the legacy marker, fills only empty / `PENDING_G1` rows, never overwrites a set value, and writes one audit row per pack.
3. **Registry:** move each PLANNED row (JP, NZ, PL, MY, ZA, BE) to AVAILABLE in Super Admin, with a reason. Until then registration stays blocked.
4. **Activate** each pack: approve by a Super Admin other than its last editor, then Activate.
5. **Ops:** remove the dead `*_TENANT_ONBOARDING_ENABLED` / `*_CANARY_ORG_IDS` variables from the deployment.
6. **Keys:** identifier-vault keyrings (`JP_MY_NUMBER_KEYRING`, `NZ_IRD_KEYRING`, `PL_/MY_/BE_IDENTIFIER_KEYRING` and their fingerprint keys) must be set before any identifier is stored.

## Commits (branch `venu`)

`21d00af4` P0 inventory · `3d8f13a3` P1–P3 gates · `85dcb965` P4/P4b content and Japan employees · `a116b5c8` console/UI signing retired · `fd2defa4` P5 data script · (this document) P7.
