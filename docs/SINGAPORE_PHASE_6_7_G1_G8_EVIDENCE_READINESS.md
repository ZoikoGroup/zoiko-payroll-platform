# Singapore Payroll — Phase 6.7 G1–G8 External-Evidence Readiness

- **Date:** 2026-09-28. Branch `nikhil` @ `83601eb`, uncommitted.
- **Baseline:** `docs/SINGAPORE_PHASE_6_6_PRODUCTION_GATE_READINESS.md` §4. Gate wording: ZP-SG-ENG-001 §18.
- **Rule:** no gate is COMPLETE. No CPF Board / IRAS / MOM / PDPC approval, certification, acceptance or partner
  result exists. Internal golden vectors and rehearsals are **internal engineering evidence only**.
- **Statuses:** ENGINEERING COMPLETE (EC), EXTERNAL EVIDENCE REQUIRED (EER), BUSINESS APPROVAL REQUIRED (BAR), BLOCKED,
  COMPLETE.

## 1. Priority order and next actions

| # | Evidence | Gate(s) | Owner | Next action | Blocks |
|---|---|---|---|---|---|
| 1 | Independent CPF comparison | G1 (feeds G2, G8) | Statutory compliance owner | Engage an independent reviewer; give them the 36 golden cases and CPF Board sources; agree the case set and tolerance (zero) | Commercial activation |
| 2 | Design-partner parallel run | G8 (feeds G2, G5, G6) | Implementation lead | Select a Singapore employer; sign a data-processing agreement (G7); run two consecutive cycles in parallel with their current payroll | Activation |
| 3 | PDPA / DPO evidence | G7 | DPO + security owner | DPO review of roles, transfers, retention and NRIC/FIN handling; security review; recovery test | Processing real employee data (so it gates #2) |
| 4 | MOM evidence | G5, G6 | Statutory compliance owner + legal | Obtain unpublished values or scope them out; reconcile one real MOM levy bill; legal review of Employment Act controls | Activation |
| 5 | IRAS / G3 | G3, G4 | Product owner | Export-only vs API decision; register the IRAS modification guide; design→build revision/amendment; IRAS acknowledgement of an original and a modification | Activation |
| 6 | Unpublished statutory values | G5 | Statutory compliance owner | Pre-July-2026 part-time LQS; Work Permit levy before 24 Sep 2026 outside construction (pack BLOCKED rows) | Affected cohorts only |

## 2. Gate matrix

| Gate | Requirement | Engineering status | Existing internal evidence | Missing external evidence | Required artifact | Owner | Authority | Acceptance criterion | Dependency | Status |
|---|---|---|---|---|---|---|---|---|---|---|
| G1 CPF content | 2026 SC/SPR tables, low-wage formulas, OW/AW classification, ceilings, rounding and 2027 boundary independently certified | CPF engine, 2026 + 2027 packs (Draft) | Hashed CPF Board sources (rate tables, AW ceiling, SDL, SHG); 36/36 golden incl. CPF Board worked examples and 2027 boundary; PostgreSQL rehearsals matched golden F1/F2/F4 | Independent certification | Signed independent comparison report (cases, sources, zero unexplained differences) | Statutory compliance owner | Independent reviewer; CPF Board sources | Every agreed case matches to the cent; reviewer signs | None | EC · **EER** |
| G2 CPF operations | CSN workflow, EZPay FTP output, SDL/SHG values, payment, amendment/reconciliation proven | EZPay builder (spec sample byte-exact), maker-checker lifecycle, supplementary advice, SDL/SHG | Tests; rehearsal file (14 × 150-byte records, sha256 verified) | CPF Board acceptance of a real file; payment reconciliation | CPF acknowledgement + bank/payment reconciliation record | Employer payroll operations | CPF Board (EZPay / Corppass) | File accepted; totals reconcile to payroll | #2, #3 | EC · **EER** |
| G3 IRAS | AIS YA2027 model validated; AIS-API 2.0 onboarding or explicit export-only; amendment + acknowledgement proven | Export-only original extract + lifecycle; 6.7 guard; revision/amendment designed, **not built**; API not built | Extract / lifecycle tests; IRAS modification guide retrieved (E1) | IRAS validation; acknowledgements; onboarding if API | Signed mode decision; acknowledged original + modification | Product owner | IRAS (myTax Portal / APEX) | See the G3 decision doc §J | #3, #5 | **BAR · EER** (implementation gap: revision/amendment) |
| G4 Tax clearance | IR21 trigger, hold, filing, directive, release/remittance, exceptions validated with current IRAS guidance | Full IR21 lifecycle, distinct-approver release (refusals audited), bank hold, amended-IR21 exception path | Lifecycle tests; register | Validation against current IRAS guidance; a real filing | Compliance review memo; IRAS acknowledgement of a filing | Statutory compliance owner | IRAS | Workflow matches guidance; filing acknowledged | #3 | EC · **EER** |
| G5 Foreign workforce | Work-pass/CPF distinction, levy billing, LQS/PWM gating, prohibited levy recovery | S Pass / WP handling; levy employer-only; LQS / PWM approval gates; 6,132 MOM PWM cells | Tests; rehearsals (levy never deducted; PWM shortfall blocks approval) | Reconciliation with a real MOM levy bill; unpublished values | Levy-bill reconciliation; published MOM values or a signed scope-out | Statutory compliance owner | MOM | Bill reconciles; no BLOCKED rows in scope | #2, #6 | EC · **EER** · partly **BLOCKED** |
| G6 Labour pay | Salary deadlines, payslip, authorised deductions, Part IV overtime, leave/public holidays validated | Employment Act rules; Part IV overtime; MOM incomplete-month; gazetted holidays | Tests (MOM incomplete-month table reproduced); rehearsal overtime | Legal / MOM validation | Legal review memo | Legal + compliance owner | MOM / counsel | No open legal findings | None | EC · **EER** |
| G7 Security/privacy | PDPA roles/transfers/retention, NRIC/FIN/SHG protections, credentials, tenant isolation, recovery approved | PDPC partial masking; tenant isolation; Super Admin RBAC; refusal auditing; hotfix maker-checker; retention report; deploy-script safety patch (merge-time) | Tests; rehearsals | DPO approval; security review; recovery test | DPO sign-off; security review report; recovery test record | DPO + security owner | PDPC framework (internal DPO) | Approvals signed; no open critical findings | Deploy patch applied at merge | EC · **EER · BAR** |
| G8 Parallel payroll | Two cycles + annual AIS simulation, zero unexplained material differences | Two-cycle rehearsals incl. the migrated shared-lineage copy | 172-PASS rehearsals (6.5, 6.6) | A live design-partner run; an annual AIS simulation on real data | Parallel-run reconciliation report | Implementation lead | Design-partner employer | Two cycles + AIS with zero unexplained material differences | #2, #3 | EC (rehearsal) · **EER** |

## 3. Evidence checklist (artifacts to collect)
- [ ] G1 independent comparison report (signed)
- [ ] G2 CPF EZPay acknowledgement + payment reconciliation
- [ ] G3 signed export-only / API decision; IRAS acknowledgement of an original and a modification
- [ ] G4 IR21 guidance review + acknowledged filing
- [ ] G5 MOM levy-bill reconciliation; published values or signed scope-out
- [ ] G6 legal review memo
- [ ] G7 DPO sign-off; security review; recovery test record
- [ ] G8 parallel-run report (two cycles + AIS simulation)

## 4. Owner decisions outstanding (not made by engineering)

**Singapore hotfix policy.** Unchanged, pending a decision.

| Option | Technical | Audit | Operational | Maker-checker | Production risk |
|---|---|---|---|---|---|
| 1. Keep (current) | No change | Record + audit; review must be by another Super Admin (6.6) | A lone Super Admin can activate an evidenced, golden-PASS pack in an emergency | Deferred to a mandatory distinct review | An unreviewed hotfix can sit open; no enforcement window |
| 2. Prohibit for Singapore | One isolated country check in `activate_jurisdiction_pack_hotfix` | Refusals audited | Emergencies need two available Super Admins | Always up-front | Slower emergency response |
| 3. Allow + enforced post-review | New checks: block further Singapore activations while an unreviewed Singapore hotfix exists (optionally a review deadline) | Adds enforcement evidence | Needs a reviewer within the window | Deferred but enforced | Design and implementation effort; must avoid deadlocking a needed follow-up fix |

**Universal scope.** Unchanged, pending a decision.
- Atomic hotfix persistence already applies to **all countries**.
- The distinct hotfix reviewer (6.6), the refused-action audit (6.5) and Approve-step self-approval (6.5) apply to
  **Singapore only**.
- Making the reviewer rule universal means:
  - countries operated by a single Super Admin could never close a hotfix review (operational deadlock);
  - no current test breaks (the one UK review test uses a distinct reviewer);
  - it's a one-line constant change.

  The decision belongs to the product owner.
