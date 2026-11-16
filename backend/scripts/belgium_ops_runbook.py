"""Belgium (ZP-BE-ENG-001) Block I3: generate docs/belgium/OPERATIONS_RUNBOOK.md from the codes in the code.

    python -m scripts.belgium_ops_runbook          # (re)write the runbook
    python -m scripts.belgium_ops_runbook --check  # exit 1 if the runbook is out of date or a code is undocumented

The code list is DISCOVERED, not typed: every string literal shaped ``BE_…`` in the Belgian modules
(belgium*.py, be_*.py, engine/countries/belgium*.py, engine/jurisdictions/belgium/*.py), minus the known
identifiers (settings names, pack rule types, calendar report types, payment channels). Every discovered code
must have a CATALOGUE entry and every entry must still exist in the code (tests/test_belgium_ops_runbook.py), so
the runbook cannot drift from the code.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PAYROLL = BACKEND / "app" / "modules" / "payroll"
RUNBOOK = BACKEND.parent / "docs" / "belgium" / "OPERATIONS_RUNBOOK.md"
_LITERAL = re.compile(r"""["'](BE_[A-Z0-9_]+)["']""")

# Literals that are names, not operational codes (each says what it is).
IDENTIFIERS = {
    "BE_TENANT_ONBOARDING_ENABLED": "setting", "BE_CANARY_ORG_IDS": "setting", "BE_DEMO_PACKS_ENABLED": "setting",
    "BE_DEMO_ORG_IDS": "setting", "BE_IDENTIFIER_KEYRING": "setting", "BE_IDENTIFIER_FINGERPRINT_KEY": "setting",
    "BE_ABS_MATERNITY_MULTIPLE": "pack rule type", "BE_AUTHORITY_EXAMPLE": "pack rule type",
    "BE_EARNING_CLASS": "pack rule type", "BE_PUBLIC_HOLIDAY": "pack rule type",
    "BE_FILING_DIMONA_SCHEMA": "pack rule type", "BE_FILING_DMFA_SCHEMA": "pack rule type",
    "BE_FILING_FINPROF_SCHEMA": "pack rule type", "BE_FILING_BELCOTAX_SCHEMA": "pack rule type",
    "BE_DMFA": "calendar report type", "BE_FINPROF": "calendar report type", "BE_BELCOTAX": "calendar report type",
    "BE_ONSS_ADVANCE": "calendar report type", "BE_HOLIDAY_FUND": "calendar report type",
    "BE_SEPA_BATCH": "payment channel", "BE_PAYMENT_BATCH": "payment treatment",
    "BE_RECORDS": "report field source kind", "BE_LEDGER": "report field source kind",
    "BE_SNAPSHOT": "report field source kind", "BE_FILING": "report field source kind",
    "BE_HOLIDAY_CERT": "report field source kind",
}

# Owners
CONTENT = "Super Admin content (Belgian specialist signs)"
SETUP = "Org admin — organisation setup"
EMPLOYEE = "Org admin — employee statutory data"
OPERATOR = "Payroll operator"
AUTHORITY = "Authority / mandate holder"
ENGINEERING = "Engineering (not built — no workaround)"

# code -> (kind, meaning, likely cause, owner, how to fix)
CATALOGUE = {
    # ── scaffold / pack reader ──
    "BE_SIMPLE_MODE_UNSUPPORTED": ("BLOCK", "Simple calculation mode is not available for Belgium.",
                                   "A run or preview requested simple mode.", OPERATOR,
                                   "Use the standard calculation mode."),
    "BE_ENGINE_NOT_BUILT": ("BLOCK", "A Belgian calculation path that is not built was reached.",
                            "A feature outside the built scope.", ENGINEERING, "Escalate; do not pay manually."),
    "BE_CONTENT_PENDING": ("BLOCK", "A content row the calculation needs is not signed (gate G1).",
                           "The Draft pack row is empty, unsourced or unsigned.", CONTENT,
                           "Console → Belgium → the row's tab: enter value + source, a second person signs."),
    "BE_FEATURE_BLOCKED": ("BLOCK", "The pack decides the feature is NOT_SUPPORTED.",
                           "An owner decision in the pack marks the case unsupported.", CONTENT,
                           "Review the decision (Owner decisions tab); keep the employee out of Belgian payroll."),
    "BE_ROW_MISSING": ("BLOCK", "A required content row is absent from the active pack.",
                       "The pack was seeded before the catalogue gained the key.", CONTENT,
                       "Re-seed the Draft (adds missing rows only), fill and sign it."),
    "BE_TABLE_EMPTY": ("BLOCK", "A band / table key has no signed rows.", "Slab rows not entered or not signed.",
                       CONTENT, "Console → Signing status / slab rows: add rows, a second person signs."),
    "BE_ROUNDING_KEY_INVALID": ("BLOCK", "A rounding rule names an unknown rounding key.",
                                "Content typo in a rounding row.", CONTENT, "Correct the rounding row and re-sign."),
    "BE_BSSC_PENDING": ("EXCEPTION", "The special social security contribution is not computed (decision D7).",
                        "Every Belgian payslip carries it until the specialist decides.", OPERATOR,
                        "Acknowledge with a reason; settle the contribution outside the engine."),
    "BE_PACK_MISSING": ("BLOCK", "No Active Belgian pack is in force on the pay date.",
                        "Pack still Draft, or the pay date is outside its window.", CONTENT,
                        "Complete G1-G7 and activate (runbook); check the run's pay date."),
    # ── applicability resolver ──
    "BE_REGISTRATION_MISSING": ("BLOCK", "No employer registration is in force on the pay date.",
                                "The legal employer was never registered, or the registration starts later.", SETUP,
                                "Compliance → Belgium → Employer registration: record, second person approves."),
    "BE_REGISTRATION_NOT_ACTIVE": ("BLOCK", "The employer registration is Draft / superseded.",
                                   "The registration was not approved.", SETUP,
                                   "A second person approves the registration."),
    "BE_REGISTRATION_UNVERIFIED": ("BLOCK", "The employer registration is not verified.",
                                   "Verification against the ONSS / KBO evidence is outstanding.", SETUP,
                                   "Employer registration → Verify (with the evidence reference)."),
    "BE_EMPLOYER_CATEGORY_UNSUPPORTED": ("BLOCK", "The ONSS employer category is not supported.",
                                         "A category outside the built scope.", ENGINEERING,
                                         "Keep the employer out of Belgian payroll; escalate."),
    "BE_PROFILE_MISSING": ("BLOCK", "The employee has no Belgian worker profile in force.",
                           "Profile not recorded or starts after the pay date.", EMPLOYEE,
                           "Employee → Belgium records → Worker profile: record, second person approves."),
    "BE_PROFILE_NOT_ACTIVE": ("BLOCK", "The worker profile is not approved.", "Profile left in Draft.", EMPLOYEE,
                              "A second person approves the worker profile."),
    "BE_WORKER_CATEGORY_UNSUPPORTED": ("BLOCK", "The worker category is not supported.",
                                       "A category outside white-collar / manual.", ENGINEERING,
                                       "Keep the employee out of Belgian payroll; escalate."),
    "BE_WORKER_CODE_UNSUPPORTED": ("BLOCK", "The ONSS worker code is not supported.", "Code outside the content list.",
                                   CONTENT, "Correct the profile, or the specialist adds the code to the content."),
    "BE_SPECIAL_STATUS_UNSUPPORTED": ("BLOCK", "A special worker status (student, flexi-job, …) is not supported.",
                                      "The profile records a special status.", ENGINEERING,
                                      "Keep the employee out of Belgian payroll; escalate."),
    "BE_FACT_MISSING": ("BLOCK", "A fact the resolver needs is not recorded.",
                        "A required profile / classification field is empty.", EMPLOYEE,
                        "Complete the named field on the employee's Belgian record."),
    "BE_CONTRACT_UNSUPPORTED": ("BLOCK", "The contract type is not supported.", "Contract outside the built scope.",
                                ENGINEERING, "Keep the employee out of Belgian payroll; escalate."),
    "BE_FREQUENCY_UNSUPPORTED": ("BLOCK", "The pay frequency is not supported (monthly only, G-11).",
                                 "Employee set to weekly / bi-weekly pay.", EMPLOYEE,
                                 "Set the employee to Monthly pay."),
    "BE_PAY_BASIS_UNSUPPORTED": ("BLOCK", "The pay basis is not supported.", "Profile pay basis outside the scope.",
                                 EMPLOYEE, "Correct the worker profile's pay basis."),
    "BE_CLASSIFICATION_MISSING": ("BLOCK", "No employment classification is in force.",
                                  "Classification not recorded for the line.", EMPLOYEE,
                                  "Record the employment classification (joint committee, class); approve."),
    "BE_CLASSIFICATION_NOT_ACTIVE": ("BLOCK", "The employment classification is not approved.",
                                     "Classification left in Draft.", EMPLOYEE, "A second person approves it."),
    "BE_JOINT_COMMITTEE_MISSING": ("BLOCK", "The classification has no joint committee.",
                                   "Joint committee field empty.", EMPLOYEE, "Record the joint committee."),
    "BE_AGREEMENT_INVALID": ("BLOCK", "The referenced collective agreement is invalid for the organisation.",
                             "Agreement of another organisation or withdrawn.", SETUP,
                             "Pick a valid agreement on the classification."),
    "BE_UNIT_INVALID": ("BLOCK", "The referenced establishment unit is invalid.",
                        "Unit of another registration or closed.", SETUP,
                        "Pick a valid establishment unit on the classification."),
    "BE_SCHEDULE_MISSING": ("BLOCK", "No work schedule is in force for the line.", "Schedule not recorded.",
                            EMPLOYEE, "Record the work schedule; a second person approves."),
    "BE_SCHEDULE_AMBIGUOUS": ("BLOCK", "Several work schedules are in force for one line.",
                              "Overlapping schedule versions.", EMPLOYEE, "Close the older version."),
    "BE_MID_PERIOD_CLASSIFICATION_CHANGE": ("BLOCK", "The classification changes inside the pay period.",
                                            "A new version starts mid-month.", EMPLOYEE,
                                            "Align the change to the period start, or escalate (not modelled)."),
    "BE_SECTOR_AGREEMENT_MISSING": ("EXCEPTION", "No sector agreement content for the joint committee.",
                                    "Joint committee content not yet entered.", CONTENT,
                                    "Specialist enters the joint committee wage modules; acknowledge meanwhile."),
    "BE_SCALE_INPUT_MISSING": ("EXCEPTION", "A sector-scale input (class, seniority) is missing.",
                               "Classification lacks function class / seniority.", EMPLOYEE,
                               "Complete the classification; acknowledge if knowingly paid."),
    # ── engine ──
    "BE_PAY_DATE_MISSING": ("BLOCK", "The run has no pay date (every rule is selected by it).",
                            "Run created without a pay date.", OPERATOR, "Set the run's pay date."),
    "BE_FORMULA_INVALID": ("BLOCK", "A signed formula does not parse in the restricted grammar.",
                           "Content formula error.", CONTENT, "Correct the formula row; re-sign."),
    "BE_BAND_NOT_FOUND": ("BLOCK", "No band covers the amount.", "Gap in a band table.", CONTENT,
                          "Add the missing band; re-sign."),
    "BE_COMPONENT_UNKNOWN": ("BLOCK", "A pay component is unknown (free text never calculates, BE-008).",
                             "An allowance not mapped to a Belgian component.", SETUP,
                             "Compliance → Belgium → Component mapping: map it; approve."),
    "BE_COMPONENTS_MISMATCH": ("BLOCK", "The components do not add up to gross.",
                               "Inconsistent salary structure on the employee.", EMPLOYEE,
                               "Correct the employee's salary components."),
    "BE_EARNING_CLASS_MISSING": ("BLOCK", "No signed earning treatment for a paid component.",
                                 "Earning classification row unsigned.", CONTENT,
                                 "Console → Earning classification: decide and sign."),
    "BE_EARNING_CLASS_REVIEW": ("BLOCK", "The earning treatment is REVIEW (never calculates, BE-006).",
                                "Specialist has not decided the treatment.", CONTENT, "Decide the treatment and sign."),
    "BE_EARNING_CLASS_CONFLICT": ("BLOCK", "An exceptional earning is also in the regular base (BE-011).",
                                  "Conflicting earning treatments.", CONTENT, "Correct the treatments; re-sign."),
    "BE_SOURCE_PERIOD_MISSING": ("BLOCK", "Arrears / a correction without its source period (BE-009).",
                                 "Correction or arrears entered without the period.", OPERATOR,
                                 "Enter the source period on the correction."),
    "BE_MULTI_LINE_UNSUPPORTED": ("BLOCK", "Pay split across several employment lines is not modelled.",
                                  "Employee has two active lines.", ENGINEERING, "Keep one line; escalate."),
    "BE_NON_RESIDENT_UNSUPPORTED": ("BLOCK", "Non-resident withholding is not built.", "Profile residency NON_RESIDENT.",
                                    ENGINEERING, "Keep the employee out of Belgian payroll; escalate."),
    "BE_YTD_MISSING": ("BLOCK", "Year-to-date facts needed by the rule are missing.",
                       "Mid-year start without prior-period import.", OPERATOR,
                       "Import the prior periods (parallel / opening balances) or escalate."),
    "BE_DECLARATION_INVALID": ("BLOCK", "A withholding declaration is invalid for the pay date.",
                               "Declaration withdrawn / overlapping.", EMPLOYEE,
                               "Employee → declarations: correct and approve."),
    "BE_NEGATIVE_NET": ("EXCEPTION", "Net pay would be negative.", "Deductions exceed pay this month.", OPERATOR,
                        "Review the inputs; acknowledge only with a recovery plan."),
    "BE_REDUCTION_CAPPED": ("EXCEPTION", "A reduction was capped by its limit.", "High reductions this month.",
                            OPERATOR, "Review; acknowledge if expected."),
    "BE_SPECIAL_160_UNKNOWN": ("BLOCK", "The employer's special contribution (workforce test) status is UNKNOWN.",
                               "Registration recorded without the status (G-25).", SETUP,
                               "Employer registration: record APPLIES / NOT_APPLICABLE with evidence."),
    "BE_COMPONENT_UNMAPPED": ("BLOCK", "Platform pay has no ACTIVE Belgian component mapping (G-28).",
                              "New allowance added without mapping.", SETUP,
                              "Component mapping: map the platform component; approve."),
    "BE_REDUCTION_UNSUPPORTED": ("BLOCK", "A reduction applies but is not built (G-27).", "Employer qualifies for a "
                                 "target-group reduction.", ENGINEERING, "Escalate; do not pay manually."),
    "BE_BENEFIT_IN_KIND_UNSUPPORTED": ("BLOCK", "Benefit in kind (company car …) valuation is not built (G-27).",
                                       "Employee has a benefit in kind.", ENGINEERING, "Escalate."),
    # Block M-ECWC: the ONSS rate table
    "BE_ONSS_RATE_TABLE_MISSING": ("BLOCK", "No ONSS rate file covers the pay date's quarter.",
                                   "The quarter's DmfA rate file is not registered on the pack.", CONTENT,
                                   "Super Admin: register the archived quarterly rate ZIP, attest, sign the subset."),
    "BE_ONSS_RATE_FILE_UNATTESTED": ("BLOCK", "The quarter's ONSS rate file is not attested as the genuine "
                                              "publication.", "Registered but not yet attested.", CONTENT,
                                     "A Super Admin other than the registrar attests the archived file."),
    "BE_ONSS_RATE_UNSIGNED": ("BLOCK", "A rate row, combination or type rule in use is not signed.",
                              "Made live but not yet signed (a signed file does not sign its rows).", CONTENT,
                              "A Super Admin other than the registrar / the one who made it live signs it."),
    "BE_ONSS_RATE_ROW_MISSING": ("BLOCK", "No live rate row for the employer category, code and ContributionType.",
                                 "The code is not in the live subset of the quarter's file.", CONTENT,
                                 "Super Admin: mark the supported codes live and sign them."),
    "BE_ONSS_RATE_FLAT_UNSUPPORTED": ("BLOCK", "A flat amount or quarterly minimum applies; not calculated yet.",
                                      "The rate row carries a flat amount / minimum.", ENGINEERING, "Escalate."),
    "BE_ONSS_RATE_PERSONAL_UNSUPPORTED": ("BLOCK", "A combined contribution has a personal share; not calculated "
                                                   "yet.", "The combined code is employee-borne.", ENGINEERING,
                                          "Escalate; do not mark this code live."),
    "BE_ONSS_FACT_MISSING": ("BLOCK", "An employer fact selecting the ContributionType (closure-fund sector, "
                                      "workforce class, wage moderation) or its evidence is missing.",
                             "Registration recorded without the fact or its evidence reference.", SETUP,
                             "Employer registration: record the fact with its evidence reference (four-eyes)."),
    "BE_ONSS_TYPE_UNRESOLVED": ("BLOCK", "No signed type rule gives the code's ContributionType for these facts.",
                                "Type rules missing for this combination of facts.", CONTENT,
                                "Super Admin: add the rule from the DmfA glossary annex 3; another signs it."),
    "BE_ONSS_TYPE_AMBIGUOUS": ("BLOCK", "Signed type rules give different ContributionTypes for the same facts.",
                               "Overlapping type rules.", CONTENT, "Super Admin: correct the overlapping rules."),
    "BE_ONSS_RATE_MARKERS_MIXED": ("BLOCK", "Employer base and fund contributions are not both on the rate table.",
                                   "One key signed RATE_TABLE, the other SLAB_ROWS.", CONTENT,
                                   "Sign both keys RATE_TABLE (or both SLAB_ROWS)."),
    "BE_SECTOR_MINIMUM_UNVERIFIED": ("EXCEPTION", "The sector minimum is not verified.",
                                     "Joint committee scale unsigned.", CONTENT,
                                     "Specialist signs the scale; acknowledge meanwhile."),
    "BE_SCALE_ROW_MISSING": ("EXCEPTION", "No scale row for the class / seniority.", "Scale table incomplete.", CONTENT,
                             "Add the scale row; acknowledge meanwhile."),
    "BE_MINIMUM_WAGE_BREACH": ("EXCEPTION", "Pay is below the applicable minimum — never auto-paid.",
                               "Salary under the sector / national minimum.", EMPLOYEE,
                               "Correct the salary; acknowledge only with legal sign-off."),
    "BE_INDEXATION_ABOVE_LIMIT": ("EXCEPTION", "An indexation above the configured limit.", "Indexation input error.",
                                  OPERATOR, "Check the indexation input."),
    "BE_WAGE_NORM_WARNING": ("WARNING", "Pay increase may exceed the wage norm.", "Large raise.", OPERATOR,
                             "Informational; HR confirms."),
    "BE_OVERTIME_FACTS_MISSING": ("BLOCK", "Overtime paid without the overtime facts.",
                                  "Overtime amount without hours / attendance.", OPERATOR,
                                  "Record attendance hours for the period."),
    "BE_WORKING_TIME_LIMIT": ("EXCEPTION", "A working-time limit is exceeded.", "Hours above the limit.", OPERATOR,
                              "Review the attendance; acknowledge with a reason."),
    "BE_OVERTIME_PREMIUM_UNVERIFIED": ("EXCEPTION", "The overtime premium rule is not verified.",
                                       "Content unsigned.", CONTENT, "Specialist signs; acknowledge meanwhile."),
    "BE_OVERTIME_PREMIUM_SHORT": ("EXCEPTION", "The overtime premium paid is short.", "Premium input too low.",
                                  OPERATOR, "Correct the premium."),
    "BE_HOLIDAY_CATEGORY_TRANSITION": ("EXCEPTION", "The employee changed manual / white-collar this year.",
                                       "Category change in the profile history.", OPERATOR,
                                       "Review holiday pay split; acknowledge."),
    "BE_HOLIDAY_PAID_BY_FUND": ("EXCEPTION", "Manual worker holiday pay is paid by the holiday fund.",
                                "Holiday pay entered for a manual worker.", OPERATOR,
                                "Remove the holiday pay; the fund pays."),
    "BE_HOLIDAY_FUND_MISMATCH": ("EXCEPTION", "Holiday fund amounts do not match.", "Certificate vs ledger difference.",
                                 OPERATOR, "Check the holiday certificate."),
    "BE_HOLIDAY_PAY_SHORT": ("EXCEPTION", "Holiday pay is short of the computed due.", "Input too low.", OPERATOR,
                             "Correct the holiday pay input."),
    "BE_ABSENCE_DIFFERENT_CAUSE": ("EXCEPTION", "Overlapping absence episodes with different causes.",
                                   "Episodes recorded inconsistently.", EMPLOYEE, "Correct the absence episodes."),
    "BE_ABSENCE_PAY_UNVERIFIED": ("EXCEPTION", "Absence pay rule not verified.", "Content unsigned.", CONTENT,
                                  "Specialist signs; acknowledge meanwhile."),
    "BE_ABSENCE_PAY_SHORT": ("EXCEPTION", "Guaranteed salary paid is short.", "Input too low.", OPERATOR,
                             "Correct the absence pay."),
    # ── run lifecycle / preflight ──
    "BE_PAYSLIP_BLOCKED": ("PREFLIGHT", "The employee's calculation is blocked in this run.",
                           "See the block on the payslip remarks.", OPERATOR, "Fix the named block; regenerate."),
    "BE_RESOLVER_FAILED": ("PREFLIGHT", "The classification resolver failed for the employee.",
                           "Inconsistent Belgian records.", EMPLOYEE, "Open the employee's Belgian records; correct."),
    "BE_DEMO_DIMONA_SIMULATED": ("PREFLIGHT", "Demo organisation: Dimona is simulated (never transmitted).",
                                 "Staging demo only.", OPERATOR, "Informational (demo)."),
    "BE_DIMONA_IN_MISSING": ("PREFLIGHT", "No Dimona IN for the employment line (BE-033).",
                             "Hire not declared.", OPERATOR, "Filing centre → Dimona: build, approve, transmit."),
    "BE_DIMONA_IN_NOT_ACCEPTED": ("PREFLIGHT", "The Dimona IN is not accepted yet.", "Awaiting the authority.",
                                  AUTHORITY, "Record the authority's response when received."),
    "BE_DIMONA_IN_CANCELLED": ("PREFLIGHT", "The Dimona IN was cancelled.", "Cancelled declaration.", OPERATOR,
                               "Build a new Dimona IN."),
    "BE_PAYSLIP_NO_SNAPSHOT": ("REFUSAL", "A Belgian payslip without its frozen calculation — no PDF.",
                               "Payslip from a failed / legacy generation.", OPERATOR, "Recalculate the run."),
    # ── filings / obligations ──
    "BE_DEMO_FILING": ("REFUSAL", "A demo filing is never submitted or transmitted.", "Demo organisation.", OPERATOR,
                       "Informational (demo)."),
    "BE_TRANSMISSION_NOT_CERTIFIED": ("REFUSAL", "No authority channel is certified (gate G3).",
                                      "Belgium not activated for transmission.", AUTHORITY,
                                      "Submit through the authority portal; record the reference."),
    "BE_EMPLOYER_NOT_REGISTERED": ("REFUSAL", "No ACTIVE employer registration for the filing period.",
                                   "Registration missing / not approved.", SETUP, "Approve the registration."),
    "BE_DIMONA_NO_LINE": ("REFUSAL", "The employee has no ACTIVE employment line to declare.",
                          "Classification missing.", EMPLOYEE, "Record and approve the classification."),
    "BE_DIMONA_START_MISSING": ("REFUSAL", "The employment line has no contract start date.",
                                "Classification lacks the start date.", EMPLOYEE, "Record the contract start."),
    "BE_DIMONA_NOT_SENT": ("REFUSAL", "Only a transmitted Dimona IN can be cancelled.", "Cancel on a Draft.", OPERATOR,
                           "Rebuild the Draft instead."),
    "BE_NO_COMMITTED_PAYROLL": ("REFUSAL", "No committed Belgian payroll in the period.", "Runs not approved yet.",
                                OPERATOR, "Approve the period's runs first."),
    "BE_INCOME_YEAR_OPEN": ("REFUSAL", "Belcotax fiches are built after the income year closes.",
                            "Built too early.", OPERATOR, "Build after 31 December."),
    "BE_FILING_NOT_SENT": ("REFUSAL", "Only a transmitted fiche is cancelled.", "Cancel on a Draft.", OPERATOR,
                           "Rebuild the Draft instead."),
    "BE_FILING_ALREADY_SUBMITTED": ("REFUSAL", "Already submitted under another reference.", "Duplicate submission.",
                                    OPERATOR, "Use the recorded reference."),
    "BE_FILING_ALREADY_ANSWERED": ("REFUSAL", "The authority's response is recorded and immutable.",
                                   "Second response entered.", OPERATOR, "File a correction instead."),
    "BE_WHT_FREQUENCY_UNKNOWN": ("REFUSAL", "The employer's withholding frequency is not recorded (BE-013).",
                                 "Registration without the frequency.", SETUP,
                                 "Employer registration: record MONTHLY / QUARTERLY."),
    "BE_WHT_PERIOD_MISMATCH": ("REFUSAL", "The FinProf period does not match the employer frequency.",
                               "Monthly vs quarterly period.", OPERATOR, "Build the matching period."),
    "BE_ADVANCE_EXISTS": ("REFUSAL", "The month's ONSS advance is already recorded.", "Duplicate notice.", OPERATOR,
                          "Correct the existing advance instead."),
    "BE_PAYMENT_REFERENCE_REUSED": ("REFUSAL", "A bank reference is reused with another amount.", "Data entry error.",
                                    OPERATOR, "Check the bank statement; use the right reference."),
    "BE_OBLIGATION_RECONCILED": ("REFUSAL", "The obligation is reconciled.", "Payment after reconciliation.",
                                 OPERATOR, "Record a variance instead."),
    "BE_OBLIGATION_NOT_PAID": ("REFUSAL", "Only a PAID obligation is reconciled.", "Reconcile too early.", OPERATOR,
                               "Record the payment first."),
    "BE_VARIANCE_OPEN": ("REFUSAL", "Open variances block reconciliation.", "Unresolved difference.", OPERATOR,
                         "Resolve the variances (reason required)."),
}

PLAYBOOK = """## Support playbook

### Payroll blocked (preview / generate refused, or approval refused)
1. Read the code in the message or the run's preflight panel (Run detail → Belgium preflight).
2. Look the code up in the table above: the **Owner** column says who fixes it.
3. Content codes (`BE_CONTENT_PENDING`, `BE_ROW_MISSING`, `BE_TABLE_EMPTY`, `BE_EARNING_CLASS_*`): nothing the
   organisation can do; the Super Admin / Belgian specialist signs the row (four-eyes). Never edit a value to unblock.
4. Setup / employee codes: the org admin records or approves the named record (a second person approves).
5. Exceptions (kind EXCEPTION) are acknowledged with a reason before approval: one by one (**Acknowledge**), or
   ticked / **Select all exceptions** → **Acknowledge selected (N)**. That is one request, still audited per item.
   They are never paid automatically.
6. Logs: `be.calculation.blocked` and `be.run.approval_refused` events carry the code, organisation, run and employee
   ids (never names, NISS or amounts); filter by the request's correlation id.

### Filing rejected by the authority
1. Filing centre → the filing → record the authority response (REJECTED with its error codes); it is immutable.
2. Fix the cause (usually employee / employer data), rebuild: a CORRECTION version supersedes the rejected one.
3. Obligations and reconciliation follow the accepted version; open variances must be resolved with a reason.

### Dimona missing (`BE_DIMONA_IN_MISSING` at preflight)
1. Check the employee has an ACTIVE classification with a contract start date (`BE_DIMONA_NO_LINE`,
   `BE_DIMONA_START_MISSING`).
2. Filing centre → Dimona → build the IN declaration, validate, approve (second person), transmit through the
   authority portal (no certified channel yet: `BE_TRANSMISSION_NOT_CERTIFIED`), record the reference and response.
3. Re-run the preflight; approval proceeds once the Dimona IN is ACCEPTED.

### Golden certification failing (Super Admin → Belgium → Overview)
1. Open the golden check: each failing case names the expected vs computed figure and the content rows used.
2. A difference means the signed content or the authority example is wrong — never the engine silently. The
   specialist corrects the row (four-eyes) or the authority example; re-run the certification.
3. Activation stays refused until golden certification and every other gate (G1-G7) is green.

### NISS reveal requests
1. Requester (org admin): Employee → Belgian identifiers → Request reveal (reason required).
2. A **second** person approves; the requester reveals **once**. The approver can never reveal; a second reveal needs
   a new request.
3. Every step is in the identifier access log and emits `be.identifier.reveal` (state + vault / employee ids only).
4. No keys configured (dormant / staging without keys): every identifier operation refuses — by design.
"""


def discover() -> set:
    files = set(PAYROLL.glob("belgium*.py")) | set(PAYROLL.glob("be_*.py")) \
        | set((PAYROLL / "engine" / "countries").glob("belgium*.py")) \
        | set((PAYROLL / "engine" / "jurisdictions" / "belgium").glob("*.py"))
    found = set()
    for f in files:
        found |= set(_LITERAL.findall(f.read_text(encoding="utf-8")))
    return found - set(IDENTIFIERS)


def render() -> str:
    owners = {}
    for _kind, _meaning, _cause, owner, _fix in CATALOGUE.values():
        owners[owner] = owners.get(owner, 0) + 1
    lines = [
        "# Belgium (ZP-BE-ENG-001) — operations runbook",
        "",
        "For: support, payroll operators and the Super Admin team. **Generated** by `backend/scripts/"
        "belgium_ops_runbook.py` from the codes in the Belgian code — do not edit by hand; "
        "`tests/test_belgium_ops_runbook.py` fails when a code is undocumented or this file is stale.",
        "",
        "Kinds: **BLOCK** the calculation is refused · **EXCEPTION** the payslip is calculated but approval waits for "
        "an acknowledgement with a reason · **PREFLIGHT** approval is refused until fixed · **REFUSAL** an action "
        "(filing, payment, PDF) is refused · **WARNING** informational.",
        "",
        "Logs: every block / refusal / filing state / reveal step is one `zoiko.belgium` log line `be.event {...}` with "
        "the code and internal ids only (`app/modules/payroll/belgium_observability.py`).",
        "",
        f"{len(CATALOGUE)} codes. Owners: " + "; ".join(f"{o} ({n})" for o, n in sorted(owners.items())) + ".",
        "",
        "| Code | Kind | Meaning | Likely cause | Owner | How to fix |",
        "|------|------|---------|--------------|-------|------------|",
    ]
    for code in sorted(CATALOGUE):
        kind, meaning, cause, owner, fix = CATALOGUE[code]
        lines.append(f"| `{code}` | {kind} | {meaning} | {cause} | {owner} | {fix} |")
    lines += ["", "Identifiers that look like codes but are names (not operational events): "
              + ", ".join(f"`{k}` ({v})" for k, v in sorted(IDENTIFIERS.items())) + ".", "", PLAYBOOK]
    return "\n".join(lines).rstrip() + "\n"


def problems() -> list:
    found = discover()
    out = [f"undocumented code: {c}" for c in sorted(found - set(CATALOGUE))]
    out += [f"documented code no longer in the code: {c}" for c in sorted(set(CATALOGUE) - found)]
    if not RUNBOOK.exists() or RUNBOOK.read_text(encoding="utf-8") != render():
        out.append(f"{RUNBOOK.name} is out of date: run python -m scripts.belgium_ops_runbook")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    if a.check:
        bad = problems()
        print("\n".join(bad) or "runbook up to date")
        return 1 if bad else 0
    RUNBOOK.write_text(render(), encoding="utf-8", newline="\n")
    print(f"written {RUNBOOK} ({len(CATALOGUE)} codes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
