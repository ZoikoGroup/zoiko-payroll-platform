# Mexico (MX) — Phase 4 Plan: Employee statutory profile

Spec ZP-MX-ENG-001 v1.0 §12 (employee onboarding: Identity, Employment, Pay, IMSS, INFONAVIT, ISR, Benefits, State ISN), MX-036, MX-037, MX-038, MX-031/032, MX-035, MX-061 · plan v1.1 §7 · builds on Phase 3 (employers, establishments, IMSS registrations).
Baseline: `nikhil` after the Phase 3 follow-up (`878dc00`) and the production-state docs. **Approved 2026-10-16 with changes (§14). Delivered in two PRs: 4a (dormancy only) first, 4b after 4a is merged.**

Rules carried forward: stage only; zero behaviour change for other jurisdictions; never infer a statutory value; fail closed while content is empty; nothing Active by code; and — new — **merging to `main` deploys to production and runs Alembic: Mexico must stay dormant and fail-closed, every migration additive and guarded** (§9).

---

## 1. Scope

**In**
- **Dormancy controls first** (closes the two gaps in `PRODUCTION_STATE.md` §2c, and keeps Phase 4 dormant in production).
- Mexico employee validation strategy: RFC (persona física), CURP, NSS, CLABE — format, plus check digits only where a saved source states the algorithm.
- `EmployeeStatutoryProfile` `mx_*` columns (effective-dated versions, existing shared mechanism) through the existing `statutory_profile_errors` / `statutory_profile_values` hooks.
- Employment attributes that drive later phases: establishment, work state/municipality (MX-038), IMSS registration, contract/regime/workday/job-risk/pay-frequency codes, salary type and daily salary, seniority date.
- Identifier cross-checks as **exceptions**, never auto-fixes (MX-036).
- INFONAVIT credit notices — operator-recorded authority notices (MX-031), no invented rate.
- CLABE in bank routing (MX, CLABE, SPEI) — validation only; no payment file (Phase 10).
- Employee readiness (per employee) feeding the employer readiness / G-gates.
- Org UI on the employee screen; Super Admin read-only view.

**Out (with home phase)**: SBC computation, SBC history and variable accumulators (Phase 5 — engine outputs); benefit accrual ledgers (Phase 5/9); IMSS/IDSE movements (Phase 8); termination fields (Phase 9); CFDI receiver validation against SAT (Phase 7); payroll preflight that consumes the exceptions (Phase 6).

## 2. Dormancy first — **Phase 4a, its own PR** (production safety, and the Phase 3 gaps)

One setting, **`MX_TENANT_ONBOARDING_ENABLED: bool = False`** (config.py; *not* set in production `.env`, set in tests/harness). Phase 4a contains only this setting, the gates below and `test_mexico_dormancy.py` — no migration, nothing else. Its production effect is **tightening only**.

How an organisation can become "Mexican" today (verified on a scratch DB, 2026-10-16), and the 4a gate on each:

| Path | Today | Phase 4a (flag False) |
|---|---|---|
| Sign-up — trial (`register_trial`) and enterprise (`register_enterprise`) | refused: MX not in `REGISTRATION_COUNTRIES`; enterprise runs `get_jurisdiction_onboarding_block_reason` | unchanged (pinned by a test) |
| `PUT /organizations/me` and the Super Admin organization update → `Organization.country = "Mexico"` | **allowed** (MX not in `_REGISTRY_ROW_REQUIRED_COUNTRIES`); `get_company_details` then back-fills `jurisdiction_country = MX` | refused by a Mexico-only branch in `get_jurisdiction_change_block_reason` (both callers); the back-fill skips MX |
| `PUT /payroll/compliance/company` → `jurisdictionCountry = "MX"/"Mexico"` on an org with no jurisdiction chosen | **allowed** | refused by a Mexico-only branch in `update_company_details` |
| `/api/payroll/mexico/...` org routes (21) | any subscribed org admin / payroll admin | router-level guard: refused unless the flag is on **and** the caller's organisation resolves to MX |
| MX employee creation | refused (`Unsupported country code 'MX'`) | unchanged in 4a; in 4b the MX strategy sits in a separate map consulted only with the flag on, so the "Supported: …" message for every other country never changes |

Super Admin read routes stay available (read-only). The flag is the single switch Phase 10 replaces with the service-registry `AVAILABLE` state (G1–G8 signed); it is not a substitute for those gates.

**Recovery for an organisation already locked into MX** (see `PRODUCTION_STATE.md` §2c/§6): `update_company_details` refuses any change once a real jurisdiction is chosen (HTTP 423 "requires a controlled migration process"), and **no governed path exists today** to change a locked `CompanyComplianceDetails.jurisdiction_country` — no Super Admin endpoint writes that column. `Organization.country` can be changed by a Super Admin through the organization update (passing the registry gate), but that does not rewrite an already-set compliance jurisdiction. Correction is therefore an operator database change, approved and recorded by a Super Admin (old/new value, reason, ticket), done only while the org has no MX employees and its `payroll_mx_*` rows have been reviewed. A governed "controlled jurisdiction migration" for Super Admin is a platform item, not built here.

## 3. Identifiers (spec §12 Identity, MX-035, MX-036, MX-061)

Storage follows the existing HK/NL pattern (verified in `employee_validation.py`): the raw value lives in the employee's `compliance_fields` (needed later for the CFDI receiver node), declared in the strategy's `SENSITIVE_FIELDS` so it is **masked in every API response**; the statutory profile holds only keyed tokens and last-4 for matching and display.

**Plaintext at rest — stated explicitly.** `compliance_fields` is a JSON column with **no application-level encryption** for any country. RFC, CURP, NSS and CLABE would therefore be stored in clear in the database row, exactly like the HKID — the finding in `docs/HONG_KONG_RELEASE_EVIDENCE/G5/ENCRYPTION_AT_REST_ASSESSMENT.md` (§1: no Fernet/AES/pgcrypto anywhere; storage-layer encryption, fact **F2**, UNVERIFIED) and the open owner decision **D-4 "Encryption at rest"** in `HK_OWNER_DECISION_REGISTER.md` (A provider encryption verified / B application-level, platform-wide / C = A + CMEK). **Decision Q9 (security lead):**
- **Q9-a — application-level encryption for MX identifiers only**: encrypt `rfc`, `curp`, `nss`, `clabe` in `compliance_fields` with a key in GCP Secret Manager (`MX_IDENTIFIER_ENCRYPTION_KEY`, envelope / per-value nonce), decrypted only in the CFDI/IDSE builders (Phase 7/8). Mitigates leaked dumps and backups; not a compromised app server. Mexico-only, but a second pattern that platform-wide option B would later replace.
- **Q9-b — known risk tied to HK D-4**: no MX-specific encryption; Mexico inherits the platform-wide D-4 outcome (A, B or C), with the deploy owner's F1–F7 facts recorded before Mexico goes LIVE, as a G7 prerequisite ("Certificates/secrets, personal identifiers … signed").
- Engineering recommendation: **Q9-b**, unless the security lead wants Mexico to pilot option B. No MX identifier is captured before 4b, and none in production while the flag is off.

**Duplicate-identifier message.** The shared duplicate check answers `An employee with <FIELD> '<value>' already exists` with the **full value**. For Mexico (4b) the duplicate message uses the masked value (`mask_identifier`), so a 409 never echoes a full CURP (MX-061); other countries unchanged.

| Identifier | Phase 4 check | Source | Not checked until a source is saved |
|---|---|---|---|
| RFC (persona física, 13) | format `^[A-ZÑ&]{4}[0-9]{6}[A-Z0-9]{3}$` + real YYMMDD (reuses the Phase 3 validator) | `core/jurisdiction.py` schema / plan §7 | SAT check digit; SAT registry match (Phase 7) |
| CURP (18) | format only (structure from the RENAPO standard) | **needs a source** — proposed **S31** (RENAPO CURP instructivo) | check digit; RENAPO validation |
| NSS (11) | 11 digits | plan §7 | check digit — proposed **S32** (IMSS) |
| CLABE (18) | 18 digits | plan §7 | check digit — proposed **S33** (Banxico/ABM CLABE standard) |

**Decision Q2:** add S31–S33 to the addendum (with fetch checklists) and implement the check digits only once saved; until then `mx_identifier_validation_status = FORMAT_ONLY`, never `VALID`.

**Cross-consistency (MX-036).** RFC↔CURP↔name/date-of-birth consistency is a **preflight exception**, never a refusal and never an auto-fix: the profile records `mx_identifier_validation_status` (`FORMAT_ONLY` / `VALID` / `MISMATCH`) plus the finding; Phase 6 preflight blocks the employee. The comparison rule (which characters must agree) is taken from S31/SAT text once saved — **Decision Q3**; until then the cross-check reports "not checked — source pending".

**Tokens.** `mx_rfc_token`, `mx_curp_token`, `mx_nss_token` = HMAC-SHA256 under a dedicated **`MX_IDENTITY_TOKEN_KEY`** (GCP Secret Manager in production), HK D-19 pattern. **Q7 (approved, stricter than HK):** the fallback derived from `PAYROLL_SECRET_KEY` is used **only in development/test**; with the flag on in production mode (the same environment test `app/config.py`'s fail-closed guards use) and `MX_IDENTITY_TOKEN_KEY` missing, every MX identifier write is **refused** ("MX_IDENTITY_TOKEN_KEY is not configured") and readiness shows it BLOCKED (G7). Test `test_mexico_identity_token_key.py`: production mode + flag on + no key → refused; dev → fallback; production + key → works; the key value never appears in a response, audit row or log. Duplicate detection within the organisation uses the CURP (`duplicate_field = "curp"`).

**Rehire under the duplicate-CURP rule.** The duplicate check covers every employee of the organisation, terminated ones included, so a returning person is **not** created as a second employee record — the (masked) 409 points to the existing employee. A rehire is the **same** `PayrollEmployee` reactivated (status back to ACTIVE through the existing employee update) plus a **new effective-dated Mexico statutory profile version** from the rehire date: new establishment / registration if changed, and a new `mx_seniority_date` unless a legal continuity rule applies (taken from S26 at transcription — never assumed). Earlier versions and committed results stay intact, so the first employment's history (and any finiquito, Phase 9) keeps its own data. The IMSS re-entry movement (*reingreso*) is generated from that version in Phase 8. Concurrent employment in two *organisations* is unaffected (the check is per organisation).

## 4. Data model — migration `mx_employee_m3`

Additive and guarded (`_has_column` / `_has_table` / `_has_index`), single child of the head that exists when 4b is built (`6e4a1d9c3f27` today).

**Locking on the shared table** (approved change 5, improving on the Switzerland migrations on the same table, which add columns one `op.add_column` per statement — one `ACCESS EXCLUSIVE` lock each — with immediately-validated FKs):
1. `SET LOCAL lock_timeout = '5s'` (PostgreSQL only) before touching `payroll_employee_statutory_profiles`: if a long transaction holds the table the migration fails fast instead of queueing every payroll read behind it; the deploy fails visibly and is re-run, nothing half-applied.
2. **One** `ALTER TABLE payroll_employee_statutory_profiles ADD COLUMN …, ADD COLUMN …` for all new columns — one brief `ACCESS EXCLUSIVE` lock, metadata-only (every column nullable, no default — no rewrite). Columns already present (re-run) are skipped by the guard.
3. The two FKs as `ADD CONSTRAINT … FOREIGN KEY … NOT VALID` in that same statement (no scan), then `ALTER TABLE … VALIDATE CONSTRAINT …` separately (`SHARE UPDATE EXCLUSIVE` — reads and writes continue; trivially valid, every value is NULL).
4. SQLite (dev/test): plain `batch_alter_table`, no lock settings.
5. `payroll_mx_infonavit_notices` is a new table (no lock on existing data).

**4.1 `payroll_employee_statutory_profiles` — new nullable `mx_*` columns** (shared table; `ALTER TABLE … ADD COLUMN` nullable, no default — no rewrite, no effect on other countries' rows):

| Group | Columns |
|---|---|
| Identity | `mx_rfc_token`, `mx_rfc_last4`, `mx_curp_token`, `mx_nss_token`, `mx_identifier_validation_status`, `mx_identifier_findings` (JSON), `mx_fiscal_postal_code`, `mx_receiver_fiscal_regime` |
| Employment | `mx_establishment_id`, `mx_imss_registration_id`, `mx_work_state`, `mx_work_municipality`, `mx_remote_state_exception_ref`, `mx_seniority_date`, `mx_contract_type_code`, `mx_regime_type_code`, `mx_workday_type_code`, `mx_job_risk_code`, `mx_professional_min_code` |
| Pay | `mx_pay_frequency_code`, `mx_daily_salary`, `mx_salary_type` (FIXED/VARIABLE/MIXED) |
| ISR | `mx_annual_adjustment_exclusion` (declaration code), `mx_annual_adjustment_exclusion_evidence_ref` |

Deviations from plan v1.1 §7 (**Decisions Q4–Q6**):
- **`mx_min_wage_zone` not stored** — derived from work state + municipality via the transcribed ZLFN list (as Phase 3 establishments); UNRESOLVED while S9 is empty.
- **`mx_subsidy_eligible` / `mx_annual_adjustment_eligible` not stored** — eligibility is an engine result (Phase 5) from income and content; a typed flag would be an arbitrary tax field (§12 "No arbitrary personal tax-rate field"). Only the employee's *declared* exclusion and its evidence are recorded.
- **`mx_termination_date` / `mx_termination_reason` → Phase 9.**
- `mx_establishment_id` / `mx_imss_registration_id` are nullable **foreign keys** (`ondelete=SET NULL`) to `payroll_mx_establishments` / `payroll_mx_imss_registrations` — the Switzerland precedent on this same shared table (`ch_bvg_plan_scheme_id` etc. → `payroll_ch_scheme_profiles`) — plus service checks (same organisation, same legal employer, registration ACTIVE on the profile's effective date).

**4.2 New table `payroll_mx_infonavit_notices`** (plan v1.1 §7): `id, organization_id, employee_id, credit_number, notice_type (RETENCION/SUSPENSION/MODIFICACION), discount_method (FIXED_AMOUNT/PERCENTAGE/VSM/UMA_FACTOR), discount_value, effective_from, effective_to, authority_reference, evidence_document_id → payroll_compliance_documents, status (RECORDED/SUPERSEDED/CLOSED), recorded_by_id, created_at`. Partial unique index on (`employee_id`, `credit_number`) WHERE `effective_to IS NULL`. The discount value is **copied from the authority notice** with its evidence — the only way a credit deduction can exist (MX-031: "may not invent a mortgage deduction rate"). Nothing deducts it until Phase 5.

**4.3 Deferred tables** (**Q4**): `payroll_mx_sbc_history`, `payroll_mx_variable_accumulators`, `payroll_mx_benefit_accruals` are engine outputs and move to Phase 5, created together with the code that writes them.

## 5. Validation rules (service, all Mexico-only)

- **Work state (MX-038)** — required; one of the 32 federal-entity codes; defaults from the chosen establishment but is the employee's own statutory attribute; a work state that differs from the establishment's needs `mx_remote_state_exception_ref` (exception workflow, §12 State ISN). Unsupported ISN state → the employee's ISN status is BLOCKED (MX-045), not refused (the employee may still be recorded).
- **Establishment / registration** — same organisation and same legal employer; registration ACTIVE on the profile's `effective_from`.
- **Catalog codes** (contract, regime, workday, job risk, pay frequency, receiver fiscal regime, postal code) — stored as entered; checked against an **Active** CFDI catalog release (S28 Nómina catalogs; S30 for `c_RegimenFiscal` / `c_CodigoPostal`); with none Active the readiness item is BLOCKED ("Phase 7"), never guessed.
- **Professional minimum** — if set, must exist among the Active pack's `MX_MIN_WAGE` PROFESSION rows on the effective date; empty content → cannot be set (refused with the reason).
- **Daily salary vs minimum wage** — compared against the Active pack's minimum for the derived zone/profession on the effective date; below → exception; content missing → "not checked".
- **Salary type** FIXED/VARIABLE/MIXED recorded; the SBC itself is not entered or computed here (MX-037: SBC and pay displayed separately — the SBC card arrives with the engine).
- Versions: each save is a new effective-dated version; fields not sent carry forward (NL `_nl_profile_values` pattern); overlap refused by the existing shared guard.

## 6. Endpoints

Shared, already routed (hooks replaced for MX only): `GET/POST /api/payroll/employees/{id}/statutory-profile`, `GET …/history` — MX validation via `statutory_profile_errors` / `statutory_profile_values`.

Org (`/api/payroll/mexico`, behind the §2 guard): `GET /employees/{id}` (everything Mexico holds for one employee, identifiers masked), `GET /employees/{id}/readiness?on=` (required `on`), `POST /employees/{id}/infonavit-notices`, `PUT /infonavit-notices/{id}/close`.

Super Admin (read-only, masked): `GET /super-admin/compliance/mexico/employees/{id}?organization_id=` and the existing `/employees` list gains profile status.

## 7. Readiness (per employee) → gates (spec §22 definitions, as Phase 3)

| Item | Gate |
|---|---|
| RFC/CURP/NSS format and cross-check status | G1 (CFDI receiver) · NSS also G2 |
| Receiver fiscal regime / postal code / contract / regime / workday / pay-frequency codes in an Active catalog | G1 |
| Registration assigned and ACTIVE, job-risk code | G2 |
| INFONAVIT notice recorded with evidence (only when a credit exists) | G3 |
| Work state supported for ISN | G4 |
| Minimum-wage zone resolved; salary ≥ minimum | G5 |
| CLABE format / check digit | G6 (bank workflow) |
| Dedicated `MX_IDENTITY_TOKEN_KEY` configured | G7 |
| Remote/multi-state exception reference | unmapped |

Employer readiness (Phase 3) gains a summary line "employees with blocking exceptions". LIVE stays unreachable.

## 8. Frontend

- Employee screen (spec route "People → Employee → Payroll → Mexico"; repo equivalent: the employee detail panel): **`MexicoStatutoryProfilePanel.jsx`** mounted in `EmployeeDetailPanel.jsx` when `employee.countryCode === "MX"` (NL pattern, one added block), sections Identity / Employment / Pay / IMSS / INFONAVIT / ISR / Benefits (read-only floor reference) / State ISN, with the readiness list and a local-date `on` bar.
- `countryFieldSpecs.js` MX block (RFC, CURP, NSS — masked), `bankFieldsFor.js` + `BANK_ROUTING_COUNTRIES` MX (CLABE, SPEI) — inert unless an MX employee exists.
- `MXInfonavitNoticePanel.jsx`. The SBC explainability card moves to Phase 5.
- Super Admin: employee detail drawer in the Mexico workspace (read-only).

## 9. What this does in production when merged

**Phase 4a PR** (no migration): only the §2 gates — every currently reachable Mexico org route starts refusing, and no organisation can newly select Mexico through `Organization.country` or the company jurisdiction. Nothing else changes.

**Phase 4b PR:**

| Change | Production effect with `MX_TENANT_ONBOARDING_ENABLED` unset (False) |
|---|---|
| Migration `mx_employee_m3` — locking | `lock_timeout = 5s`; one `ALTER TABLE` → one brief `ACCESS EXCLUSIVE` lock on `payroll_employee_statutory_profiles` (metadata-only, milliseconds when uncontended); FKs `NOT VALID` then `VALIDATE` under `SHARE UPDATE EXCLUSIVE` (reads/writes continue). If the lock is not obtained within 5 s the deploy step fails cleanly and is re-run; the old code keeps serving until restart. |
| Migration `mx_employee_m3` | Adds ~25 **nullable** columns to `payroll_employee_statutory_profiles` (no default → metadata-only `ADD COLUMN` on Postgres, no table rewrite, existing rows NULL; the two reference columns carry nullable FKs to the Phase 3 Mexico tables, checked trivially since every existing value is NULL) and one empty table `payroll_mx_infonavit_notices`. Guarded and idempotent; `deploy_migrate.sh` + the head check + `check_schema_drift` run as in PR #101. Downgrade drops only Mexico objects. |
| Org router guard | **Tightens** production: every `/api/payroll/mexico/...` route that is reachable today (21, PRODUCTION_STATE §2b) starts refusing. Any rows a tenant may already have created stay untouched (readable by Super Admin; see the count query in PRODUCTION_STATE §6). |
| Company jurisdiction gate | **Tightens**: no organisation can newly select Mexico. An org that already selected `MX` keeps it (the jurisdiction lock already prevents changing it); it simply cannot use the Mexico routes. |
| MX validation strategy (dormant map) | No change: MX employee creation is still refused with the same message; other countries' messages unchanged. |
| Statutory-profile hooks | Unreachable (no MX employees). |
| New org routes (§6) | Behind the guard → refused. |
| Super Admin routes | Read-only, masked; return empty sets. |
| Bank routing MX | Inert (no MX employee); no payment file exists for MX. |
| Settings | `MX_TENANT_ONBOARDING_ENABLED` defaults False; `MX_IDENTITY_TOKEN_KEY` optional (only used when the flag is on). Nothing needs adding to the production `.env`. |

Net effect: Phase 4 makes production **more** dormant than today. Before the merge, the PR description must state: migration name, "additive/guarded", the flag default, and the two tightenings above.

## 10. Tests

| File | Proves |
|---|---|
| `test_mexico_dormancy.py` (**4a**) | Flag off: every org route 403; `Organization.country`→Mexico refused (org admin and Super Admin); company jurisdiction MX/Mexico refused; back-fill skips MX; sign-up refuses MX; MX employee creation refused with the unchanged message; other countries' paths unchanged. Flag on: org guard refuses a non-MX org and accepts an MX org. |
| `test_mexico_identity_token_key.py` (4b) | Q7: production mode + flag on + no `MX_IDENTITY_TOKEN_KEY` → refused; dev fallback; key never echoed. |
| `test_mexico_employee_validation.py` | RFC física / CURP / NSS / CLABE formats; `FORMAT_ONLY` without sources; check digits only with synthetic monkeypatched rules; masking in responses; duplicate CURP refused within an org, allowed across orgs; tokens stable and keyed. |
| `test_mexico_statutory_profile.py` | Versioning + carry-forward; establishment/registration same-employer and ACTIVE checks; work state ≠ establishment needs exception ref; catalog codes BLOCKED with no Active release; professional minimum refused while content empty; salary-vs-minimum exception with synthetic Active content; cross-check MISMATCH recorded, never rewritten (MX-036). |
| `test_mexico_infonavit_notices.py` | Evidence required; one open notice per credit; supersede/close; no rate without a notice; tenant isolation. |
| `test_mexico_employee_readiness.py` | Gate mapping with §22 definitions; unmapped items; `on` required; employer summary line. |
| `test_mexico_employee_migrations.py` | Upgrade/downgrade guarded and idempotent; columns nullable with no default; other countries' profile rows untouched (round-trip an NL and an HK profile through the migration). |
| Updated | alembic head/count, `_GUARDED`, manifest, MX migrations parity, content test (if S31–S33 added), Phase 3 org-router tests (enable the flag in their fixture). |

Full backend suite before reporting; `check:undefined`, lint (no new errors), build.

## 11. Browser checks (real Chrome, inspected screenshots → `docs/mexico/phase4-evidence/`)

Harness as Phase 3 (scratch SQLite, `@example.com` users), with the flag **on** for the MX flows and a second backend run with the flag **off**:
1. Flag off: org admin of an MX org gets the dormancy message in the Mexico Compliance Centre; company-details jurisdiction picker refuses Mexico; Super Admin views still load.
2. Flag on: create an MX employee; Mexico statutory panel renders all §12 sections; RFC/CURP/NSS shown masked after save.
3. Bad CURP format refused field-level; valid → `FORMAT_ONLY` badge with "check digit not verified — source pending".
4. Work state ≠ establishment without exception ref → refused; with ref → saved, ISN status shown.
5. Catalog-code items BLOCKED ("Phase 7"); professional minimum cannot be set (content empty, reason shown).
6. INFONAVIT notice: refused without evidence; recorded with evidence; supersede.
7. Employee readiness with gates / unmapped; employer readiness shows the employee-exceptions line.
8. Regression: NL employee detail panel unchanged; HK employee create unchanged; NL/HK company details unchanged.
9. No unexpected 4xx/5xx; no console errors beyond provoked refusals.

## 12. Order of work

1. Dormancy controls + tests (lands first, so Phase 4 is safe to merge even half-built).
2. Migration + model columns + notice table.
3. Validation strategy (dormant map), tokens, profile hooks, notices, readiness.
4. Org/Super Admin routes; frontend panel and field specs.
5. Full suite, lint, build, browser run, `MEXICO_PHASE_4_IMPLEMENTATION_REPORT.md` (with the §9 production table), stage, stop.

## 13. Decisions needed

| # | Question | Recommendation |
|---|---|---|
| Q1 | Dormancy switch: one setting `MX_TENANT_ONBOARDING_ENABLED` (default False, unset in production) gating org routes, company-jurisdiction MX and MX employee creation — included as the first Phase 4 item? | Yes. It closes both Phase 3 gaps and keeps every later phase dormant until Phase 10 replaces it with registry AVAILABLE. |
| Q2 | Check digits for CURP, NSS, CLABE: add sources S31 (RENAPO CURP), S32 (IMSS NSS), S33 (Banxico/ABM CLABE) and implement only once saved? | Yes; format-only (`FORMAT_ONLY`) until then. |
| Q3 | RFC↔CURP↔name/DOB cross-check: rule taken from S31/SAT text once saved; mismatch = exception (never refusal/auto-fix)? | Yes. |
| Q4 | Defer `sbc_history`, `variable_accumulators`, `benefit_accruals` to Phase 5 with the engine that writes them? | Yes. |
| Q5 | Drop `mx_subsidy_eligible` / `mx_annual_adjustment_eligible` (engine results) and record only the declared exclusion + evidence? | Yes. |
| Q6 | Termination columns to Phase 9? | Yes. |
| Q7 | Dedicated `MX_IDENTITY_TOKEN_KEY` in GCP Secret Manager, HK-style derived fallback in dev/test, readiness flags it when missing? | Yes. |
| Q9 | Raw MX identifiers in `compliance_fields` are plaintext at rest (as HKID; HK G5 assessment F2, owner decision D-4). Q9-a application-level encryption for MX identifiers, or Q9-b known risk tied to D-4 (G7 prerequisite)? | **Security lead to decide**; engineering recommends Q9-b. |
| Q8 | Nullable FKs from the shared statutory-profile table to the Mexico establishment / registration tables (CH precedent on the same table), plus service-level ownership checks? | Yes — integrity in the database; the columns stay NULL for every other country. |

## 14. Approval changes (2026-10-16)

1. **Split delivery**: Phase 4a (flag, org-router guard, jurisdiction gates, `test_mexico_dormancy.py`; no migration) is its own PR, built first; 4b starts after 4a is merged.
2. `PRODUCTION_STATE.md` §6 count query covers organisations whose jurisdiction is MX; recovery note (§2): no governed path changes a locked jurisdiction — a recorded, Super Admin–approved operator correction until one is built.
3. Q7 stricter: never the derived fallback outside dev/test; refuse when the flag is on in production mode without `MX_IDENTITY_TOKEN_KEY` (4b, with a test).
4. Plaintext at rest stated explicitly; Q9 for the security lead.
5. `mx_employee_m3`: `lock_timeout`, one `ALTER TABLE`, FKs `NOT VALID` + separate `VALIDATE`; locking in §9.
6. Rehire behaviour under the duplicate-CURP rule (§3).
7. Q1–Q8 approved as recommended. S31–S33 added to the addendum with fetch checklists; the content module's source list gains them in 4b with the other backend changes.
