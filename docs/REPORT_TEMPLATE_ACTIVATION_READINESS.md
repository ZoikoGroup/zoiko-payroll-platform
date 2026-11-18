# Report-template activation readiness: other teams' Published templates

*Read-only review, 2026-11-18. No code or data was changed.*

After fix `b82bccaa` (report-template four-eyes rules) is deployed, 36 Published report templates become activatable. 24 of them belong to other teams and were published without those teams' sign-off:

| Country | Templates | Recommendation |
|---|---|---|
| Singapore | 11 | Don't activate |
| Ireland | 6 | Don't activate |
| Netherlands | 5 | Don't activate |
| Switzerland | CH-LOHNAUSWEIS | Don't activate |
| Sweden | SE-AGI-INDIVIDUAL | Don't activate |
| Germany | DE-PAYROLL-SUMMARY | Ask owner (not now) |

This document covers those 24. The other 12 of the 36 were not named in the request and are not assessed here. To list all 36, run `python -m scripts.report_stuck_published_templates` from `backend/`. It is a read-only dry run.

**Why this matters now:**
- None of these six countries has a code-level gate that refuses template activation. Ireland, Singapore, Switzerland, Sweden and Germany have no `template_activation_refusal` hook (`backend/app/modules/payroll/jurisdiction_hooks.py:27-43`). The Netherlands' hook always returns `None` (`netherlands_service.py:2202-2203`).
- After `b82bccaa`, the only checks left at Active are:
  - the four-eyes rules R1/R2;
  - R3 ("the approver may not activate") for SG, NL, CH and SE;
  - one Active template per country, state, year and report type.
- So whether these templates may be activated is a governance decision, not something the code will stop.

**Sources:**
- Each country's docs under `docs/`.
- The seed and service definitions in `backend/`.
- Gate code, where it exists.

File references are to the working tree on `nikhil`. Some Singapore docs have uncommitted local edits; the working-tree text was used.

---

## Points that apply to all 24

1. **No owner has signed off any of the 24 templates in the repository.** The docs name roles, never people:
   - Singapore's sign-off table has blank names (`docs/SINGAPORE_RELEASE_CHECKLIST.md:43-51`).
   - Ireland, the Netherlands, Switzerland and Sweden have no country document under `docs/` at all.
2. **None of the 24 is officially certified.** Each is either:
   - explicitly not certified (Singapore: "not approved or certified by CPF Board, IRAS, MOM or PDPC", `statutory_summary.py:107`); or
   - explicitly not the official filing (IE ROS file, NL loonaangifte, SE AGI XML, DE ELSTER/DEÜV); or
   - silent on certification.
3. **Published templates are already usable for generation.** `get_applicable_report_template` falls back to a Published template when no Active one exists (`service.py:12549-12556`), and the generation check requires "published", not Active. So leaving these un-activated does not fully stop their use: an organisation in that country can already generate from them.
4. **Organisations need more than a registration listing.** All six countries are listed in `REGISTRATION_COUNTRIES` (`app/core/jurisdiction.py:27-84`). Production onboarding also needs:
   - the country's registry row to be AVAILABLE;
   - an Active canonical pack (`get_jurisdiction_onboarding_block_reason`, comment at `jurisdiction.py:69-72`).

   The trial route (`/auth/register-trial`) has no pack requirement (`jurisdiction.py:22-26`). Exposure through trial organisations should be checked separately.
5. **A Published template cannot go back to Draft.** Its only moves are Active or Superseded (`REPORT_TEMPLATE_TRANSITIONS`). If an owner wants one withdrawn, the path is to Supersede it and later publish a new version.

---

## Singapore (11): don't activate

Overall state per docs:
- **PRODUCTION READY: NO** and **PRODUCTION OPERATIONAL: NO.** "Packs Draft, 11 templates Draft, registry PLANNED" (`docs/SINGAPORE_FINAL_RELEASE_READINESS.md:10-11`).
- **0 `SG-GATE-*` artifacts** are held in production (`docs/SINGAPORE_G1_G8_GATE_MATRIX.md:3`). "No gate has evidence today", and D1–D3 are `BUSINESS_DECISION_REQUIRED` (`docs/SINGAPORE_EXTERNAL_EVIDENCE_HANDOFF.md:6`).
- **The runbook orders template promotion (step I) after:**
  1. the failed `d4369e7` deploy is resolved and the deploy owner signs off (`SG-OPS-DEPLOYMENT`);
  2. G1 is accepted;
  3. the production golden run passes;
  4. Super Admin B approves pack 158 and Super Admin C activates it.

  Promotion then needs at least three distinct Super Admins (`docs/SINGAPORE_PRODUCTION_ACTIVATION_RUNBOOK.md:3, 7, 119-127`; release readiness `:79-90`).
- **Open business item:** confirm that Super Admins 1, 17 and 18 are distinct people (`SINGAPORE_FINAL_RELEASE_READINESS.md:75`).
- **Certification:** "Zoiko holds no CPF Board, IRAS, MOM or PDPC approval … `officialCertification` is `false` everywhere" (`docs/SINGAPORE_FINAL_IMPLEMENTATION_STATUS.md:15`). "Obtain accountable Singapore statutory and privacy review before production activation" (`docs/SINGAPORE_PHASE_5_7_PRODUCTION_FILE_MANIFEST.md:183`).
- **Owners (roles only):**
  - Statutory compliance owner: G1, G4, G5;
  - Employer payroll operations: G2;
  - Product owner: G3 / D1, LQS scope;
  - DPO and security owner: G7;
  - Deploy owner: `SG-OPS-DEPLOYMENT`.

| Template | What it is | Docs' classification / certification | Open gates / decisions (per docs) | Owner (per docs) | Recommendation |
|---|---|---|---|---|---|
| SG-IR8A | IR8A employment-income extract for the employer's own AIS / myTax submission | EXPORT_READY. "Certification: none" (`SINGAPORE_G3_IR8A_AMENDMENT_AND_AIS_DECISION.md:6`); export-only, AIS-API not built (handoff `:99`) | G3 BLOCKED_EXTERNAL (D1 not recorded; needs live filing); D1 decision; G8 | Product owner | Don't activate |
| SG-SDL-MONTHLY | Monthly Skills Development Levy employer total | SUBMISSION_SUPPORT; not certified | G2 (SDL/SHG) BLOCKED_EXTERNAL (gate matrix `:26`) | Employer payroll operations | Don't activate |
| SG-CPF-EZPAY | CPF EZPay FTP contribution file (150-byte ASCII records) | EXPORT_READY; built to the CPF spec, "Spec sample byte-exact" but no live submission (`FINAL_IMPLEMENTATION_STATUS.md:433`) | G1 PENDING_EXTERNAL; G2 BLOCKED_EXTERNAL | Statutory compliance owner; Employer payroll operations | Don't activate |
| SG-PAYROLL-REGISTER | Per-employee payroll register for a run | INTERNAL_REPORT; not certified | None specific (G2 / G8 reconcile against it) | Not stated | Don't activate (ask owner) |
| SG-PAYROLL-SUMMARY | Run totals | INTERNAL_REPORT; not certified | None specific | Not stated | Don't activate (ask owner) |
| SG-CPF-CONTRIBUTION | Employee / employer CPF per employee, for EZPay reconciliation | SUBMISSION_SUPPORT; not certified | G1 PENDING_EXTERNAL ("No reviewer commissioned"); G2; CPF 29-Feb birthday rule EXTERNAL_DATA_REQUIRED (handoff `:114`) | Statutory compliance owner; Employer payroll operations | Don't activate |
| SG-SHG-MONTHLY | Self-Help Group contributions per employee | SUBMISSION_SUPPORT; not certified | G2 BLOCKED_EXTERNAL; G7 (NRIC/FIN/SHG protections) PENDING_EXTERNAL | Employer payroll operations; DPO and security owner | Don't activate |
| SG-FWL-MONTHLY | Foreign Worker Levy reconciliation against the MOM bill | INTERNAL_REPORT; not certified | G5 BLOCKED_EXTERNAL ("MOM expiry rule unpublished"); two MOM data items EXTERNAL_DATA_REQUIRED (handoff `:111-112`) | Statutory compliance owner | Don't activate |
| SG-PWM-COMPLIANCE | Progressive Wage Model compliance workspace | STATUTORY_WORKSPACE; "Not an MOM submission"; not certified | G5 (LQS/PWM) BLOCKED_EXTERNAL | Statutory compliance owner | Don't activate |
| SG-IR21-REGISTER | IR21 tax-clearance case register (NRIC masked) | STATUTORY_WORKSPACE; "Not built: a Form IR21 content extract" (`FINAL_IMPLEMENTATION_STATUS.md:296`) | G4 PENDING_EXTERNAL (review) / BLOCKED_EXTERNAL (filing) | Statutory compliance owner | Don't activate |
| SG-LQS-COMPLIANCE | Local Qualifying Salary check per employee | STATUTORY_WORKSPACE; quota "not computed anywhere … fails safe" (`FINAL_IMPLEMENTATION_STATUS.md:330-332`) | G5 BLOCKED_EXTERNAL; LQS quota scope open decision (release readiness `:76`) | Statutory compliance owner; Product owner | Don't activate |

**Also open:** the 2027 template versions are an open business decision (`SINGAPORE_FINAL_RELEASE_READINESS.md:77`).

The docs record all 11 as Draft. If production now shows them Published, they were promoted outside the runbook's order.

---

## Ireland (6): don't activate

Overall state per repository (there is no Ireland document under `docs/`):
- **Seeded Draft only:** "a Super Admin must review, Approve, Publish and Activate before an organization can generate against them" (`backend/scripts/seed_statutory_report_templates.py:1598-1600`).
- **None is the ROS submission file:** "Revenue's published ROS file format / upload specification is external evidence not present in this repository" (`:1609-1615`).
- **G1 is open.**
  - There are no real golden cases: "No real golden cases exist yet… certifies nothing" (`backend/tests/fixtures/ie_golden/README.md:7-33`).
  - Two blocking G1 divergences are unresolved and kept as xfail tests (README `:35-51`; `backend/tests/test_engine_ireland.py:131-141, 168-174`):
    - PAYE: 533.32 vs 533.33;
    - net pay: 3157.61 vs 3218.67, a 61.06 gap still to be traced.
  - They need "the signed rounding-stage ruling (IE-009) from the tax specialist".
- **G5 (statutory sick pay) is deliberately empty** pending a specialist ruling (`app/modules/payroll/engine/countries/shared.py:774-790`).
- **Owner:** roles only, "an Irish statutory specialist" and "the tax specialist". No name.

| Template | What it is | Certification (per repo) | Open gates / decisions | Owner | Recommendation |
|---|---|---|---|---|---|
| IE-ROS-EMP-CERT | Per-employee PAYE certificate (RPN, PAYE, USC, PRSI, PRSC, net) | Not stated; not the ROS file | G1 divergences (PAYE and net feed it) | Tax specialist (role) | Don't activate |
| IE-ROS-PAYROLL | Period payroll summary (gross, PAYE, USC, PRSI, PRSC, net) | Not stated; not the ROS file | G1 | Tax specialist (role) | Don't activate |
| IE-PRSI-SCHEDULE | Per-employee PRSI by sub-class / band | Not stated | G1 | Tax specialist (role) | Don't activate |
| IE-USC-SCHEDULE | USC deducted per employee | Not stated | G1 (the net-pay divergence involves the USC method) | Tax specialist (role) | Don't activate |
| IE-MFF-SCHEDULE | MyFutureFund status and contributions; State top-up informational only (IE-018) | Not stated | G1; golden sourcing needs NAERSA / DoF notices | Irish statutory specialist (role) | Don't activate |
| IE-LPT-SCHEDULE | LPT deducted where the RPN instructs it (IE-003) | Not stated | G1; real RPN data unavailable (golden README `:24-28`) | Tax specialist (role) | Don't activate |

---

## Netherlands (5): don't activate

Overall state per repository (there is no Netherlands document under `docs/`):
- **Seeded Draft only.** A test asserts that status (`backend/tests/test_netherlands_report_templates.py:67-72`). The statutory loonaangifte and jaaropgaaf are deliberately not templates (seed `:2359-2366`).
- **Fail-closed by design:**
  - "Live Dutch payroll stays gated until G1–G8 are signed (ZP-NL-ENG-001 §19)" (`netherlands_service.py:2178`).
  - AVAILABLE is "refused until every gate G1–G8 is signed (spec §19: approval of the build is not approval of live payroll)" (`:2158-2159`).
  - `statutory_summary` hard-codes `"available": False` (`:2176`).
- **G1 is effectively open.** Golden cases are "all PROVISIONAL … The official 2026 Belastingdienst wage-tax tables are not in the repository", and the wage tax is "a synthetic row" (`backend/tests/fixtures/nl_golden/README.md:18-22`).
- **G3 (filing) is open.** It uses a "Placeholder structure — NOT the real schema" (`netherlands_filing_service.py:231`).
- **Owner decisions D-1 to D-4** (retention, deletion vs anonymisation, GDPR roles / Art. 28, PKIoverheid custody) block launch (`netherlands_service.py:2082-2087`).
- **Owner:** not stated. Golden vectors need "an independent reviewer (NL-054, NL-055)".

| Template | What it is | Certification (per repo) | Open gates / decisions | Owner | Recommendation |
|---|---|---|---|---|---|
| NL-PAYROLL-REGISTER | Per-run register: gross, loonheffing, deductions, net | Not stated | G1 (loonheffing from synthetic tables); D-1–D-4 | Not stated | Don't activate |
| NL-LOONSTROOK | Payslip data per employee incl. hours, minimum wage, contract, employer cost (NL-048) | Not stated | G1; D-1–D-4 | Not stated | Don't activate |
| NL-EMPLOYER-COST | Employer premiums (AWf, Aof, Wko, Whk, Zvw, pension) | Not stated | G1; G2 (VCR & premiums), by subject, not stated in docs | Not stated | Don't activate |
| NL-LOONAANGIFTE-SUMMARY | Run reconciliation totals | "NOT the return itself" (seed `:2442-2443`) | G3 (stated), G1 | Not stated | Don't activate |
| NL-JOURNAL | Run totals for the accounting journal | Not stated | G1 | Not stated | Don't activate |

---

## Switzerland: CH-LOHNAUSWEIS — don't activate

| | |
|---|---|
| **What it is** | Per-employee, per-calendar-year Swiss salary certificate (Form 11, 2026, employee side), built from committed CH payslips (`backend/app/modules/payroll/switzerland_service.py:2647-2658, 2694-2704`). |
| **Certification** | Not claimed. ELM transmission is switched off (`CH_ELM_TRANSMIT_ENABLED = False`, `:2666-2677`). No seed script creates this template, so where the Published row came from should be confirmed. |
| **Open gates** | CH release gates G1–G7 pass only on reviewed `CH-GATE-Gn` evidence (`:2116-2152`). Some checks are hard-coded `False`, so readiness cannot pass today: G1 "PENDING G1 SIGN-OFF" (`:2184`) and G4 "No certified ELM transmission channel exists" (`:2196`). Federal values are still `needs_g1`, and the golden cases "are **not** gate evidence" (`backend/tests/fixtures/ch_golden/README.md`). |
| **Owner** | Not stated (no Switzerland document in `docs/`). |
| **Recommendation** | **Don't activate.** Ask the Switzerland owner where the row came from and confirm G1. |

## Sweden: SE-AGI-INDIVIDUAL — don't activate

| | |
|---|---|
| **What it is** | Per-payee data extract for the AGI individual return, report type AGI (`backend/scripts/seed_sweden_canonical_packs.py:399-420`). |
| **Certification** | "Data extract only — XML generation and Skatteverket schema validation are a separate, gated phase (SE-008)" (`:417-420`). "this template never claims a filing channel" (`:403-405`). |
| **Open gates** | §16 readiness has items hard-coded `False`: `agi_xml` "Not built" and `parallel_payroll` "Evidence required from the implementation team" (`service.py:43269-43272`). Tax tables 29–42 are not yet entered (`se_golden/README.md`). The employer-contribution split "MUST be confirmed by the Swedish statutory reviewer before activation" (seed `:27-29`). Registry `PLANNED`, filing `NOT_OFFERED` (seed `:468-470`). "Nothing here activates live Swedish payroll" (`service.py:43202`). |
| **Owner** | Roles only: "Swedish statutory reviewer", "implementation team". |
| **Recommendation** | **Don't activate.** |

## Germany: DE-PAYROLL-SUMMARY — ask owner (not now)

| | |
|---|---|
| **What it is** | Aggregate per-run summary: gross, Lohnsteuer + Soli, KiSt, employee / employer social insurance (`backend/scripts/seed_statutory_report_templates.py:1544-1576`). |
| **Certification** | Internal summary, not a filing; DEÜV and ELSTER are deliberately not seeded (`:1577-1587`). The wage tax behind it: "Official BMF PAP equivalence has not been independently established" (`docs/GERMANY_2026_ORG38_LIVE_PAYROLL_UAT_FINAL.md:111-112`). |
| **Open gates** | PAP has 0 of 8 gates satisfied, all blocking (`docs/GERMANY_PAP_PRODUCTION_GATE_EVIDENCE_MATRIX.md`). The runbook says "Do not execute any step…" until legal counsel's determination (`docs/GERMANY_PAP_ACTIVATION_RUNBOOK.md:5-10`). Germany is "NOT marked PRODUCTION READY … CONDITIONAL GO (86/100)" (`docs/GERMANY_JURISDICTION_PRODUCTION_READINESS_REPORT.md:140, 157`). One doc disagrees: `docs/GERMANY_2026_FINAL_STATUTORY_VALIDATION_REPORT.md:4` says "READY FOR PRODUCTION". |
| **Known defects** | Live template labels are stale (ORG38 doc `:99, :116`). The row-count reconciliation always shows MISMATCH (`docs/GERMANY_2026_REPORT_TEMPLATES_IMPLEMENTATION_REPORT.md:174`). |
| **Owner** | Not named: "whoever owns republishing those two live templates" (ORG38 doc `:153`); PAP licensing needs legal counsel. |
| **Recommendation** | **Ask the Germany owner. Don't activate now.** It was generated from while Published in the Org 38 UAT ("does not require `Active` status", ORG38 doc `:79`), so activation adds no capability. Activating would make the current version, with its known label and reconciliation defects, the one that wins, while PAP gates are 0/8. |

---

## Suggested next steps (for owners, not actions taken)

1. **Ask each owner to confirm, before anyone activates these after `b82bccaa` deploys:**
   - Singapore: statutory compliance owner and product owner.
   - Ireland: tax specialist.
   - Netherlands: not named in docs.
   - Switzerland: not named in docs.
   - Sweden: statutory reviewer.
   - Germany: not named in docs.
2. **Decide with each owner whether the Published versions should be Superseded.** Point 3 above means they are usable for generation even without Active.
3. **Check trial organisations** (`/auth/register-trial`) in these countries for reports generated from these templates.
4. **Confirm the Super Admin accounts are distinct people.** Singapore lists this as open; the same accounts published these templates.
