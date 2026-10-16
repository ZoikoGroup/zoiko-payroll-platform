# Mexico (MX) — Phase 3 Plan: Employer onboarding and registrations

Spec: ZP-MX-ENG-001 v1.0 §11 (panels A–H), with MX-002, MX-024, MX-026, MX-034, MX-035, MX-045, MX-051, §20 and §22.
Plan: `MEXICO_IMPLEMENTATION_PLAN.md` v1.1 §6, plus the employer-profile items moved there from §5 (*[v1.1 Phase 2 Q1]*).
Baseline: branch `nikhil` at 651948a (Phase 2 committed), on top of e77ff16 (origin/main merge).
Status: **approved 2026-10-16** with the answers and corrections in §19; §19 overrides anything above it.

The usual rules apply:
- Stage only; you commit.
- No other jurisdiction changes behaviour.
- No statutory value is typed in or inferred.
- Every check fails closed while its content is empty.
- Nothing is ever set Active by code.

---

## 1. Scope

**In scope**
- Employer profile (panels A and B), versioned and effective-dated.
- Establishments.
- IMSS employer registrations. An employer can have several (MX-002).
- Risk premiums per registration and per premium period (MX-024, MX-026).
- INFONAVIT operating model (panel D).
- State ISN registrations (panel E). Only states in scope can register; Phase 2 makes that CDMX.
- Labour policy (panels F and G), with statutory-floor checks.
- Credential references for CSD, PAC, IDSE, SUA and bank (MX-035).
- Employer readiness (panel H), mapped onto G1–G8.
- The org-admin screens and the Super Admin Employer tab.

**Out of scope here.** Each item has a home phase. Phase 3 shows it as BLOCKED (with the reason) wherever it affects readiness.

| Item | Phase |
|---|---|
| Stamp test against a PAC; resolving any secret reference | 7 |
| SAT RFC/name consistency check (panel A's "hard validation") | 7, via the PAC |
| IDSE, SUA and SIPARE transport, and SUA reconciliation | 8 |
| Employee work state, establishment assignment, CLABE | 4 |
| Using any of this in a calculation | 5 |
| Payroll bank workflow, parallel payroll, gate evidence sign-off | 10 |

---

## 2. Where the screens mount

### 2.1 Org admin

The spec route "Settings → Countries → Mexico → Employer & Registrations" **does not exist in this repo**. Countries have no Settings tree. Every jurisdiction with org-side set-up uses the same pattern instead:
- **Payroll → Compliances → a per-country "Compliance Centre" tab**, in `modules/payroll/Compliances/CompliancePage.jsx`.
- It is shown only when the org's `jurisdictionCountry` normalises to that country.
- Existing examples: `NLComplianceCentreTab`, `HKComplianceCentreTab`, `SAComplianceCentreTab` and the SG and IT tabs.

**Proposed mount:** Payroll → Compliances → **Mexico Compliance Centre** → section **Employer & Registrations**, with panels A–H laid out as in spec §11.
- New file: `modules/payroll/Compliances/MXComplianceCentreTab.jsx`.
- Readiness panel H: `MXReadinessPanel.jsx`, cloned from `NLReadinessPanel.jsx`.
- In `CompliancePage.jsx`, add one line, `...(isMexico ? [MX_TAB] : [])`, where `isMexico = normalizeCountryCode(companyDetails.jurisdictionCountry) === "MX"`, and one render line. NL already shows this exact pattern.
- No base tab is removed. The generic Tax Configuration tab stays, unlike NL. Removing it would be a behaviour choice for you to make; see §18 Q6.

**Gap to note.** No product path creates an MX organisation yet:
- MX is deliberately absent from `REGISTRATION_COUNTRIES` and `SUPPORTED_COUNTRY_CODES` (Phase 0 decision 1).
- So the tab is reachable only for an org whose country was set to MX by a Super Admin or a fixture.
- That is consistent with gating live payroll on G1–G8. Phase 3 does not change it.

### 2.2 Super Admin

- **Employer tab.** `MXEmployerProfileTab`, moved here from Phase 2. It goes into `config/jurisdictions/mexicoComplianceConfig.jsx`, whose Phase 2 comment ("The Employer tab arrives with its table in Phase 3") marks the place.
- It reuses the existing org picker in `MXCompliancePage.jsx` (`/mexico/organizations`).
- It is **read-only**: panels A–H and the readiness card for the selected org. Super Admin does not author an employer's facts; the tenant owns them (§18 Q5).
- NL lets a Super Admin create an employer profile (`NLEmployerProfileTab` → `createNlEmployerProfile`). I recommend Mexico does not copy that.
- **Readiness G1–G8 tab** (exists from Phase 2) gains a "per-employer readiness" table. It is a count of employers and the first blocking item for each.

### 2.3 API mount

New file **`mexico_org_router.py`**, mounted inside `payroll_router` as `/api/payroll/mexico`. It is a clone of `netherlands_org_router.py`, so the subscription gate applies and the house rules come with it:
- The org is always `current_user.organization_id`. No route takes an org id.
- Reads need `get_current_payroll_operator`. Writes need `get_current_org_admin`.
- Every child id is checked against the caller's org before the service runs.

Plan v1.1 §6 put the readiness endpoint in `router.py` (France pattern). The NL org-router pattern is newer and keeps `router.py` to a single `include_router` line, so I recommend that instead.

The Super Admin reads go on the existing `mexico_router.py` (`/super-admin/compliance/mexico/...`).

---

## 3. Data model — migration `mx_employer_m2`

The migration is guarded and idempotent (`_has_table`/`_has_index`), with `down_revision` set to the single head at build time (currently `5d2c8f1a7b3e`). Every table carries `created_by_id`, `created_at` and `updated_at`. Every write is audited through `record_tax_audit`, with secret references and RFCs masked (§4.5).

Deviations from plan §6 are marked **Δ** with the reason.

### 3.1 `payroll_mx_employer_profiles` (panels A and B)

**Columns**
- `id`, `organization_id` (NOT NULL)
- `version`, `previous_version_id`, `effective_from` (NOT NULL), `effective_to` — **Δ**, NL pattern
- `taxpayer_type` (MORAL / FISICA) — **Δ**, see §5
- `rfc`, `legal_name`, `fiscal_regime_code`, `fiscal_postal_code`, `fiscal_address` (JSON), `place_of_issue_postal_code`
- `withholding_obligation_active`
- `tax_contact`, `bank_contact` (JSON)
- `pac_provider`, `pac_environment` (SANDBOX / PRODUCTION)
- `stamp_test_status` (NOT_TESTED, and only that in Phase 3), `stamp_test_uuid`, `stamp_tested_at`

**Δ Columns removed**
- **CSD/PAC secret columns** (`csd_*`, `pac_credential_secret_ref`) → moved to `payroll_mx_credential_refs` (§4). Rotation history and IDSE-per-registration do not fit as single columns.
- **`infonavit_operating_model`** → moved to the IMSS registration (§7), because payment goes by Registro Patronal.
- **`readiness_status` / `readiness_evidence`** → computed on read (§10). A stored status goes stale the moment any underlying row changes.

**Behaviour**
- A change is a new version from its `effective_from`; the previous open row is closed. Nothing is edited in place (NL `create_employer_profile` pattern).
- The RFC cannot change across versions. A different RFC is a different legal employer, so it gets a new profile chain.

**Indexes**
- `uq_mx_employer_org_rfc_open` on (`organization_id`, `rfc`) WHERE `effective_to IS NULL`. This is a partial index, because `effective_to` is nullable and NULLs are distinct in a unique index.
- `uq_mx_employer_org_rfc_from` on (`organization_id`, `rfc`, `effective_from`).

An org may hold several RFCs (MX-002: tenant ≠ legal employer). RFC uniqueness is **per org only**. A cross-tenant check would leak another tenant's existence.

### 3.2 `payroll_mx_establishments`

**Columns**
- `id`, `organization_id`, `employer_profile_id`, `name`
- `state_code` (must be one of the 32 `MX_FEDERAL_ENTITIES` codes), `municipality_code`, `postal_code`
- `imss_registration_id`, `is_active`

**Behaviour**
- **Δ `min_wage_zone` is derived, not typed.** It is resolved from `MX_ZLFN_MUNICIPALITIES` (state + municipality) on the date asked. While that content is empty it shows **UNRESOLVED** and blocks readiness. A typed zone would be a statutory fact entered by the tenant.
- The establishment's IMSS registration must belong to the same employer profile.

**Index**
- `uq_mx_estab_profile_name_active` on (`employer_profile_id`, `name`) WHERE `is_active`.

### 3.3 `payroll_mx_imss_registrations`

**Columns**
- `id`, `organization_id`, `employer_profile_id`
- `registro_patronal`, `risk_class`, `fraction`, `subdelegation_code`
- `effective_from` (NOT NULL), `effective_to`
- `status` (DRAFT / ACTIVE / CLOSED)
- `infonavit_operating_model` (SUA / SIPARE) — **Δ** from the profile
- `payment_account_ref`, `payment_account_last4` — **Δ**, panel D "payment account"; reference only, CLABE validation is Phase 4

**Behaviour**
- An employer may hold any number of registrations.
- No two open rows may share a Registro Patronal within the org.
- Overlapping windows for the same Registro Patronal are refused in the service. SQLite has no EXCLUDE constraint, the same reason `CollectiveAgreement` gives.

**Indexes**
- `uq_mx_imss_org_rp_open` on (`organization_id`, `registro_patronal`) WHERE `effective_to IS NULL`
- `uq_mx_imss_org_rp_from` on (`organization_id`, `registro_patronal`, `effective_from`)

### 3.4 `payroll_mx_risk_premiums`

**Columns**
- `id`, `registration_id`, `determination_year`, `premium_rate_pct`
- `period_from`, `period_to` (both NOT NULL)
- `evidence_document_id` → `payroll_compliance_documents` — **Δ**
- `status` (DRAFT / ACTIVE / SUPERSEDED)
- `created_by_id`, `created_at`, `approved_by_id`, `approved_at`

**Why Δ:** plan §6 had `source_document_id` → `SourceArtifact`. But SourceArtifact is the *platform's* legal-source register, while an employer's premium determination is *tenant evidence*. NL already uses `payroll_compliance_documents` for the same purpose (`digipoort_test_evidence_id`).

**Index**
- `uq_mx_riskprem_reg_period_active` on (`registration_id`, `period_from`) WHERE `status = 'ACTIVE'`

The rules are in §6.

### 3.5 `payroll_mx_isn_registrations` (panel E)

**Columns**
- `id`, `organization_id`, `employer_profile_id`
- `state_code`, `local_account_number`, `jurisdiction_pack_id`, `return_frequency`
- `effective_from` (NOT NULL), `effective_to`
- `status` (PENDING_PACK / ACTIVE / CLOSED)

**Indexes**
- `uq_mx_isn_profile_state_open` on (`employer_profile_id`, `state_code`) WHERE `effective_to IS NULL`
- `uq_mx_isn_profile_state_from` on (`employer_profile_id`, `state_code`, `effective_from`)

The rules are in §8.

### 3.6 `payroll_mx_labor_policies` (panels F and G)

**Columns**
- `id`, `organization_id`, `employer_profile_id` — **Δ**; policies belong to a legal employer, not the tenant
- `collective_agreement_id` (nullable FK)
- `version`, `effective_from` (NOT NULL), `effective_to`
- `ordinary_weekly_hours`, `weekly_schedule` (JSON)
- `aguinaldo_days`, `vacation_policy` (JSON), `vacation_premium_pct`
- `sunday_premium_pct` — **Δ**; the spec names it (§17) and a floor key exists (`mx_sunday_premium_min_pct`)
- `savings_fund`, `food_vouchers`, `other_benefits` (JSON)
- `time_record_dependency` — **Δ**, panel F "electronic time-record dependency"; a flag plus an interface version, no integration
- `floor_check_status`, `floor_check_detail` (JSON)
- `status` (DRAFT / ACTIVE / SUPERSEDED)

**Indexes**
- `uq_mx_laborpol_profile_open` on (`employer_profile_id`) WHERE `effective_to IS NULL AND status = 'ACTIVE'`
- `uq_mx_laborpol_profile_from` on (`employer_profile_id`, `effective_from`, `version`)

The rules are in §9.

### 3.7 `payroll_mx_credential_refs` — **new, Δ** (§4)

**Columns**
- `id`, `organization_id`, `employer_profile_id`
- `imss_registration_id` (nullable; set for IDSE and SUA)
- `kind` (CSD / PAC / IDSE / SUA / BANK)
- `secret_ref`
- `certificate_serial`, `fingerprint_sha256`, `subject_summary`, `valid_from`, `valid_to`
- `status` (ACTIVE / ROTATED / REVOKED), `rotated_from_id`

**Index**
- `uq_mx_cred_owner_kind_active` on (`employer_profile_id`, `kind`, `coalesce(imss_registration_id, 0)`) WHERE `status = 'ACTIVE'`
- If expression indexes are awkward on both dialects, the service enforces "one ACTIVE per (profile, kind, registration)" instead. I'll check this the same way the HK/SG partial indexes were checked.

### 3.8 Index style

All partial indexes use `postgresql_where=text(...)` and `sqlite_where=text(...)`, as `ContributionRate` does (models.py L2637–2657). `test_mexico_employer_migrations.py` checks that each one exists on SQLite and is refused on duplicate.

---

## 4. Secrets: CSD, PAC, IDSE, SUA, bank (MX-035, §20, MX-061)

### 4.1 What the repo already has (searched, not assumed)

| Mechanism | Where | What it stores |
|---|---|---|
| **Germany ELSTER certificate reference** | `GermanyElsterCertificateConfig` (models.py ~L1284–1320), `service.set_elster_certificate_config` (~L29666) | Only `certificate_reference`, a pointer into an external secret store ("key-vault path / HSM"), plus `is_configured`. Rejects an empty reference. Never accepts key bytes. |
| **NL employer PKI reference** | `PayrollNlEmployerProfile.pki_cert_ref`, `pki_cert_fingerprint`, `pki_cert_issuer`, `pki_cert_expires_at` | Reference, fingerprint and expiry only. Readiness marks an expired certificate BLOCKED (`netherlands_service` ~L680). |
| **Environment-held platform secrets** | `settings.HK_IDENTITY_TOKEN_KEY` (config.py L36); HK readiness checks that it is configured as a dedicated secret | A platform key in the environment, never in the database. |
| France DSN credentials | **Not found.** There is no DSN credential store in `app/`; France has no transport credentials yet. | — |
| Anti-precedent | `PayrollEmailSettings.custom_smtp_password` (mail/models.py L50): "plaintext today" | Must **not** be copied. |

The repo has **no secret-store client** (no Vault, KMS or Secrets Manager integration). Phase 3 therefore stores references only, exactly as ELSTER and NL do. Nothing resolves a reference until Phase 7 adds a resolver behind an interface.

### 4.2 What goes in the database

These fields only:
- `kind` and `secret_ref`
- `certificate_serial`, `fingerprint_sha256`, `subject_summary`
- `valid_from`, `valid_to`
- `status` and the rotation link

**Never stored:** private keys, key passwords, PAC passwords or API keys, IDSE passwords, or e.firma material.

### 4.3 How a reference is checked

1. **Scheme.** It must start with an allowed scheme, set in a new `settings.MX_SECRET_REF_SCHEMES` (default `vault://,aws-sm://,azure-kv://,gcp-sm://`). An unknown scheme is refused. That stops a raw secret pasted into the field from being stored as a "reference".
2. **Shape.** It must be at most 300 characters and contain no whitespace. Anything that looks like key material is refused: `-----BEGIN`, `PRIVATE KEY`, a long base64 run, or PKCS#8/PKCS#12 magic bytes once decoded. The refusal is audited **without** echoing the value.
3. **Echo.** The UI shows only the scheme and a masked tail (e.g. `vault://…/csd-2026`). The API never returns the full reference to a payroll operator; only the org admin who set it sees it once, in the write response.

### 4.4 CSD certificate (public part only)

- The org admin may upload the **public `.cer`** (an X.509 certificate is public, not secret).
- The server parses it with `cryptography`, which is already in requirements.txt (49.0.0) but not imported by `app/` yet. From it the server derives `certificate_serial`, `fingerprint_sha256`, `valid_from`/`valid_to` and `subject_summary`. The `.cer` bytes are then **discarded**, not stored.
- A file containing a private key, or a PKCS#12 container, is refused.
- **CSD-subject RFC ↔ profile RFC match.** This is done **only** once the exact subject attribute that carries the RFC is confirmed in a saved SAT source (S4).
- Until then the subject is shown, and the match item reads "not checked — source pending". It is not inferred.

### 4.5 Expiry, rotation and logging

- **Readiness by expiry.** An expired credential is BLOCKED. A credential expiring within `settings.MX_CREDENTIAL_EXPIRY_WARNING_DAYS` is a WARNING. That is a product setting, not statutory content; the default 30 is open to change in §18.
- **Rotation.** Rotating adds a new ACTIVE row and marks the old one ROTATED, so history is kept.
- **Logging and audit.** Audit values record `{"kind", "fingerprint", "validTo"}` and never `secret_ref`. RFCs and Registro Patronal numbers in audit values are masked to the last 4 (MX-061). A test greps the audit rows and the captured log for the raw values.

---

## 5. RFC and Registro Patronal validation

| Identifier | Phase 3 check | Source of the rule | Not checked in Phase 3 |
|---|---|---|---|
| RFC, legal entity (moral) | `^[A-ZÑ&]{3}[0-9]{6}[A-Z0-9]{3}$`; the 6 digits must be a real YYMMDD date; upper-cased and trimmed, never otherwise rewritten | Existing `JURISDICTION_TAX_SCHEMAS["MX"]` (core/jurisdiction.py L605–611) | SAT check digit; SAT registry/name match → Phase 7 stamp test (panel A "hard validation" stays BLOCKED until then) |
| RFC, individual employer (física) | Same with 4 letters (13 characters, as plan §7 already states for employees); requires `taxpayer_type=FISICA` | Plan v1.1 §7; **§18 Q2** | Same |
| Registro Patronal | `^[A-Z0-9]{11}$` | Existing `JURISDICTION_TAX_SCHEMAS["MX"]` | Check digit, and any meaning of its sub-fields (subdelegation etc.) — **not** derived from the number |
| `fiscal_regime_code`, postal codes | Must exist in the **Active** CFDI catalog release (`c_RegimenFiscal`, `c_CodigoPostal`) from Phase 2 | S28 catalog workbook | No Active release exists until Phase 7 → the item is **BLOCKED: catalog not active**. A free-text value is still saved so onboarding can proceed. |

**Rules**
- A mismatch is refused with a field-level message. Nothing is auto-corrected.
- The check-digit algorithms for RFC and Registro Patronal are in no saved source. I will not implement them from memory. If you want them, save the source and they become one more check.

---

## 6. IMSS registrations and risk premiums

**Registrations**
- Any number per employer (MX-002).
- Each has its own class, fraction, subdelegation, effective window and premium history (MX-024: the premium is **registration-scoped**, never company-wide).
- Establishments point at a registration. Phase 4 employees will point at a registration too.

**Premium periods (March → February)**
- Per your instruction, a premium period runs from 1 March to the end of February of the following year. MX-026 supports this: determined in February, effective for the following premium period.
- **Source:** the spec register's S14 ("IMSS — work-risk premium") has **not been saved** yet (`docs/mexico/sources/` holds only S22).
- So the period shape is a value-free content rule in `mexico_content.py`: `MX_RISK_PREMIUM_PERIOD = None`, transcribed with its S14 citation.
- **While it is None**, premium rows can be saved as DRAFT but **cannot be approved**. Readiness says "premium period rule awaiting S14 transcription". §18 Q3 asks whether you want this, or the March–February shape coded now from your instruction.

Once the rule is transcribed:
- `period_from` must be its start date and `period_to` its end date; leap years are handled by date arithmetic, not a fixed day.
- `determination_year` must be the year before `period_from`.

**The premium rate**
- It is employer-specific data from the IMSS determination, not platform content, so the tenant types it.
- It must fall inside the legal minimum/maximum range, which is two new value-free keys, `mx_risk_premium_min_pct` and `mx_risk_premium_max_pct`, transcribed from S10/S14.
- **While those keys are empty, approval is refused** — fail-closed.
- Approval needs an attached determination document and an org admin who did not create the row (four-eyes inside the tenant). If the org has only one admin, it waits; §18 Q4.

**Coverage**
- For any date asked, each ACTIVE registration must have exactly one ACTIVE premium covering that date.
- A gap makes the registration BLOCKED in readiness.
- A new registration with no determination yet is also a gap. The premium that applies before the first determination is statutory content not yet transcribed, so it is not guessed.

## 7. INFONAVIT (panel D)

- Per IMSS registration: `infonavit_operating_model` (SUA / SIPARE) and a reference to the payment account.
- "Must reconcile to IMSS registration architecture" is satisfied structurally: INFONAVIT configuration cannot exist without a registration.
- The reconciliation itself is Phase 8. Readiness shows "configured" (G3 input) and "reconciled: Phase 8" (BLOCKED).

## 8. State ISN registrations (panel E)

- **Only in-scope states can register.** That is `state_code ∈ MX_ISN_STATES_IN_SCOPE`, which is `("CDMX",)`. Every other state is refused with the MX-045 message, and the refusal is audited.
- `jurisdiction_pack_id` is resolved by the server: the state's `MX-ISN-<STATE>-2026` pack, never chosen by the client.
- **While that pack is not Active**, the registration is saved as **PENDING_PACK** and readiness for that state is BLOCKED ("CDMX ISN content not activated"). It becomes ACTIVE only when the pack is Active.
- `return_frequency` and the due date come from the state's content (filing rule). That content is empty today, so the field shows "awaiting content" and is not validated against a guessed list.
- **States without a registration.** For every state where the employer has an active establishment:
  - in scope but no registration → **BLOCKED** ("register for ISN");
  - not in scope → **BLOCKED** ("state not supported — payroll for this state is blocked", MX-045).

  Phase 4 extends this from establishments to employee work states.

## 9. Labour policy and statutory floors (panels F and G, MX-051)

**Floor checks (Phase 1 content)**

| Policy field | Floor | Content |
|---|---|---|
| `aguinaldo_days` | ≥ `mx_aguinaldo_min_days` | Scalar key (S26/S20) |
| `vacation_premium_pct` | ≥ `mx_vacation_premium_min_pct` | Scalar key |
| `sunday_premium_pct` | ≥ `mx_sunday_premium_min_pct` | Scalar key |
| `vacation_policy` days per service-year band | ≥ `MX_VACATION_DAYS` band for each service year | Slab rule `MX_VACATION_DAYS` |
| `ordinary_weekly_hours` | ≤ `MX_WORKWEEK.ordinary_weekly_max_hours` | Slab rule `MX_WORKWEEK` (MX-048) |
| Daily limits | **Not checked.** No content key exists; LFT daily limits vary by shift type. Shown as "not checked — no content". Phase 5 `labor.py`, or a new key from S26 if you want it now (§18 Q7). | — |

**Where the floors are read from.** I recommend the **Active national pack** (`MX-PAYROLL-2026` via the resolver), the same governed rows the engine will use, rather than the `mexico_content` module constants.
- With no Active pack, every floor is BLOCKED ("statutory content not active").
- Today the content is also empty. Either way the result is fail-closed.
- §18 Q1.

**Dates checked**
- The floor is checked at `effective_from` **and** at every content boundary inside the policy window.
- So an open-ended policy is re-checked against the 2027 workweek row once that row is transcribed (MX-050: a reduction may not lower pay, but a 48-hour policy becomes non-compliant on the 2027 date).

**Result**
- `floor_check_status` is one of:
  - PASS;
  - FAIL (with the failing field, the floor and its source);
  - BLOCKED_CONTENT (a floor value is missing).
- Only PASS can be activated.
- The check re-runs on every read of readiness, so a later content activation is picked up. The stored status is the last result, for display.
- A policy can **improve** on the floor but never go below it. FAIL refuses activation; nothing is silently raised to the floor.

**Savings fund, food vouchers and other benefits** have no statutory floor in the spec. They are stored and displayed. Their ISR/SBC/ISN treatment comes from earning classifications (Phase 2 table, Phase 5 engine), not from here.

### 9.1 Reuse `CollectiveAgreement`? — partly

**Reuse it for the agreement itself.** `payroll_collective_agreements` is already generic:
- It has a `jurisdiction_country` column and a governed Draft → In Review → Approved → Active lifecycle with four-eyes.
- Org-level assignment works through `organization_id`.
- NL links to it from its employer profile (`collective_agreement_id`).
- `service.upsert_collective_agreement` has no country allow-list except the CH carve-out, so MX rows need no shared-code change.
- `payroll_mx_labor_policies.collective_agreement_id` is a nullable FK to it. The UI lists `list_collective_agreements(db, "MX", org_id)`.
- No MX agreement is seeded. "No CCT" is explicit (NULL), never a default.

**Do not store the labour policy in it.**
- Its `modules` list (`wage_scales`, `overtime`, `vacation_enhancement`, …) is a set of switches with no fields for aguinaldo days, vacation premium %, weekly schedule or benefit floors.
- Its lifecycle is a Super Admin content lifecycle, while an employer's labour policy is tenant data.
- Spec §1 also defers CCT-specific benefits beyond configured contract packs, so in Phase 3 a linked agreement is **informational**: it has no payroll effect and no floor relaxation.

## 10. Employer readiness (panel H) and G1–G8

Readiness is computed on read by `mexico_service.employer_readiness(db, org_id, on)`. It is **per legal employer** (each RFC chain), with sub-rows per IMSS registration and per state. Each item carries a status (PASS / WARNING / BLOCKED / NOT_STARTED), a reason, and the gate it feeds.

| Panel / item | Phase 3 can reach | Feeds |
|---|---|---|
| A: RFC format, legal name, regime + postal code in Active CFDI catalog | PASS on format; catalog items BLOCKED until Phase 7 | G1 |
| B: CSD reference + certificate parsed + not expired; PAC provider/environment/reference; withholding obligation | PASS / WARNING (expiry) | G1, G7 |
| B: stamp test | **BLOCKED (Phase 7)** | G1, G6 |
| C: ≥1 ACTIVE IMSS registration; premium covers date; class/fraction set | PASS once premium rules are transcribed | G2 |
| C: IDSE/SUA credential references | PASS / WARNING | G6, G7 |
| C: SUA reconciliation | **BLOCKED (Phase 8)** | G2 |
| D: INFONAVIT model per registration | PASS | G3 |
| E: ISN registration per establishment state with Active pack | BLOCKED until a state pack is Active | G4 |
| F/G: labour policy floor PASS | BLOCKED_CONTENT until content is Active | G5 |
| Bank payroll workflow | **BLOCKED (Phase 10)** | G6 |
| Parallel payroll | **BLOCKED (Phase 10)** | G8 |

**How readiness relates to G1–G8**
- G1–G8 are **platform** gates signed on evidence (Phase 10). Employer readiness **never signs a gate**.
- An employer is eligible for LIVE (MX-034) only when **all** of its items PASS **and** every gate is SIGNED (`gate_states`, unchanged).
- The readiness response returns both: `{"employers": [...], "gates": gate_states(db)}`, the same shape as NL's `/readiness`.
- In Phase 3, "LIVE-eligible" is unreachable by construction. The stamp test, reconciliations, bank workflow and parallel payroll are all BLOCKED, and a test pins that.
- The Super Admin Readiness tab shows, per gate, how many employers have that gate's items passing. That is the input Phase 10's gate evidence will cite.

---

## 11. Endpoints

**Org (`/api/payroll/mexico`, `mexico_org_router.py`)**

Reads (payroll operator). Writes (org admin) are marked †.
- `GET` / `POST`† `/employers` — list, or create a profile chain
- `POST`† `/employers/{id}/versions`
- `GET` / `POST`† `/employers/{id}/establishments`; `PUT`† `/establishments/{id}/deactivate`
- `GET` / `POST`† `/employers/{id}/imss-registrations`; `PUT`† `/imss-registrations/{id}/close`
- `GET` / `POST`† `/imss-registrations/{id}/risk-premiums`; `PUT`† `/risk-premiums/{id}/approve`
- `GET` / `POST`† `/employers/{id}/isn-registrations`; `PUT`† `/isn-registrations/{id}/close`
- `GET` / `POST`† `/employers/{id}/labor-policies`; `PUT`† `/labor-policies/{id}/activate`
- `GET /labor-policies/{id}/floor-check?on=` (read-only)
- `GET` / `POST`† `/employers/{id}/credentials`; `POST`† `/employers/{id}/credentials/csd-certificate` (public `.cer` upload); `PUT`† `/credentials/{id}/revoke`
- `GET /collective-agreements` (MX, read-only)
- `GET /readiness?on=` — `on` is required; no server-date default (the Phase 2 Q5 rule)

**Super Admin (`mexico_router.py`, read-only)**
- `GET /employers?organization_id=`
- `GET /employers/{id}`
- `GET /employer-readiness?organization_id=&on=`
- `GET /employer-readiness/summary?on=` (per-gate counts)

## 12. Files

**Backend**
- New: `mexico_org_router.py`, `alembic/versions/<rev>_mx_employer_m2.py`
- Modify:
  - `models.py` (7 tables)
  - `mexico_service.py` (employer, registration, premium, ISN, labour, credential, readiness)
  - `mexico_schemas.py` (create schemas: no defaults on statutory or identity fields; `extra="forbid"` so stray secret fields are refused)
  - `mexico_router.py` (Super Admin reads)
  - `router.py` (one `include_router` line)
  - `config.py` (`MX_SECRET_REF_SCHEMES`, `MX_CREDENTIAL_EXPIRY_WARNING_DAYS`)
  - `engine/countries/mexico_content.py` (value-free `MX_RISK_PREMIUM_PERIOD = None`; keys `mx_risk_premium_min_pct`/`max_pct`; tests updated for the new keys)
  - `.env.example` gets **no change from me**: it carries your unstaged hunk. The two settings have safe defaults, and I'll list the lines for you to add.
  - `alembic/MIGRATIONS_MANIFEST.txt`

**Frontend**
- New:
  - `modules/payroll/Compliances/MXComplianceCentreTab.jsx` and `MXReadinessPanel.jsx`
  - `components/jurisdiction/mexico/MXEmployerProfileTab.jsx` (Super Admin, read-only)
  - `components/jurisdiction/mexico/employer/` — `MXLegalEntityPanel`, `MXSatPayrollPanel`, `MXRegistrationsPanel` (IMSS + premiums + INFONAVIT), `MXIsnRegistrationsPanel`, `MXLaborPolicyPanel`, `MXCredentialRefsPanel`, `useMexicoOrgData.js`
  - These panels are shared by both the org view and the Super Admin view; read-only is a prop.
- Modify:
  - `CompliancePage.jsx` (MX tab, two lines)
  - `mexicoComplianceConfig.jsx` (Employer tab)
  - `payrollService.js` (MX org block)
  - `superAdminService.js` (MX Super Admin reads)
- **Not doing:** `pages/PolicyModule/MXPolicyPage.jsx` from plan §6. That module authors pay-structure defaults ("New Policy" packs), not the §11 labour policy. Pay structure belongs in Phase 6.
  - Phase 3 does check whether MX can be picked in the Policy country selector today. If it can, it would fall back to India's page (the HK D-5 defect). In that case I log it in OUT_OF_SCOPE_DEFECTS.md rather than change shared code.

## 13. Tests (all synthetic, scratch DB, full suite before reporting)

| File | What it proves |
|---|---|
| `test_mexico_employer_profile.py` | Versioning (new row, prior closed, no in-place edit); RFC immutable across versions; moral/física formats; date-part validity; multiple RFCs per org; per-org uniqueness; catalog items BLOCKED with no Active release |
| `test_mexico_imss_registrations.py` | Many per employer; open-row uniqueness; overlap refused; establishments must share the profile; derived min-wage zone UNRESOLVED on empty content |
| `test_mexico_risk_premiums.py` | Approval refused while the period rule or range is empty; with synthetic content: March–Feb shape (incl. a leap year), determination year, range, four-eyes, evidence required, supersede, coverage gap → BLOCKED; registration-scoped (two registrations, two premiums) |
| `test_mexico_isn_registrations.py` | CDMX accepted as PENDING_PACK; all 31 other states refused + audited; pack resolved server-side; ACTIVE only with an Active pack; establishment in an unsupported state → BLOCKED |
| `test_mexico_labor_policy.py` | Empty content → BLOCKED_CONTENT; no Active pack → BLOCKED; synthetic Active pack: each floor PASS / FAIL with an exact message; re-check across a synthetic 2027 workweek row; above-floor allowed; FAIL never auto-raised; CBA link optional and with no effect |
| `test_mexico_credential_refs.py` | Unknown scheme refused; PEM / `PRIVATE KEY` / base64 blob / PKCS#12 refused and **not echoed**; public `.cer` parsed (test cert generated in the test with `cryptography`, never committed); `.cer` bytes not persisted; expiry → BLOCKED/WARNING; rotation; audit rows and caplog contain no raw reference, RFC or Registro Patronal |
| `test_mexico_employer_readiness.py` | Item→gate mapping; LIVE-eligible unreachable in Phase 3; gates unchanged; `on` required |
| `test_mexico_org_router.py` | Tenant isolation (org B cannot read or write org A's ids → 404); operator reads, operator write → 403, admin write OK; Super Admin (no org) → 403 on org routes; Super Admin read-only routes |
| `test_mexico_employer_migrations.py` | Upgrade/downgrade guarded and idempotent; every partial index exists and rejects a duplicate on SQLite |
| Updated | `test_alembic_metadata.py` (head + count), `test_migration_idempotency.py` (`_GUARDED`), manifest, `test_mexico_scaffolding.py`/`test_mexico_content.py` (new value-free keys) |

New test files import `app.*` lazily inside the tests, per the collection-order hazard.

## 14. Browser checks (real Chrome, inspected screenshots → `docs/mexico/phase3-evidence/`)

**Harness:** Phase 2's (`vite build` + `vite preview`, uvicorn on a scratch SQLite database that `setup_db.py` asserts). It adds:
- an MX org (country set by the fixture);
- an org admin and a payroll operator;
- a second MX org for isolation;
- an NL org and an HK org for regression.

**Checks**
1. Org admin sees **Mexico Compliance Centre → Employer & Registrations**, with panels A–H.
2. Create an employer; a bad RFC is refused field-level, a good RFC is accepted; a new version leaves the old one closed.
3. Two IMSS registrations; a premium cannot be approved (content pending) and shows the exact reason.
4. CDMX ISN registration shows PENDING_PACK; picking another state is refused with the MX-045 text.
5. Labour policy shows BLOCKED_CONTENT with the reason; it cannot be activated.
6. Credentials: a PEM pasted into the reference field is refused and not shown back; a `vault://` reference is accepted and shown masked; a `.cer` upload shows serial, fingerprint and expiry.
7. Readiness panel H shows every BLOCKED item with its gate, and **no LIVE**.
8. A payroll operator sees everything read-only (no write buttons; a direct API write gets 403).
9. Org B cannot see org A's employer (UI empty, API 404).
10. Super Admin Employer tab: org picker → read-only panels + readiness; no write controls.
11. Regression: the NL org's Compliances tab list is exactly as before (screenshot compared with Phase 2's `24_regression_nl.png`); the HK org has no MX tab; the Super Admin NL workspace is unchanged.
12. No 4xx/5xx except the refusals the script expects (asserted, as in `approve_check.py`).

## 15. Proof that other jurisdictions are unaffected

- **Shared files touched:** `CompliancePage.jsx` (two additive lines, MX-only), `router.py` (one `include_router`), `models.py`/migration (new tables only), `config.py` (two new settings), `payrollService.js`/`superAdminService.js` (new exports only). There are **no** changes to `service.py` and none to `CollectiveAgreement` or its service.
- `git diff 651948a -- <shared files>` goes in the report, showing additive MX-only hunks.
- Full backend suite: the only acceptable failure is OOS-4 (`test_hong_kong_configuration`).
- `platform_shared_helper_snapshots.json` must **not** need re-recording. If it does, I stop and explain before touching it.
- `npm run check:undefined`, lint count unchanged from 184, `vite build`.
- Browser regression item 11.

## 16. Test and harness credentials — confirmation

I checked the committed Phase 2 harness and tests:
- `BrowserCheck!2026` and `sa-a@`/`sa-b@mxbrowsercheck.io` appear **only** in `docs/mexico/phase2-evidence/harness/{setup_db,acceptance,approve_check}.py`.
- They exist only in the throwaway SQLite database those scripts create. `setup_db.py` asserts the URL is `sqlite:///` **and** inside the scratchpad, and refuses anything else.
- They were never created in the shared Postgres database or in production, never put in any `.env`, and belong to no real person. They are throwaway values.
- The MX test files contain no credentials (grep for `password|SECRET_KEY|api_key`: no hits). All Mexico content and source rows in tests are synthetic.
- **One caveat:** `mxbrowsercheck.io` is not a reserved domain. Earlier, `.test` was rejected by the email validator. Nothing sends mail to it (login only), but for Phase 3 I will try `@example.com` (reserved under RFC 2606) first, and keep the `.io` name only if the validator refuses it.
- Phase 3 adds no real secrets anywhere:
  - Test `.cer` files are generated at test time and not committed.
  - Secret references in tests are fake `vault://test/...` strings.
  - Org admin passwords in the harness follow the same throwaway, scratch-database-only rule.

## 17. Order of work

1. Migration + models + index tests.
2. Service: profile, registrations, premiums, ISN, labour, credentials, readiness, with the unit tests for each.
3. Org router + Super Admin reads + router tests.
4. Frontend panels, org tab, Super Admin tab.
5. Full suite, lint, build, browser run, report `MEXICO_PHASE_3_IMPLEMENTATION_REPORT.md`, stage, stop.

## 18. Decisions needed before I build

| # | Question | My recommendation |
|---|---|---|
| Q1 | Floors read from the **Active national pack** (governed, what the engine will use) or from the `mexico_content` constants? | Active pack. Both are empty today, so both fail closed; only the pack respects activation. |
| Q2 | Accept individual-employer RFCs (13 characters, `taxpayer_type=FISICA`) as well as legal entities (12)? | Yes. Sole traders employ staff, and the 12-character-only pattern would turn them away. |
| Q3 | Risk-premium period: keep it as a value-free content rule until S14 is saved and transcribed (approval refused until then), or code March → February now from your instruction? | Content rule from S14 ("source wins"). Please save S14 (and the S10 article giving the premium range) in Batch B. |
| Q4 | Premium approval needs a second org admin (four-eyes in the tenant). With a single admin it waits. OK, or allow the same admin with a recorded reason? | Four-eyes, no exception. A wrong premium is costly. |
| Q5 | Super Admin Employer tab read-only (no Super Admin writes of tenant facts, unlike NL)? | Read-only. |
| Q6 | Keep the generic "Tax Configuration" base tab for MX orgs (NL hides it)? | Hide it for MX, as NL does. Its US fallback shows nothing true for Mexico. MX-only change. |
| Q7 | Add a value-free daily-hours key now (from S26), or leave daily limits to Phase 5? | Leave to Phase 5; show "not checked" in Phase 3. |
| Q8 | `MX_CREDENTIAL_EXPIRY_WARNING_DAYS` default (product setting, not statutory) | 30 days. |
| Q9 | Which secret store does production use, so the scheme allow-list matches? | Tell me the scheme. Until then, the four defaults in §4.3, and nothing resolves a reference before Phase 7. |

---

## 19. Approval (2026-10-16) — answers and corrections

**Answers**
- **Q1:** Active pack.
- **Q2:** yes — 13-character física RFCs with `taxpayer_type=FISICA`.
- **Q3:** content rule, source wins.
  - The premium min/max range should be in LSS Art. 74 (S10, Batch A); confirm it from the text once S10 is saved.
  - If the 1 March → end-of-February validity is not in S10 or S14, it is expected in the RACERF (Reglamento de la LSS en materia de Afiliación, Clasificación de Empresas, Recaudación y Fiscalización), added as **S29** to the addendum with a fetch checklist.
  - The March–February shape itself comes from spec **MX-026** ("normally filed in February and effective for the subsequent IMSS premium period"); the exact dates are transcribed from the source, never coded from the spec text.
- **Q4:** four-eyes, no exception. Readiness says "waiting for a second org admin" while the org has only one.
- **Q5:** read-only.
- **Q6:** hide Tax Configuration for MX orgs only.
- **Q7:** Phase 5.
- **Q8:** 30 days, as a setting.
- **Q9:** production is GCP (`GCP_DEPLOYMENT.md`: application secrets live in a VM `.env` today; Secret Manager is the target). `MX_SECRET_REF_SCHEMES` allows **only `gcp-sm://`**; the vault/aws/azure schemes in §4.3 are dropped. Per-employer CSD/PAC credentials need Secret Manager live before Phase 7. That is an infrastructure lead-time item, recorded in the Phase 3 report.

**Corrections**
1. The readiness → gate mapping cites the spec §22 definition for every gate an item feeds. An item with no clear gate is marked **unmapped**, never guessed.
2. `.cer` upload:
   - size cap 16 KB;
   - DER or PEM only, and anything else is rejected **before** parsing;
   - processed in memory only and never written to disk, not even as a temp file. This means a raw request body read with a hard cap, not a multipart `UploadFile`, because Starlette spools that to a temp file.
   - Tests cover each of these.
3. The org readiness UI passes the user's local date explicitly as `on`, shown in a date bar with a picker. The API still requires `on`.
4. The report carries a dependency table: which Phase 3 items stay BLOCKED or UNRESOLVED until which source or phase.

Harness users use `@example.com`.
