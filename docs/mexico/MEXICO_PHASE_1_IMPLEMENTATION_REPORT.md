# Mexico (MX) — Phase 1 Implementation Report

**Status: INTERIM.** The value-free tooling is built. **No statutory value has been transcribed.** Every content table is empty until the user replies "start transcription", and transcription is blocked on the Batch A source files.

**Branch:** `nikhil` (Phase 0 committed as c09f7e8). The work is staged only; the user commits.

---

## Interim note — value-free Phase 1 tooling (2026-10-15)

### Built

| File | What |
|---|---|
| `backend/app/modules/payroll/engine/countries/mexico_content.py` | **Content structures, all empty.** It contains:<br>• typed row shapes (`ScalarRow`, `IsrBracket`, `MinWageRow`, `ZlfnMunicipality`, `CeavBand`, `WorkweekRow`, `VacationDaysRow`), each carrying source code, page/article ref and `needs_g1`<br>• `MX_PARAMETER_KEYS`: **names, kinds, labels and scope only**, all taken from concepts the spec names. The special-pay exemption keys are named at transcription from S24/S25.<br>• `MX_PENDING_G2_KEYS` (CEAV lowest-band reference only)<br>• `MX_CEAV_SEEDED_YEAR = 2026` and the 2023–2030 schedule years<br>• `ADDENDUM_SOURCE_REFERENCES` S24–S27 (pending spec-owner approval)<br>• an empty `MX_ISR_ARITHMETIC_EXCEPTIONS` (source-wins log)<br>• 9 `*_in_force(as_of)` helpers. Each takes the date as a required argument, validates it first, never reads the clock, and raises `MexicoContentMissing` on empty content. |
| `backend/scripts/seed_mexico_canonical_packs.py` | **Seed script cloned from NL.** It is Draft only and uses NL's `_require_confirmed_target` guard (override env var + TTY + typed CONFIRM). It:<br>• refuses to rewrite a non-Draft pack and replaces Draft rows wholesale;<br>• upserts `SourceArtifact` rows by URL + SHA-256 (HK pattern), using only manifest rows marked **VERIFIED**. A row citing anything else refuses the seed.<br>• seeds `MX-PAYROLL-2026` and `MX-ISN-CDMX-2026` (parent = national; seeded CEAV rows = 2026 only), a CDMX `StateLocalProgramReadiness` row (`OTHER_STATE_PAYROLL`), the registry row (PLANNED / NOT_OFFERED) and audit entries;<br>• puts the `[PENDING G1]` / `[PENDING G2]` label markers on every row and refuses catalog drift.<br>On today's content it creates the two Draft packs with **0 rows**. |
| `backend/scripts/verify_mexico_sources.py` | **Evidence tool**, which never touches the database. Subcommands:<br>• `hash`: SHA-256, bytes, type and text-layer detection; a new or changed file becomes UNVERIFIED<br>• `header`: prints the document header, for title, issuer and reform date<br>• `set`: VERIFIED requires a title, an issuer, a header version and a text layer<br>• `check`: hash integrity<br>• `compare`: row-by-row number extraction with pdftotext `-layout` or pypdf. An ISR bracket's four numbers must sit on **one** line of S2. Against empty content it checks 0 rows. |
| `docs/mexico/sources/SOURCES_MANIFEST.csv` | Migrated to the tool's columns (adds `issuer`, `header_version`, `text_layer`). The S22 row stays `WRONG_VERSION`, now with issuer and header version recorded. |
| `backend/app/modules/payroll/service.py` | `"MX"` added to `_CANONICAL_PACK_ONLY_COUNTRIES` (L1511). |
| `backend/app/modules/payroll/engine/countries/shared.py` | `"MX"` added to `_VALIDATION_ENABLED_COUNTRIES` (L97). |
| `backend/app/modules/payroll/engine/fallback_registry.py` | **Mexico fallback rows, value-free:**<br>• `mexico` added to `_MODULES`;<br>• one row per `MX_PARAMETER_KEYS` entry, generated from the catalogue so it cannot drift, each with `attr: "MX_NO_FALLBACK"` (a defined `None`) and no value in any note;<br>• state-scoped and text keys marked `required: False` (see deviation 1);<br>• one N/A row for the `MX_*` TaxSlab families. |
| `backend/tests/test_mexico_content.py` | 14 structural tests that run now, plus 9 value tests, each skipped with the reason *"awaiting transcription — this content table is empty until 'start transcription'"*. The value tests read their expected figures from the spec `.docx` at run time; none are typed into the test. |
| `backend/tests/test_mexico_seed.py` | 20 structural tests (23 cases with parametrization) of seed, guard, evidence, activation and governance behaviour. |
| `backend/tests/test_mexico_source_tool.py` | 6 tests of the evidence tool, run on synthetic files. |
| `backend/tests/test_mexico_scaffolding.py` | The Phase 0 assertion `MX_PARAMETER_KEYS == {}` replaced with "keys named, content tables empty". |

### Phase 1 §6 conditions covered by structural tests

| Condition | Covered by |
|---|---|
| Seed idempotence | National, ISN, registry, readiness and artifact counts are unchanged on re-run. |
| Guard refusal | Three cases each give `SystemExit(2)`: no override, non-TTY, not confirmed. The guard passes only with all three. |
| Non-Draft refusal | Both packs are refused once they leave Draft. |
| Activation still refused | `service.set_jurisdiction_pack_status(…, "Active")` on each seeded pack refuses with the Phase 0 hook message, and the pack stays Draft. |
| No Active set by production code | An AST scan of all seven Mexico production files finds no `"Active"` literal outside docstrings. |
| Test-only Active pack | Inserted by a fixture with the ORM, never through a service function. All of its rows are synthetic. |
| Required date argument | Every `*_in_force` helper has `as_of` with no default. A non-date raises `TypeError`, including on empty content. |
| Today changes nothing | The content module's `date` is replaced with a clock-less class; the synthetic January and February rows are still selected by argument. A source scan finds no `date.today(`, `datetime.now(` or `utcnow(` in any Mexico engine file. |
| Pay-date selection through the real resolver | `tax_resolver.resolve_tax_configuration` returns the January row for 2026-01-31 and the February row for 2026-02-01 (synthetic values 1 and 2). |
| Canonical-only reads | An org-scoped MX row with a wrong value is never returned, with or without the org opted in. Applying an extracted rate to an MX org is refused. A pack missing a required key fails readiness. |
| Generic-tax-path spy | `_calculate_annual_tax` is spied in both `shared` and `generic`. MX calculations (standard and enterprise) with all five `MX_*` slab families raise `MexicoCalculationBlockedError`, and the spy is **never called**. A control run for an unknown country shows the spy does watch the generic path. |
| `_VALIDATION_ENABLED_COUNTRIES` affects only MX | The set equals the previous set plus `{"MX"}` exactly. Seven countries that are not opted in are still no-ops. All eight previously opted-in countries still refuse an empty configuration. |
| CEAV only 2026 seeded; full schedule date-selected | A synthetic 2025/2026/2027 schedule seeds only `tax_table_number="2026"`. `ceav_bands_in_force` picks the year by date. |
| ISR arithmetic checker (§3, §6 changes 1–2) | Synthetic tariffs prove the checker:<br>• accepts a consistent table;<br>• flags gaps and closed tops;<br>• indexes quotas from the **previous** bracket (directional: changing bracket 1's rate breaks only bracket 2's quota, and vice versa);<br>• honours documented source-wins exceptions. |

### Deviations

1. **MX text parameters are not readiness requirements.**
   - **Cause:** the shared predicate (`service._check_missing_required_keys`) counts a side-less key as configured only through `flat_amount`. The CEAV lowest-band reference lives in `text_value`, so as a required key it could never be satisfied, and Mexico readiness would fail permanently.
   - **Fix:** text keys are `required: False`, as NL does for its text keys. The Phase 5 engine checks them itself.
2. **The helpers validate their date before reading content.** This surfaced in my own test: with empty content, `uma_in_force(None)` raised `AttributeError` instead of `TypeError`.
3. **A third test file**, `test_mexico_source_tool.py`, covers the evidence tool. The plan only named the content and seed test files.

### Test results

**Full backend suite** (`pytest tests/`, detached run): **1 failed, 5939 passed, 48 skipped, 2 xfailed** in 22 min 40 s.
- Against Phase 0 (5896 passed, 39 skipped), this is exactly +43 passing and +9 skipped, which are the new Mexico tests. Nothing else changed.
- The single failure is the known, pre-existing **OOS-4**: `test_hong_kong_configuration.py`, with the same 10 "undocumented" findings. It comes from the stale untracked HK matrix CSV and is unrelated to Mexico.

**Mexico files alone** (75 tests, run while iterating with the DB URL forced to a throwaway SQLite): **66 passed, 9 skipped.**
- `test_mexico_scaffolding` 23.
- `test_mexico_content` 14 + 9 skipped value tests.
- `test_mexico_seed` 23.
- `test_mexico_source_tool` 6.

**Frontend:** untouched in this step.

### Not done (by instruction)

- No transcription. No statutory value exists in any content table, test or registry note.
- No source-file verification: none of the Batch A files are present. The manifest holds only the stale S22 row.
