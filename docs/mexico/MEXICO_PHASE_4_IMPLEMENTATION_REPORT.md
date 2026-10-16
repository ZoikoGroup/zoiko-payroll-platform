# Mexico (MX) — Phase 4 Implementation Report: Employee statutory profile

Spec ZP-MX-ENG-001 v1.0 §12 · plan `MEXICO_PHASE_4_PLAN.md` (§14 approval changes) · delivered in two PRs:
**4a** (dormancy gates — merged as PR #103, deployed, run 38870346791 ✅) and **4b** (this report; staged on `nikhil`, not committed).

## 1. Result

| Check | Result |
|---|---|
| Full backend suite — run locally in 5 chunks of ~60 files (full single runs are killed by session restarts here) | **6 272 passed, 1 failed, 50 skipped, 2 xfailed** = all 6 325 collected tests. The one failure is the known **OOS-4** (`test_hong_kong_configuration`, same 10 HK findings) |
| New Phase 4 tests | `test_mexico_dormancy.py` (49, incl. the `tax_resolver` pins), `test_mexico_employee_validation.py`, `test_mexico_identity_token_key.py`, `test_mexico_statutory_profile.py`, `test_mexico_infonavit_notices.py`, `test_mexico_employee_readiness.py`, `test_mexico_employee_migrations.py` — all pass |
| Migration on **PostgreSQL 17** (throwaway local cluster, `MX_PG_TEST_URL`) | 2/2 — exact locking plan emitted; held lock → fails fast in ~5 s, nothing half-applied |
| Browser — flag **off** (production setting) | **8/8** — `phase4-evidence/RESULTS-off.md`, 3 screenshots |
| Browser — flag **on** | **12/12** — `phase4-evidence/RESULTS-on.md`, 8 screenshots, key ones inspected |
| ESLint (`src`) | 184 errors — unchanged; new files add none |
| `check:undefined` / `vite build` | 496 files clean / passes |

## 2. What was built (4b)

**Backend**
- **Migration `8b2f6d4e1a93_mx_employee_m3`** — 24 nullable `mx_*` columns on `payroll_employee_statutory_profiles`, two nullable FKs (`fk_statutory_profile_mx_establishment`, `fk_statutory_profile_mx_imss_registration`, `ON DELETE SET NULL`) and table `payroll_mx_infonavit_notices` (partial unique index: one open notice per credit). Single head; 199 revisions.
- **`employee_validation.py`** — `MXEmployeeValidation` (RFC física 13 + real date, CURP 18, NSS 11, CLABE 18 optional; `SENSITIVE_FIELDS` rfc/curp/nss/clabe; duplicate key CURP; `MASK_DUPLICATE_VALUE = True`) registered in a separate **`_DORMANT_STRATEGIES`** map used only while the flag is on; `is_supported_employee_country()`; the global sensitive-field set includes the dormant strategy's fields; `mask_routing` masks `clabe` like `iban`.
- **`mexico_identity.py`** — `v1:` HMAC-SHA256 tokens under `MX_IDENTITY_TOKEN_KEY`; **Q7 strict**: the `PAYROLL_SECRET_KEY`-derived fallback only when `ENVIRONMENT`/`APP_ENV` is development/dev/test/testing/local (or unset with DEBUG on); otherwise a missing key refuses every Mexican identifier write.
- **`mexico_employee_service.py`** — profile hooks (shape errors; carry-forward; establishment / registration same-org, same-employer, registration ACTIVE on the effective date; work state defaults from the establishment and needs an exception ref when it differs, MX-038; professional minimum only from Active content; tokens + last-4 + `FORMAT_ONLY` with "source pending" findings), INFONAVIT notices (RETENCION / MODIFICACION supersedes / SUSPENSION closes; evidence required; method + value only from the notice), employee record and per-employee readiness.
- `mexico_service.py` — `statutory_profile_errors` / `statutory_profile_values` hooks now delegate to the module above (were the Phase 0 refusal); `statutory_summary` phase 4.
- `service.py` — Mexico-only hunks: the profile save uses `is_supported_employee_country`; the duplicate 409 masks the value **only** for a strategy with `MASK_DUPLICATE_VALUE` (Mexico).
- `schemas.py` — 18 editable `mx_*` fields on the profile create schema; response adds last-4, status and findings (tokens never returned).
- `bank_routing.py` — MX: CLABE / SPEI (inert while no Mexican employee can exist).
- Routes (org, behind the 4a guard): `GET /employees/{id}`, `GET /employees/{id}/readiness?on=` (required), `POST /employees/{id}/infonavit-notices`. Super Admin (read-only, masked): `GET /employees/{id}?organization_id=&on=`.
- `mexico_employer_service` — employer readiness gains "Employees with blocking exceptions" (unmapped summary line).
- `mexico_content.py` — S31 (RENAPO CURP), S32 (IMSS NSS), S33 (Banxico/ABM CLABE) in the addendum source list.
- `config.py` — `MX_IDENTITY_TOKEN_KEY: str = ""`.

**Frontend**: `MexicoStatutoryProfilePanel.jsx` (§12 sections, workplace pickers, effective-dated versions, readiness with the local-date bar), `MXInfonavitNoticePanel.jsx`, a masked **Mexico identity & bank** block and the "Mexico statutory profile → Manage" block in `EmployeeDetailPanel.jsx`, `countryFieldSpecs.js` MX, `bankFieldsFor.js` MX, `payrollService.js` (3 calls).

**Docs**: `PRODUCTION_STATE.md` (§2e the 4a `tax_resolver` change; PR #102/#103 rows), `MEXICO_IMPLEMENTATION_PLAN.md` (prerequisites beside G1–G8 incl. **Q9**), `OUT_OF_SCOPE_DEFECTS.md` **OOS-7**, this report, `phase4-evidence/`.

## 3. Migration — locking, verified on PostgreSQL

Captured statement sequence (test `test_pg_emits_exactly_the_approved_locking_plan`):
1. `SET LOCAL lock_timeout = '5s'` — before any statement on the shared table.
2. **One** `ALTER TABLE payroll_employee_statutory_profiles ADD COLUMN … (×24), ADD CONSTRAINT … FOREIGN KEY … NOT VALID (×2)` — no `DEFAULT` anywhere (metadata-only, no rewrite).
3. `ALTER TABLE … VALIDATE CONSTRAINT fk_statutory_profile_mx_establishment`, then `… fk_statutory_profile_mx_imss_registration` — both end `convalidated = true`.
4. NL and HK profile rows unchanged; re-run is a no-op; downgrade removes only the Mexico objects (also under `lock_timeout`, one `ALTER TABLE`).

`test_pg_a_held_lock_makes_the_migration_fail_fast`: with another connection holding `ACCESS SHARE` on the table, the upgrade raises `lock timeout` after ~5 s and **no column was added**. SQLite (dev/test) uses Alembic batch mode (SQLite cannot add a FK column in place). The production deploy's `check_schema_drift` compares column names only — the 24 migrated columns equal the model's.

## 4. What this does in production when merged (plan §9)

| Change | Production effect (`MX_TENANT_ONBOARDING_ENABLED` unset → False) |
|---|---|
| Migration `mx_employee_m3` — locking | `lock_timeout = 5s`; one `ALTER TABLE` → one brief `ACCESS EXCLUSIVE` lock on `payroll_employee_statutory_profiles` (metadata-only, milliseconds when uncontended); FKs `NOT VALID` then `VALIDATE` under `SHARE UPDATE EXCLUSIVE` (reads/writes continue). If the lock is not obtained in 5 s the deploy step fails cleanly (nothing applied) and is re-run; the running app keeps serving the previous code until restart. |
| Migration `mx_employee_m3` — data | 24 nullable columns (every existing row NULL) + two FKs trivially valid + one empty table `payroll_mx_infonavit_notices`. Additive, guarded, idempotent; `alembic current --check-heads` and `check_schema_drift` pass (verified locally). |
| Mexican employee creation | **Unchanged**: still refused with the same `Unsupported country code 'MX'. Supported: …` message (MX is not in `_STRATEGIES`; the dormant map is consulted only with the flag on). |
| Statutory-profile route for MX | Refused (`Unsupported jurisdiction country_code: 'MX'`) — and no Mexican employee can exist. |
| New org routes (`/api/payroll/mexico/employees/...`) | Behind the 4a guard → 403. |
| Super Admin employee route | Read-only, masked; no Mexican employee exists → 404 / empty. |
| Duplicate-identifier message | Unchanged for every country (pinned); Mexico's masking applies only to Mexican employees. |
| Sensitive-field masking set | Gains `rfc`, `curp`, `nss`, `clabe`; no other strategy uses these keys (pinned) → no visible change. |
| Bank routing | MX/CLABE/SPEI added; no other country's fields, labels or rails change (pinned); inert. |
| Settings | `MX_IDENTITY_TOKEN_KEY` defaults empty; with the flag off it is never used. Nothing to add to the production `.env`. |

Net effect: production stays as dormant as after 4a; the only database change is additive columns and an empty table.

## 5. Approved changes applied

- **Q7 strict** — `test_mexico_identity_token_key.py`: production / staging / prod / unset-with-DEBUG-off → refused; development / test / testing → fallback; a dedicated key works and never appears in a response, audit row or log.
- **Duplicate masking (Mexico only)** — the 409 for a duplicate CURP shows `A**************YZ01`-style masking; HK's message is pinned byte-identical (OOS-7 is the shared ticket).
- **S31–S33** — in the addendum (4a PR) and now in the content module (`ALL_SOURCE_CODES` S1–S33).
- **Rehire** — `test_rehire_is_a_new_version_on_the_same_employee`: a second employee with the same CURP is refused (409); the rehire is a new effective-dated version on the same employee, the previous one closed the day before.

## 6. Browser evidence (`docs/mexico/phase4-evidence/`)

Harness: `vite build` + `vite preview`, uvicorn on a scratch SQLite DB built by `harness/setup_db.py` (scratch path asserted; `@example.com` users; SYNTHETIC identifiers), run twice.
- **Flag off (8/8):** Compliance Centre shows the dormancy message; payroll jurisdiction MX and organisation country Mexico refused (400); the Mexico employee panel shows only the dormancy message; creating a Mexican employee refused; Super Admin workspace loads; no unexpected HTTP / page errors.
- **Flag on (12/12):** employee drawer shows RFC/CURP/NSS masked (`A********1AB1`…); Mexico panel renders every §12 section; work state ≠ establishment needs the exception ref; version saved with `FORMAT_ONLY` and "source pending" findings; professional minimum refused (content not Active); INFONAVIT notice refused without evidence, recorded with it; employee readiness shows BLOCKED items with gates, `unmapped`, S31/S32, S28 and MX-045; employer readiness shows "1 of 1 employee(s) with identifier exceptions"; NL org tabs unchanged.
- Fixed during the run: the employee drawer had no Mexico identity block (it fell through to the generic India rows) — added; two check-wording fixes (CSS-uppercased heading; record a catalog code so the S28 dependency is shown).

## 7. Deviations from the plan (minor)

1. 24 columns, not "~25" (the plan's list, counted exactly).
2. INFONAVIT closing is a **SUSPENSION notice**, not a separate `PUT …/close` route — the authority's suspension is itself the evidence.
3. Super Admin employee view is the read-only API route; the Super Admin UI drawer is deferred (no Mexican employee can exist in production; the org screens carry the browser evidence).
4. CLABE is in the Mexico `SENSITIVE_FIELDS` (masked in `compliance_fields`) and masked in the routing display, like SA's IBAN.
5. Employer readiness's employee line is an **unmapped** summary; each employee's own readiness carries the §22 gate mapping.
6. The `MXSbcExplainabilityCard` stays in Phase 5 (no SBC is computed yet).

## 8. Open / prerequisites

Q9 (plaintext at rest, HK D-4) for the security lead; `MX_IDENTITY_TOKEN_KEY` in Secret Manager; S31–S33 to be saved (check digits and the RFC↔CURP rule stay `NOT_CHECKED`); OOS-7 shared fix; G1–G8.
