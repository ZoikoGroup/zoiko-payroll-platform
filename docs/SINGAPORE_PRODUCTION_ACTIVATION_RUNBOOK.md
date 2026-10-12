# Singapore — Production Activation Runbook

**Audience:** the deploy owner and the platform Super Admins (at least **three** distinct Super Admin accounts: A prepares, B approves, C activates).
**Status basis:** `docs/SINGAPORE_FINAL_IMPLEMENTATION_STATUS.md`, evidence dated 2026-09-29.
**Target:** Alembic head `445abd6a9083`, from the database's current revision `998877665544`.

## Rules for every step
- **NEVER USE ALEMBIC STAMP.**
- **Never** run `alembic stamp`, manual DDL, or `scripts/seed_jurisdiction_service_registry.py` against production. That script overwrites every country's registry row.
- Every step has an **expected result**. If a result differs, **stop** and go to N (Rollback) — do not improvise.
- Singapore stays **`PLANNED`** in `jurisdiction_service_registry` until step L. Nothing before step L opens Singapore onboarding. Engineering enforces this: onboarding fails closed without an `AVAILABLE` row and an Active pack.

---

## A. Pre-deployment checks (go / no-go)

| # | Check | Expected | Owner |
|---|---|---|---|
| A1 | D1 AIS submission mode recorded (export only / API / both) | A written decision. If API or both: IRAS APEX onboarding, Corppass authorisation, credentials and sandbox are in place **and** the integration is built. It is not built today. | Product owner |
| A2 | D2 hotfix policy recorded | `RESTRICTED` confirmed, or a reviewed one-line change to `SG_HOTFIX_POLICY` | Product owner |
| A3 | D3 scope of the Singapore-only controls recorded | "SG only" confirmed, or a separate change request | Product owner |
| A4 | G1–G8 evidence accepted | Each gate's signed artifact is recorded as Source Evidence with form number `SG-GATE-G<n>` (file uploaded, SHA-256 recorded) and reviewed by a **different** Super Admin. Upload the signed document first; review is refused without it, and a reviewed document can never be replaced — register a new artifact with the same form number, then supersede the old one (Singapore Readiness tab "Supersede with #n", or `PUT /api/super-admin/compliance/source-artifacts/{id}/supersede`); the old record, file and review are kept, and the gate returns to pending until the replacement is reviewed. See `docs/SINGAPORE_EXTERNAL_EVIDENCE_HANDOFF.md`. Readiness then shows the gate `PASS`. D1–D3 are recorded the same way as `SG-DECISION-D<n>`. **None exists today.** | Compliance owner / DPO / legal |
| A5 | The branch is merged into `main` with the conflicts resolved | `python -m alembic heads` → exactly `445abd6a9083 (head)`; `python -m pytest tests/ -q` → 0 failed | Engineering |
| A6 | Deploy owner has reviewed the `scripts/deploy_migrate.sh` safety fix | Approved | Deploy owner |
| A7 | Change window and rollback owner named | Recorded | Deploy owner |

**Merging to `main` triggers an automatic deploy.** Complete B–C against a restored copy **before** the merge that will deploy.

## B. Backup
1. Take a point-in-time backup / snapshot of the production database.
2. Record its identifier and the current revision:
   ```sql
   SELECT version_num FROM alembic_version;
   ```
   **Expected:** `998877665544`. If it is anything else, **stop**: the lineage has changed since the rehearsal.

## C. Restore rehearsal (mandatory)
1. Restore the B backup into a scratch instance. It must never be the production host.
2. From the merged tree, point `PAYROLL_DATABASE_URL` at the scratch instance and run:
   ```bash
   bash scripts/deploy_migrate.sh
   ```
3. **Expected output:**
   - exactly **7** `Running upgrade` lines: `998877665544 → c3d9e1f4a7b2 → d4e8f2a6b9c1 → e5f9a3b7c2d4 → f6a1b4c8d3e5 → a7c2e9f4b1d6 → b8e3d5f2a9c7 → 445abd6a9083`;
   - `No schema drift detected.`;
   - `Database is at the Alembic head.`
4. **Expected schema delta** (compare before and after):

   | Change | Objects |
   |---|---|
   | Tables added (2) | `sgp_pwm_overtime_schedules`, `sgp_ir8a_modifications` |
   | Columns added (11) | 10 × `payroll_employees.sgp_*`; `payslip_items.sgp_calculation_trace` |
   | Indexes added | 8 |
   | Removed | **nothing** |
   | Kept | the existing orphan `sgp_ir21_cases` (0 rows) — `f6a1` skips it |

5. Run the script a **second** time. **Expected:** 0 migrations, same head, no drift.
6. Carry out E (seed, twice) and F (golden vectors) on the copy. The app must start against the copy.

## D. Migration (production, in the maintenance window)
1. Put the application in maintenance mode.
2. Run `bash scripts/deploy_migrate.sh` (or let the `main` deploy run it).
3. Check the same output as C3 and C4.
4. Verify, read-only:
   ```bash
   python -m alembic current      # 445abd6a9083 (head)
   python -m scripts.check_schema_drift   # No schema drift detected.
   ```
5. If the script **refuses** — an unknown revision or drift — it has changed **nothing**. Stop and investigate. Never stamp.

## E. Seed
From `backend/`:
```bash
python -m scripts.seed_singapore_canonical_pack
python -m scripts.seed_statutory_report_templates
```
These are local-DB-guarded (`scripts/_local_db_guard.py`). For production the owner sets `ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND` deliberately, for this step only, and unsets it afterwards.

**Expected after the first run:**

| Item | Expected |
|---|---|
| Packs | `SG-PAYROLL-2026 v1.2` and `SG-PAYROLL-2027 v1.0`, both **Draft** |
| SG contribution rates | 596 |
| PWM | 6,132 rows / 84 schedules / 73 overtime-hour values / 6 source documents |
| SG templates | 11, all **Draft** |
| SG registry row | **`PLANNED`** — created only if missing; an existing row is never changed |
| Other countries' registry rows | untouched |

**Run both commands a second time. Expected:** identical counts, nothing promoted or demoted, and **no row changed**. The latest `jurisdiction_pack` audit row for each SG pack shows `rowChanges` = 0 inserted / 0 deleted for both rates and slabs. A non-zero value means the Draft pack held non-canonical values, and only those rows were replaced. Rehearsed 2026-09-29: the second run left every SG row's PostgreSQL row version (`xmin`) unchanged.

## F. Golden vectors
- Super Admin → Compliance → Singapore → **Golden Vectors** → Run.
- **Expected:** `PASS 37/37`. A FAIL, or no run, blocks activation by design.

## G. Pack approval (maker-checker)
1. Review Compliance → Singapore → **Readiness & Operations**:
   - activation gates;
   - the source + SHA-256;
   - the effective dates;
   - external dependencies;
   - pending decisions.
2. **Super Admin B** (not the last editor) clicks **Approve** on `SG-PAYROLL-2026 v1.2`.
   - **Expected:** status becomes Approved and the approver is recorded.
   - If the last editor tries, it is refused and audited.

## H. Pack activation
1. **Super Admin C** (≠ B) sets the pack **Active**, with a reason.
2. **Expected:** Active, and a `status_change` audit row carrying the reason.
3. Refusals — B activating, no golden PASS, missing evidence, overlap — are each audited once.
4. **Singapore onboarding is still closed** (registry `PLANNED`).
5. Leave `SG-PAYROLL-2027 v1.0` Draft until its own approval ahead of 1 Jan 2027.

## I. Template promotion
For each template needed at launch (all 11 are listed in Report Templates):
1. B **Approves** it (the last editor cannot).
2. A or C **Publishes** it, then sets it **Active**.

**Expected:**
- `officialCertification = No` on every template;
- generators accept only Active templates;
- a correction later means a new version: supersede the old one, then activate the new one. The new version is a faithful copy of every row, including effective dates, sources and CPF basis (fixed in the final closure). Link its source document when creating it (`sourceDocumentId`).

## J. Test tenant

**Constraint (verified in code):** Super Admin organisation creation uses the **same** onboarding gate as self-registration (`organizations/router.py` → `get_jurisdiction_onboarding_block_reason`), by design, so it cannot be used as a bypass. While Singapore is `PLANNED`, **no Singapore organisation can be created in production, not even a test one.**

**Deploy-owner choice — pick one and record it:**
- **J-1 (recommended):** run J in full on the **restored production copy** from C, after E–I have been applied there, with the copy's registry row set to `AVAILABLE`. Production then goes straight from K to L; the first production tenant is a controlled pilot.
- **J-2:** in production, perform L inside the maintenance window, create the test tenant immediately, and run J before the window ends. Self-registration is technically open during that interval; revert to `PLANNED` (N) if J fails.

No engineering bypass exists or has been added — that would be a governance change.

On whichever environment is chosen:
1. Enter the company compliance data: UEN, CSN, AIS mode `EXPORT_ONLY`.
   - For a foreign employee whose pass ends in a payroll month, record the pass end date **and** its reason (`CANCELLED` / `EXPIRED`).
   - A cancellation is levied up to the day before (MOM).
   - An expiry, or a missing reason, blocks that month's levy by design: the expiry rule is unpublished.
2. Add one citizen and one foreign-pass employee.
3. Run **two** monthly payrolls.
4. **Expected results:**
   - CPF / SDL / SHG / FWL match the golden expectations for the same facts;
   - payslips pin `SG-PAYROLL-2026 v1.2`;
   - cycle 2 carries cycle 1's YTD.
5. Generate SDL, CPF contribution, IR8A (preview) and EZPay.
   - **Expected:** masked NRIC/FIN; pack and template versions recorded.
   - EZPay: the preparer's approval is refused; a second user approves; the download has 150-byte ASCII records.
6. Correct the **latest** payslip and regenerate.
   - **Expected:** the original is preserved; the delta is linked; the previous report is Superseded; the audit lists the superseded id.

## K. Audit verification
First, the Readiness **activation dashboard**: every category must be `PASS` except production activation, which lists only "service registry PLANNED" at this point. Then, in the pack and template **Audit** tabs and on the Readiness page:
- every approval, activation, refusal and generation is present, with actor and time;
- no refused action left a pending approval;
- hotfix activations awaiting review = 0.

## L. Registry `AVAILABLE` switch (the only step that opens onboarding)
**Preconditions:** A1–A7, F–K all signed off (J under J-1 on the copy, or J-2 immediately after this step).

1. The owner changes the `jurisdiction_service_registry` row for `SG` from `PLANNED` to `AVAILABLE`, as a single audited change record. No UI action exists for this; it is deliberately a controlled owner step.
2. **Expected:** Singapore onboarding opens. It closes again automatically if no Singapore pack is Active.

## M. Monitoring (first two payroll cycles)
- **Errors:** application logs for the SG payroll/report routes; EZPay validation refusals.
- **Readiness page:** external dependencies unchanged; hotfixes awaiting review = 0.
- **Payment deadlines:** the CPF submission and payment clock (last day of the month, enforcement date) for every onboarded organisation.
- **Outcomes:** EZPay and IR8A outcomes recorded (never assumed), with REJECTED errors captured verbatim.

## N. Rollback
| Situation | Action |
|---|---|
| Migration refused, or C/D output differs | Nothing was changed. Stop, investigate, reschedule. |
| Failure after migration, before L | Restore the B backup. Onboarding was never open. |
| Defect after L | Set the SG registry row back to `PLANNED` (closes onboarding); fix forward, or restore B if data integrity is affected. |
| Statutory content defect after activation | Create a new pack version, then approve (B) and activate (C). A hotfix only under the D2 policy, with a distinct reviewer. |

**Never:** downgrade by stamping, edit a released pack or template in place, or reactivate a Superseded version (refused).

## O. Post-deployment verification
- [ ] `alembic current` = `445abd6a9083`; drift check clean
- [ ] Seed counts equal E, and a second seed run changed nothing
- [ ] Golden vectors PASS 37/37 recorded
- [ ] Pack Active: approver B ≠ activator C; audit rows present
- [ ] Templates Active as planned; all `officialCertification = No`
- [ ] Test tenant J passed; reports carry pack and template versions
- [ ] Registry `PLANNED` until L; `AVAILABLE` only after L
- [ ] G1–G8 evidence filed; D1–D3 decisions filed
- [ ] Backup identifier and change record archived
