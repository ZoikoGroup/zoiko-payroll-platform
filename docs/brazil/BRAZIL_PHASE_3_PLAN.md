# Brazil (BR) — Phase 3 Plan: Employer onboarding (employer, establishments, risk, credentials, readiness)

Spec: ZP-BR-ENG-001 v1.0 §11 (employer/onboarding), §24 (gates). Pattern: Mexico Phase 3 (`docs/mexico/MEXICO_PHASE_3_PLAN.md`), which is merged into `venu`.
Status: **plan — awaiting approval** (§12). Nothing in this document has been built.

## 1. Scope

**In scope**
- **Employer profile** (the legal employer, eSocial S-1000 facts):
  - effective-dated versions;
  - CNPJ root, legal and trade name, tax classification (Tabela 08 code, format only), principal CNAE;
  - the CPRB option by year, the eSocial environment and the contact person.
- **Establishments** (S-1005): CNPJ, CNAE, FPAS + third-party code and rate, lotação code, address (CEP, IBGE municipality, UF), headquarters flag.
- **Risk by year:** RAT (1 / 2 / 3 %) and FAP (0.5000–2.0000) per establishment per calendar year, with evidence.
- **Credential references:** eSocial A1 certificate and bank, stored as **references only**, never key material.
- **Employer readiness** per legal employer, mapped onto G1–G8.
- **Screens:**
  - Org Admin: Payroll → Compliances → **Brazil Compliance Centre**
  - Super Admin: a read-only Employer tab
- **Employee validator:** Brazil's switched off until onboarding is enabled (Mexico pattern, §8).
- **Org delete:** a test proving it works with Brazil rows present (BR-K9).

**Out of scope here** (each has a home phase and shows as BLOCKED in readiness):

| Item | Phase |
|---|---|
| FPAS / third-party rates checked against eSocial Tabela 04 (S7 not yet saved) | 3 data, once S7 is saved (§9 Q3) |
| CPRB sector eligibility (Lei 14.973 annex) | needs that annex as a saved source |
| eSocial S-1000 / S-1005 / S-1020 events and transmission | 9 |
| Rubric adoption by the organisation (codes unverified, BR-K3) | after eSocial Tabela 03 is saved (§9 Q7) |
| Employee ↔ establishment assignment, CPF / PIS, PIX | 4 |
| Using any of this in a calculation | 5 / 6 |

## 2. Where the screens mount

- **Org Admin.** `modules/payroll/Compliances/CompliancePage.jsx` already shows a per-country "Compliance Centre" tab for NL and MX by normalised `jurisdictionCountry`. Brazil adds `isBrazil` + `BR_TAB = "Brazil Compliance Centre"` and one render line.
  - New: `BRComplianceCentreTab.jsx` (sections: Employer, Establishments, Risk by year, Credentials) and `BRReadinessPanel.jsx` (cloned from the NL/MX panels).
  - No base tab is removed.
- **No product path creates a BR organisation yet.** BR is absent from `REGISTRATION_COUNTRIES`, so the tab is reachable only for an organisation a Super Admin or fixture set to Brazil. That is consistent with gating on G1–G8.
- **Super Admin.** A read-only `BREmployerProfileTab` in `brazilComplianceConfig.jsx`, using the existing organisation picker. The tenant owns its employer facts (§9 Q5).
- **API.**
  - New `brazil_org_router.py`, mounted inside `payroll_router` as `/api/payroll/brazil` (clone of `netherlands_org_router.py` / `mexico_org_router.py`).
  - The organisation is always `current_user.organization_id`; no route takes an org id.
  - Reads need a payroll operator; writes need an org admin.
  - Every child id is checked against the caller's organisation.
  - Super Admin reads go on the existing `brazil_router.py`.

## 3. Data model — migration `br_employer_m2` (guarded, after `b7a1c9e3d5f2`)

The Phase 0 tables exist, so this phase **extends** them. Every write is audited through `record_tax_audit`, with CNPJ / CPF masked to the last 4.

### 3.1 `payroll_br_employer_profiles` → effective-dated versions (§9 Q1)

- Add `effective_from` (required), `effective_to`, `version`, `superseded_by_id`, `created_by_id`.
- Replace `uq_br_employer_org` (one row per organisation) with "one version per (organisation, CNPJ root, effective_from)", plus "at most one open version per (organisation, CNPJ root)".
- Why: eSocial S-1000 carries validity periods (`iniValid`/`fimValid`), and a change of CNAE or tax classification must not rewrite history.
- The Phase 0 table is empty everywhere (production has no `payroll_br_*` tables), so no data migration is needed.
- **Remove** `cprb_opted` / `cprb_rate_pct` from the profile: the CPRB option is annual (§3.4).

### 3.2 `payroll_br_establishments`

- Add `active_from`, `active_to`, `deactivated_at`, `created_by_id`, and evidence fields `fpas_evidence_ref` / `fpas_status` (`DECLARED` until checked against Tabela 04, then `VERIFIED`).
- **Move** `rat_pct` / `fap_factor` out to §3.3 (they vary by year).
- Rules enforced in the service:
  - CNPJ check digits (`cnpj_is_valid`, numeric and the July-2026 alphanumeric form);
  - the first 8 characters equal the employer's CNPJ root;
  - exactly one active headquarters per employer;
  - CEP 8 digits; IBGE code 7 digits; UF one of the 27 units.

### 3.3 `payroll_br_risk_assignments` (new) (§9 Q2)

- Columns: `establishment_id`, `calendar_year`, `rat_pct` ∈ {1, 2, 3}, `fap_factor` (0.5000–2.0000, 4 decimals), `evidence_ref` (the FAP notice), `status` (DRAFT / ACTIVE / SUPERSEDED), `created_by_id`, timestamps.
- One ACTIVE row per (establishment, year): a partial unique index (`postgresql_where` + `sqlite_where`, as `ContributionRate`).
- Readiness reports "no risk assignment for the payroll year" as BLOCKED.

### 3.4 `payroll_br_cprb_options` (new)

- Columns: `employer_profile_id`, `calendar_year`, `opted` (bool), `sector_reference` (free text), `cprb_rate_pct`, `evidence_ref`, `status`.
- The option is per year. Sector eligibility is not sourced yet, so readiness gives a WARNING ("CPRB eligibility not verified") instead of PASS.

### 3.5 `payroll_br_credential_refs` (new, Mexico §4 pattern) (§9 Q4)

- Columns: `employer_profile_id`, `kind` (`ESOCIAL_A1` / `BANK`), `secret_ref`, `certificate_serial`, `fingerprint_sha256`, `subject_summary`, `valid_from`, `valid_to`, `status` (ACTIVE / ROTATED / REVOKED), `rotated_from_id`.
- One ACTIVE per (profile, kind).
- `esocial_cert_alias` on the profile is retired in favour of this table.

## 4. Secrets (A1 certificate)

- **References only**, as Germany ELSTER, NL and MX do. The repo has no secret-store client.
- `secret_ref` must:
  - start with an allowed scheme (`settings.BR_SECRET_REF_SCHEMES`, default `vault://,aws-sm://,azure-kv://,gcp-sm://`);
  - be at most 300 characters with no whitespace;
  - contain nothing that looks like key material (`-----BEGIN`, `PRIVATE KEY`, a long base64 run, PKCS#12 magic). Refusals are audited without echoing the value.
- An A1 certificate is a PKCS#12 bundle **with the private key**, so it is **never uploaded**. Optionally the org admin uploads the **public** `.cer`; the server derives serial, fingerprint, validity and subject with `cryptography` (already in `requirements.txt`) and discards the bytes.
- Readiness: expired → BLOCKED; expiring within `settings.BR_CREDENTIAL_EXPIRY_WARNING_DAYS` (default 30) → WARNING. Audit records `{kind, fingerprint, validTo}`, never `secret_ref`.

## 5. Employer readiness and G1–G8

Computed on read by `brazil_service.employer_readiness(db, org_id, on)` (`on` required, no server-date default). Each item is PASS / WARNING / BLOCKED / NOT_STARTED, with a reason and the gate it feeds.

| Item | Phase 3 can reach | Gate |
|---|---|---|
| Employer version in force on `on`; CNPJ root valid; contact CPF valid | PASS | G1 |
| ≥ 1 active establishment, one HQ, CNPJ roots consistent | PASS | G2 |
| Every establishment has an ACTIVE risk assignment for `on`'s year | PASS / BLOCKED | G2 |
| FPAS / third-party checked against Tabela 04 | **BLOCKED** until S7 is saved | G2 |
| CPRB option recorded for the year (if opted: eligibility) | PASS / WARNING | G2 |
| eSocial A1 credential reference ACTIVE, not expired | PASS / WARNING / BLOCKED | G3, G7 |
| eSocial events / DCTFWeb / FGTS Digital / parallel payroll | **BLOCKED** (Phases 9–11) | G3–G8 |

- Readiness **never signs a gate**. A LIVE-eligible employer is unreachable by construction in Phase 3, and a test pins that.
- Response shape: `{"employers": [...], "gates": gate_states(db)}`.

## 6. Endpoints

**Org (`/api/payroll/brazil`, `brazil_org_router.py`)** — reads: payroll operator; † writes: org admin.
- `GET` / `POST`† `/employers`; `POST`† `/employers/{id}/versions`
- `GET` / `POST`† `/employers/{id}/establishments`; `PUT`† `/establishments/{id}/deactivate`
- `GET` / `POST`† `/establishments/{id}/risk-assignments`; `PUT`† `/risk-assignments/{id}/activate`
- `GET` / `POST`† `/employers/{id}/cprb-options`
- `GET` / `POST`† `/employers/{id}/credentials`; `POST`† `/employers/{id}/credentials/public-certificate`; `PUT`† `/credentials/{id}/revoke`
- `GET /readiness?on=`

**Super Admin (`brazil_router.py`, read-only)**
- `GET /employers?organization_id=`
- `GET /employer-readiness?organization_id=&on=`
- `GET /employer-readiness/summary?on=`

## 7. Files

**Backend**
- New: `brazil_org_router.py`, `alembic/versions/<uuid12>_br_employer_m2.py`
- Modify:
  - `models.py`
  - `brazil_service.py` (employer, establishment, risk, CPRB, credential, readiness)
  - `brazil_schemas.py` (`extra="forbid"`, no defaults on identity or statutory fields)
  - `brazil_router.py`, `router.py` (one `include_router`)
  - `config.py` (`BR_SECRET_REF_SCHEMES`, `BR_CREDENTIAL_EXPIRY_WARNING_DAYS`, `BR_TENANT_ONBOARDING_ENABLED`)
  - `employee_validation.py` (BR → `_DORMANT_STRATEGIES`)
  - `MIGRATIONS_MANIFEST.txt`
  - `.env.example`: **not edited by me**; I will list the lines.

**Frontend**
- New:
  - `modules/payroll/Compliances/BRComplianceCentreTab.jsx`, `BRReadinessPanel.jsx`
  - `components/jurisdiction/brazil/BREmployerProfileTab.jsx`
  - `components/jurisdiction/brazil/employer/` panels shared by both views (`readOnly` prop)
- Modify: `CompliancePage.jsx`, `brazilComplianceConfig.jsx`, `payrollService.js`, `superAdminService.js`.

## 8. Employee validator dormancy (§9 Q6)

Mexico keeps its validator in `_DORMANT_STRATEGIES`, consulted only while `MX_TENANT_ONBOARDING_ENABLED` is on. Brazil's `BREmployeeValidation` is active today (Phase 0). Phase 3 moves it behind `BR_TENANT_ONBOARDING_ENABLED` (default off). Today that changes nothing reachable, because no BR organisation can register, but it keeps the two countries consistent. The Mexico/Brazil tests that list `_STRATEGIES` are updated accordingly.

## 9. Decisions needed before I build

| # | Question | Recommendation |
|---|---|---|
| Q1 | Employer profile: effective-dated versions (replacing one-row-per-org)? | **Yes** — S-1000 validity periods; the table is empty everywhere |
| Q2 | RAT / FAP per establishment **per year** in its own table? | **Yes** — FAP is published annually |
| Q3 | FPAS / third-party while Tabela 04 (S7) is unsourced | **Allow entry with an evidence reference, marked DECLARED; readiness BLOCKED until S7 is saved** — and I fetch/save S7 (with your go-ahead, as in Phase 1) |
| Q4 | A1 certificate | **References only; never upload the PKCS#12; optional public `.cer`** |
| Q5 | Super Admin authoring of employer facts | **Read-only** (Mexico), not NL-style create |
| Q6 | Brazil employee validator dormant behind `BR_TENANT_ONBOARDING_ENABLED` | **Yes** |
| Q7 | Organisation rubric adoption | **Defer** until eSocial Tabela 03 is saved and the codes are verified (BR-K3) |
| Q8 | May I fetch and save S6 / S7 / S10–S12 (eSocial documentation, Tabela 04) into `docs/brazil/sources/`, as in Phase 1? | **Yes** — it unblocks Q3 and Q7 |

## 10. Tests (synthetic, throwaway SQLite, full suite before reporting)

- **Migration:** guarded and idempotent; partial unique indexes enforced on SQLite.
- **Employer:**
  - versioning (overlap refused; history kept);
  - CNPJ / CPF check digits, including the alphanumeric CNPJ;
  - CNPJ root ↔ establishment; one HQ.
- **Risk and CPRB:** one ACTIVE per (establishment, year); out-of-range RAT / FAP refused; CPRB option per year.
- **Credentials:**
  - unknown scheme and key-like material refused, without the value appearing in audit or logs;
  - a public `.cer` is parsed and its bytes discarded; a PKCS#12 bundle is refused;
  - expiry gives WARNING / BLOCKED.
- **Readiness:** every item; LIVE-eligible unreachable.
- **Org router:**
  - tenant isolation (another organisation's child ids → 404);
  - operator vs admin;
  - no org id on any route.
- **Super Admin:** read-only.
- **Platform:**
  - `delete_organization` with Brazil rows present succeeds (BR-K9);
  - the dormant validator does not apply while the flag is off;
  - no other jurisdiction changes.

## 11. Browser checks

Local only (throwaway SQLite, local Super Admin and org admin, synthetic BR organisation) — never production, whose startup is not read-only. Screenshots of each section, the readiness panel and the Super Admin tab go to `docs/brazil/phase3-evidence/`.

## 12. Approval

Awaiting your answers to Q1–Q8 (or "go ahead" to accept every recommendation).
