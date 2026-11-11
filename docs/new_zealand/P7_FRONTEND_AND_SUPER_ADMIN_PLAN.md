# New Zealand P7: frontend, and the Super Admin signing console: detailed plan

**Status:** plan only, for review. Nothing is built until Venu says "go ahead" for a sub-phase.
**Builds on:** P0–P6 (backend complete to `cf63056`, head `c6ea8c6c35ce`). **Template:** Japan P7 (`c7249c0`).
**Spec:** ZP-NZ-ENG-001 §11 (screens), §12 (blocking states), §13 (privacy), NZ-023/024/026.

---

## 0. The decision P7 depends on: how Super Admin values reach calculation

Every NZ pack row ships labelled `[PENDING G1]`. Several authority tables are empty, and the engine blocks on both. Venu asked whether the values a Super Admin configures should drive processing. There are three options.

| Option | What it means | Verdict |
|---|---|---|
| **1. Governed signing console** (recommended) | A Super Admin edits or fills a row with a source document and a reason, and marks it specialist-verified. That **clears its `[PENDING G1]` marker**. A *different* Super Admin approves the pack version (existing maker-checker, fed by `statutory_editors`), then activates it. `nz_pack_activation_refusal` still refuses while any row is pending or any authority table is empty. | Values configured by Super Admin drive processing, with evidence and four-eyes. This is the Hong Kong pattern (`hong_kong_service.update_row`), already proven in production. |
| 2. Drop the PENDING guard | Whatever is seeded or typed is used immediately. | Breaks the spec's production safety rule ("no statutory number without signed evidence"). **Not recommended.** |
| 3. Option 1 + test-org bypass | As option 1, plus unsigned values allowed only for organisations flagged non-production (NZ-026 canary). | Useful for UAT before G1 closes. Adds a flag that must never reach a production org. Can be added later on top of option 1. |

**Recommendation:** build **Option 1 inside P7**, as sub-phase P7a. The console is what makes the Super Admin's values the ones the engine uses, so building the screens without it would leave NZ unusable until P9. Option 3 can be decided separately at P9 (canary).

---

## 1. Sub-phases (each its own go-ahead and local commit)

| Sub-phase | Scope | Size |
|---|---|---|
| **P7a** | Backend: governed NZ row editor + authority-table row add/remove + `statutory_editors` hook + 6 Super Admin routes + tests | small–medium |
| **P7b** | Super Admin page `/super-admin/compliance/new-zealand` (read views + signing console) | medium |
| **P7c** | Organisation Compliance Centre tab + employee statutory panel (P4–P6 records) | large |
| **P7d** | Run detail (payslip breakdown, preflight, special runs, corrections), NZ leave types in the leave screens, UI validation script | medium |

---

## 2. P7a: backend for the signing console (no migration)

### 2.1 `payroll/new_zealand_service.py` (or a new `nz_super_admin.py`)

```python
def nz_update_row(db, kind, row_id, data, actor_id) -> dict
    # kind: "rate" (ContributionRate) | "slab" (TaxSlab); canonical NZ rows only (organization_id IS NULL)
    # pack must be editable (service._require_editable_pack: Draft family)
    # required: reason, sourceDocumentId (existing SourceArtifact)
    # editable fields: rate -> flatAmount, textValue, effectiveFrom/To ; slab -> min/max, ratePct, flatAmount,
    #                  taxFormula, filingStatus, jurisdictionState, rateLabel(name), effectiveFrom/To,
    #                  treatment (NZ_EARNING_CLASS only: INCLUDED|EXCLUDED|LUMP_SUM_PATH|REVIEW)
    # specialistVerified=True -> needs a stored, hashed source reviewed by a different Super Admin
    #                            (HK rule) -> strips "[PENDING G1]" from label/rate_label = SIGNED
    # text rows validated against the engine vocabulary (e.g. rounding rules in pack.ROUNDING_RULES,
    #   nz_lump_sum_paye_method in {EXTRA_PAY_FOUR_WEEK_ANNUALISE}, ...) - never free text the engine can't read
    # service._invalidate_pack_approval_on_edit(pack); audit entity "nz_statutory_rate|slab" (old/new/reason/source)
def nz_add_table_row(db, pack_row_id, rule_type, data, actor_id) -> dict
    # only rule types in content.NZ_EMPTY_TABLES (+ NZ_PUBLIC_HOLIDAY): PAYE method, secondary/ND rates, IETC,
    #   CS variation codes, lump-sum method, holiday-advance method, IRD examples, public holidays, ACC classes
    # per-rule-type field whitelist + validation (e.g. public holiday: date, name, region in NZ_REGIONS or national)
    # created signed only with specialistVerified + source, else "[PENDING G1]"
def nz_delete_table_row(db, row_id, actor_id, reason)      # Draft packs only; audited
def statutory_editors(db, pack) -> set                     # actors of nz_statutory_* audits for this pack (HK pattern)
def nz_signing_status(db, pack_row_id) -> dict             # pending rows by group, empty tables, activation refusal text
```

`JURISDICTION_HOOKS["statutory_editors"]` changes from `set()` to the function above. This is what stops an editor approving their own pack.

### 2.2 Super Admin routes (`super_admin/router.py`, `get_current_super_admin`)
| Method / path | Purpose |
|---|---|
| GET `/compliance/new-zealand/packs/{id}/signing-status` | pending / empty / refusal |
| PUT `/compliance/new-zealand/configuration/rows/{kind}/{row_id}` | governed edit / sign |
| POST `/compliance/new-zealand/packs/{id}/tables/{rule_type}/rows` | add an authority-table row |
| DELETE `/compliance/new-zealand/configuration/slabs/{row_id}` | remove a Draft-added row |
| GET `/compliance/new-zealand/decisions` | owner decisions D-1..D-7 (from `owner_decisions`) |
| (existing) generic statutory-summary, pack approve / status / new-version | reused, not rewritten |

### 2.3 Tests: `tests/test_nz_super_admin.py`
- An edit needs a reason and a source.
- Signing needs a source verified by another Super Admin.
- Signing removes the marker.
- An Active pack is refused.
- An unknown field is refused.
- The vocabulary is enforced.
- The editor cannot approve the pack (maker-checker).
- Activation is refused until every row is signed and every table filled, then allowed.
- After activation, `calc_inputs` and the engine **calculate with the Super Admin's values** (the end-to-end proof of Option 1).
- Route registry regenerated in a no-.env worktree.

---

## 3. P7b: Super Admin page (frontend)

```
frontend/src/
├── App.jsx                                            (EDIT) /super-admin/compliance/new-zealand[/:state]
├── pages/JurisdictionCompliance/NZCompliancePage.jsx  (NEW)  JurisdictionLayout country="NZ"
├── pages/JurisdictionCompliance/index.js              (EDIT) export + NZ: "new-zealand"
├── config/jurisdictions/newZealandComplianceConfig.jsx (NEW) groups + extra tabs (keys = new_zealand_content.py)
├── components/jurisdiction/new-zealand/
│   ├── NZOverviewDashboard.jsx   pack status, pending count by group, empty tables + gates, D-1..D-7, refusal text
│   ├── NZPackRowsTab.jsx         read view of one group; "Edit / sign" per row when the pack is editable
│   ├── NZRowEditor.jsx           modal: value, effective dates, source picker, reason, "specialist verified"
│   ├── NZAuthorityTableEditor.jsx add/remove rows of an empty table (per-rule-type form; public holidays form)
│   ├── NZSigningStatusTab.jsx    what still blocks activation, with links to each row
│   ├── nzFormat.js / nzShared.jsx
├── components/jurisdiction/CountryFlag.jsx           (EDIT) NZ
├── service/superAdminService.js                      (EDIT) getNzStatutorySummary, updateNzRow, addNzTableRow, ...
└── utils/jurisdictionLabels.js                       (EDIT) NZ: "PAYE (incl. ACC earner levy)", "IRD number / NZBN"
```

**Tabs:**
- Overview
- PAYE & ACC
- KiwiSaver & ESCT
- Student loan & child support
- Minimum wage
- Holidays Act: entitlements (P5 keys) plus leave pay (P6 keys)
- Payday filing & remittance: read-only until P8
- Scope, rounding & policy: incl. correction policy, deduction precedence
- Earning classification: `EarningClassMatrix`, obligations PAYE/ACC/KIWISAVER/STUDENT_LOAN/HOLIDAY_GROSS/MIN_WAGE, 9 components
- Authority tables: each empty table with its gate, plus the add-row editor
- Signing status
- Sources: `SourceEvidencePanel`

An empty table always reads *"Empty, signed at Gx; every calculation that needs it is blocked"*. A value is never shown as if it were in force while it is pending.

---

## 4. P7c: organisation Compliance Centre and employee panel

### 4.1 Compliance Centre tab (`modules/payroll/Compliances/`)
`CompliancePage.jsx` (EDIT) gets `isNewZealand`, tab "New Zealand Compliance Centre", rendering `NZComplianceCentreTab.jsx` (NEW):

| Section | Backend (already built) |
|---|---|
| Setup status: blockers, readiness | GET `/new-zealand/summary`, `/readiness` |
| Employer profiles: versions, approve (four-eyes), verify, employer IRD (masked, reveal flow) | `/employer-profiles*`, `/ird-numbers*` |
| Leave administration: vest entitlements (as-of date), propose public holidays (year) | POST `/leave/vest`, `/public-holidays/propose` |
| Family-violence permission: holders, grant (another admin, reason), revoke | `/permissions/family-violence*` |
| Special runs: out-of-cycle / lump sum / holiday advance / final (options form) | POST `/runs/special` |
| Corrections: create from a paid payslip, approve, apply, void | `/payslips/{id}/corrections`, `/corrections/*` |
| Employee picker → the employee panel below | |

### 4.2 Employee panel: `NewZealandStatutoryProfilePanel.jsx` (NEW), shown in `EmployeeDetailPanel.jsx` when `countryCode === "NZ"`
One config-driven `NZRecordSection.jsx` (the `JPRecordSection` pattern) gives every versioned record the same flow: DRAFT → second person approves. Sections:
- **Records:** tax profile (code, source, STC and student-loan certificates, min-wage category plus evidence), KiwiSaver, work pattern (weekday hours / roster), authority notices (file upload; hash only; approve / revoke), opening balances.
- **IRD number:** `NZIrdNumberField.jsx`, masked always. Reveal is a request, then approval by another person, then a single-use reveal. Digits live only in component state for 60 s and are wiped on unmount. Input is a password field, cleared before the request. This mirrors `JPMyNumberField`.
- **Employment:** employments (create / approve / end, continuity evidence, pay-as-you-go basis), rehire.
- **Leave:**
  - entitlements, showing the legal balances (weeks / days) separately from a "Planning view, not the legal entitlement";
  - leave events, with restricted ones shown only with the permission;
  - public-holiday decisions (otherwise-working-day decision with evidence, worked shift, approve);
  - leave-pay calculations, showing **both candidates, the winner and the statutory reason**, with "Calculate" buttons;
  - cash-up (written request reference, approve);
  - final pay case (open / calculate / approve / cancel, with every entitlement resolved);
  - gross-earnings ledger (read-only).

---

## 5. P7d: runs, leave screens, validation

| File | Change |
|---|---|
| `PayRollRuns/NZPayslipBreakdown.jsx` (NEW) | From `nzCalculationSnapshot`: payment kind, tax code, separate bases per obligation, PAYE regular / extra, ACC (liable, cap, YTD, cap crossed), student loan (standard / extra / extra pay), KiwiSaver (employee, employer gross → ESCT → net, destination), child support (protected net, shortfall, variation code), minimum wage status, leave-pay lines (restricted ones masked), final-pay lines, exceptions, hashes |
| `PayRollRuns/NZRunPreflightPanel.jsx` (NEW) | GET `/runs/{id}/preflight` and `/fingerprint` |
| `PayRollRuns/RunDetailPanel.jsx` (EDIT) | Render the two panels for NZ items (the JP pattern) |
| `Attendance/AttendancePage.jsx`, `LeaveRequestsTab.jsx`, `LeaveBalancesTab.jsx` (EDIT) | For NZ employees: the NZ leave types (`annual`, `sick`, `nz_bereavement_close`, `nz_bereavement_other`, `nz_family_violence`, `nz_alternative`, `unpaid`). **The reason box is hidden for family violence**, and `restricted` is shown as "Restricted leave". Other countries are unchanged. |
| `service/payrollService.js` (EDIT) | Every NZ client call (65 org routes, P4–P6) plus the P7a Super Admin routes |
| `scripts/nz-compliance-ui-validation.mjs` (NEW, added to `npm test`) | Checks below |

**What `nz-compliance-ui-validation.mjs` checks:**
- every NZ client path matches a route in `nz_org_router.py`;
- the IRD digits appear only in the reveal state;
- no family-violence reason field;
- no JP / ZA fields;
- the components mount.

---

## 6. Rules carried into every screen
- Fail-closed copy: a block shows its code and reason (e.g. `NZ_TABLE_EMPTY:public_holidays`), and is never hidden behind a generic error.
- Reasons are required on every write (NZ-024). Approvals show "needs a second person".
- No IRD digits outside the single-use reveal. No family-violence detail without the permission. Holiday/leave screens label the planning view.
- NZ stays dormant (`NZ_TENANT_ONBOARDING_ENABLED=False`): the org screens are reachable only for an NZ org with the flag on. The Super Admin page is always visible (content work happens before go-live).

## 7. Verification (targeted, per the agreed policy)
- **Backend:** `test_nz_*`, new `test_nz_super_admin.py`, the route registry and privacy suites, the Hong Kong configuration suites (the shared editor helpers), migration pins.
- **Frontend:** `npm run build`, `npm run check:undefined` (the 9fc1a36 lesson), and `npm test` (incl. the new validation script).
- Manual smoke test in the dev server with the throwaway Super Admin account, **after asking**. No DB scripts against any remote database.

## 8. Decisions: recorded 2026-11-04 (Venu)
- **Super Admin values: Option 1** (governed signing console; maker-checker; activation refused until signed).
- **Console built inside P7** (P7a + P7b).
- **NZ leave types in the existing leave screens, NZ employees only.**
- **Order P7a → P7b → P7c → P7d**, a go-ahead and a local commit per sub-phase.

### Original questions
1. **Super Admin values: Option 1** (recommended), 2, or 3.
2. **Build the signing console inside P7** (P7a + P7b), yes or no. Recommended: yes.
3. Whether the leave screens should show NZ leave types to NZ employees only (recommended), or an NZ-specific leave form.
4. Sub-phase order: P7a → P7b → P7c → P7d (recommended), with a go-ahead per sub-phase.
