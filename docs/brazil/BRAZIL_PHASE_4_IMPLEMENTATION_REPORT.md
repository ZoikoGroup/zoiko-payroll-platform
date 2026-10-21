# Brazil (BR) — Phase 4 Implementation Report: Employee statutory profile

Spec ZP-BR-ENG-001 v1.0 §7 · plan `BRAZIL_PHASE_4_PLAN.md` (§10 approval changes) · delivered in two
tranches: **4a** (validation, PIX masking, CPF/PIS check digits) and **4b** (this report; staged on
`venu`, not yet committed).

## 1. Result

| Check | Result |
|---|---|
| Targeted backend suites (BR Phase 1–4 + alembic metadata) | **206 passed, 2 skipped**. The only failure in the wider selection is the known **branch-divergence** guard `test_no_migration_deleted_or_renamed_against_origin_main` (local branch is missing MX `c4f7a2d9e6b1` / `d8b3e5f1a2c7`; **not** a Phase 4 change — see §8) |
| New 4b tests | `test_brazil_employee_profile.py` (20 passed), `test_brazil_employee_migrations.py` (revision link, 10 columns, FK, SQLite idempotent up/down, PG plan + lock fail-fast; 2 skipped without `BR_PG_TEST_URL`) |
| Cross-jurisdiction regression | `test_mexico_statutory_profile.py`, `test_mexico_employee_migrations.py`, `test_mexico_employee_readiness.py`, `test_mexico_scaffolding.py` → **45 passed, 2 skipped** (the shared-profile schema additions are additive) |
| Alembic metadata | single head **`b9f3a7c2e5d1`**, **202** revisions |
| Frontend | `npm run check:undefined` **515 files clean**; `npm run build` **passes**; ESLint clean on every new/edited file (the 31 `no-useless-catch` errors in `payrollService.js` are pre-existing, lines ~1978+) |
| Migration applied to a live DB | **Not run** — the branch is uncommitted and there are no local Postgres credentials (the configured remote DB is guarded). SQLite up/down/up is exercised in tests; the PostgreSQL locking plan is asserted from captured statements. |
| Full backend suite | **Not run** (a full run exceeds the tool timeout); the targeted BR + MX + alembic files above were run. |
| Browser harness | **Not run** (not requested for this phase). |

## 2. What was built

**Backend**
- **Migration `b9f3a7c2e5d1_br_employee_m3`** (child of `64424fd61652_br_employer_m2`): +10 nullable `br_*` columns on the shared `payroll_employee_statutory_profiles`, one nullable FK `fk_br_profile_establishment → payroll_br_establishments (id) ON DELETE SET NULL`, three new tables, and **drops** the empty `payroll_br_statutory_profiles` (the facts move to the shared block; the drop is not reversed on downgrade). Guarded/idempotent; PostgreSQL uses `SET LOCAL lock_timeout='5s'`, one `ALTER TABLE … ADD COLUMN …` (+ `ADD CONSTRAINT … NOT VALID`) and a separate `VALIDATE`; SQLite uses batch mode.
- **New tables**
  - `payroll_br_concurrent_inss_declarations` — one RECORDED declaration per employee×competência month (partial unique index `uq_br_concurrent_employee_month_open … WHERE status='RECORDED'`); a new month supersedes the prior row, history kept.
  - `payroll_br_alimony_orders` — fixed amount **or** percentage×base (CHECK `ck_br_alimony_shape`); one open order per reference (partial unique index `uq_br_alimony_employee_order_open` on employee×reference `WHERE effective_to IS NULL AND status='ACTIVE'`).
  - `payroll_br_vale_transporte_elections` — elected flag + declared daily cost (CHECK `ck_br_vt_elected_cost`); one open election per employee (partial unique index `uq_br_vt_employee_open`).
- **`brazil_employee_service.py`** (new) — profile hooks (`statutory_profile_errors` shape checks: eSocial category 101/103, 6-digit CBO, contract type, weekly hours ≤ 44, dependants evidence; `profile_values` carry-forward + same-org establishment ACTIVE on the effective date), `profile_view`/`profile_versions`, the concurrent-INSS / alimony / VT record + list + close flows, `employee_record` (identifiers masked; profiles + child records), and `employee_readiness` (profile in force, establishment ACTIVE, category/CBO/contract, both dependant sets, concurrent INSS for the month, VT election, alimony in force; Phase 5/6/9/11 items BLOCKED).
- **`brazil_service.py`** — the statutory-profile hooks now delegate to the module above; `_has_statutory_profile` reads the shared table.
- **`schemas.py`** — 10 `br_*` fields on `EmployeeStatutoryProfileCreate` (camelCase validation aliases) and matching fields on `EmployeeStatutoryProfileResponse`.
- **`brazil_schemas.py`** — `BRConcurrentInssDeclarationCreate`, `BRAlimonyOrderCreate`, `BRAlimonyOrderClose`, `BRValeTransporteElectionCreate`.
- **`brazil_org_router.py`** — `GET /employees/{id}`, `GET /employees/{id}/readiness?on=`, `POST`/`GET /employees/{id}/concurrent-inss-declarations`, `POST /employees/{id}/alimony-orders`, `PUT /alimony-orders/{id}/close`, `POST /employees/{id}/vale-transporte-elections` (all behind the Phase-3 dormancy guard).
- **`brazil_router.py`** — Super Admin read-only, masked `GET /employees/{id}?organization_id=&on=`.

**Frontend**
- `countryFieldSpecs.js` — `BR` added to `COUNTRIES` and a `COUNTRY_FIELD_SPECS.BR` block mirroring `BREmployeeValidation.FIELD_SPECS`, with **client-side CPF / PIS-NIS Modulo 11** and **CNPJ** check-digit helpers, and a PIX-key check that applies the CPF/CNPJ digits only when `pix_key_type` is CPF/CNPJ.
- `bankFieldsFor.js` — BR in `BANK_ROUTING_COUNTRIES`, `PAYMENT_MODE_LABEL.BR="PIX / TED"`, `BTF_ROUTING_LABEL.BR="PIX Key / COMPE"`, `BANKING_COMPLIANCE_KEYS.BR=["pix_key","bank_compe","bank_agency","bank_account"]`.
- `payrollService.js` — `getBrEmployeeRecord`, `getBrEmployeeReadiness`, `recordBrConcurrentInss`, `recordBrAlimonyOrder`, `closeBrAlimonyOrder`, `recordBrValeTransporte`.
- `BrazilStatutoryProfilePanel.jsx` (new) — identity block, effective-dated profile form (Employment / IRRF dependants / salário-família dependants), versions table, the three child sub-panels with their MiniForms, and the readiness table with the local-date bar.
- `EmployeeDetailPanel.jsx` — masked **Brazil identity & bank routing** block, the "Brazil statutory profile → Manage" card, and the panel mount.

**Docs**: this report; `BRAZIL_PHASE_4_PLAN.md` status updated.

## 3. Migration — locking

Captured statement sequence for PostgreSQL:
1. `SET LOCAL lock_timeout = '5s'` before any statement on the shared table.
2. **One** `ALTER TABLE payroll_employee_statutory_profiles ADD COLUMN …×(up to 10), ADD CONSTRAINT fk_br_profile_establishment … NOT VALID` — no `DEFAULT` (nullable, metadata-only).
3. `ALTER TABLE … VALIDATE CONSTRAINT fk_br_profile_establishment` (read/write continue).
4. Three `CREATE TABLE` + partial unique indexes; `DROP TABLE payroll_br_statutory_profiles`.

`test_pg_a_held_lock_makes_the_migration_fail_fast`: with another connection holding `ACCESS SHARE` the upgrade raises `lock timeout` after ~5 s and no column is added. SQLite (dev/test) uses Alembic batch mode. Downgrade removes only this revision's objects (and intentionally does not recreate the dropped legacy table).

## 4. What this does in production when merged (`BR_TENANT_ONBOARDING_ENABLED` unset → False)

| Change | Effect |
|---|---|
| Migration `br_employee_m3` | `lock_timeout=5s`; one brief `ACCESS EXCLUSIVE` on the shared table (metadata-only); FK `NOT VALID` then `VALIDATE` under `SHARE UPDATE EXCLUSIVE`; additive columns (every row NULL) + three empty tables; legacy empty table dropped. Idempotent; `check_schema_drift` compares column names only. |
| Brazilian employee creation | **Unchanged** — still refused while the flag is off. |
| New org routes | Behind the dormancy guard → 403. |
| Super Admin employee route | Read-only, masked; no Brazilian employee exists → 404/empty. |
| Sensitive-field masking | Phase 4a already classifies `cpf`, `pis_nis`, `pix_key`, `bank_account` sensitive; no other country uses those keys. |

Net: production stays as dormant as after Phase 3; the only database change is additive.

## 5. Deviations / notes

1. The shared-table split-brain decision (plan Q1) means the legacy `payroll_br_statutory_profiles` is dropped and **not** recreated on downgrade.
2. `payroll_br_concurrent_inss_declarations` uses a **partial** unique index (`… WHERE status='RECORDED'`) rather than a full unique constraint, so a superseding declaration for the same month can be inserted while the prior row is retained.
3. The frontend exposes no GET routes for alimony/VT (there are none) — the panel reads both lists from the employee record payload.
4. The feature is dormant behind the Phase-3 flag; no browser harness or live-DB migration was run this phase.

## 6. Open / prerequisites

- The two MX migrations present on `origin/main` (`c4f7a2d9e6b1`, `d8b3e5f1a2c7`) are absent on this branch — the `test_no_migration_deleted_or_renamed_against_origin_main` guard cannot pass until `venu` is reconciled with `origin/main`. Pre-existing, unrelated to Phase 4.
- A live PostgreSQL up/down/up run needs local credentials.
- Phase 4 cannot be committed until Phase 3 is committed and `venu` is reconciled.
- BR-K3 rubric codes (eSocial Tabela 09) and the D6 item remain open from earlier phases.
