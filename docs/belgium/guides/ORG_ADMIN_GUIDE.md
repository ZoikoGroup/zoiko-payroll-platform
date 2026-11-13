# Belgium — organisation admin guide

For: org admins and payroll operators of an organisation that runs Belgian payroll. Belgium is open only once the
platform has activated it for your organisation. Until then, every Belgian screen answers "not open" (404).

Two places hold almost everything:
- **Payroll → Compliance → Belgium Compliance Centre** (tab), for employer setup, employee records, filings,
  obligations and parallel cycles.
- **Employees → (employee) → "Belgium statutory records" → Manage**, which opens the employee's Belgian records.

Runs are in **Payroll runs → (run)**, in the **Belgium preflight** and **Belgium salary payment** panels.

Ground rules:
- Every record is **versioned and four-eyes**. One person records with a **Reason \***, and a *second* person
  **Approve**s. Nothing is edited in place: a change is a new version from a date.
- Amounts are never typed into a payslip. The engine calculates them from signed content and your records. If
  something is missing, it blocks with a code; look the code up in [OPERATIONS_RUNBOOK.md](../OPERATIONS_RUNBOOK.md).

## 1. Employer setup (Belgium Compliance Centre)

| What | Section / labels | Notes |
|------|------------------|-------|
| Employer registration | "Employer registration (per legal employer, BE-001)": **Effective from**, **Legal name**, **Enterprise number (KBO/BCE)**, **ONSS employer category**, **Legal language**, **Mandates** | Then a second person clicks **Approve**, and **Verify** after checking it against the ONSS / KBO evidence (**Evidence reference**). An unverified registration blocks payroll (`BE_REGISTRATION_UNVERIFIED`) |
| Special contribution (the "1.60%" workforce-test status) | Same form: **Special contribution (workforce test) applies?** + **Workforce test evidence** | Choose APPLIES or NOT_APPLICABLE with evidence. Leaving it UNKNOWN blocks payroll (`BE_SPECIAL_160_UNKNOWN`). The rate itself is content, never typed here |
| Withholding declaration frequency | Same form | MONTHLY or QUARTERLY. Without it, FinProf cannot be built (`BE_WHT_FREQUENCY_UNKNOWN`) |
| Employer ONSS number | "Employer ONSS number" → **Store ONSS number** | Kept in the encrypted vault and shown masked ("On file (masked)") |
| Establishment units | "Establishment units": **Unit number**, **Region** … | Referenced by employees' classifications |
| Pay component mapping | "Pay component mappings": **Platform key** → **Belgian component** | Every platform pay item (basic, allowances…) must map to a Belgian component. An unmapped item blocks (`BE_COMPONENT_UNMAPPED`); free text never calculates |
| Joint Committee coverage | "Joint Committee coverage" | Shows which joint committees have sector content. A missing one raises `BE_SECTOR_AGREEMENT_MISSING` (an exception, not a block) |
| Substitute holidays | "Substitute holidays" | The employer's recorded substitute days |

## 2. Employee statutory records (Employees → employee → Belgium statutory records → Manage)

"Belgium statutory records" has one section per record. Each is recorded and then approved by a second person:

| Section | Key fields (UI labels) | Blocks when missing |
|---------|------------------------|---------------------|
| **Worker statutory profile** | **Category** (white-collar / manual), **ONSS worker code**, **Residency**, **Pay basis (required to calculate)** | `BE_PROFILE_MISSING` |
| **Work schedules** | **Regime**, **Hours / week**, **Employment line** | `BE_SCHEDULE_MISSING` |
| **Employment classification** | **Joint Committee**, **Function class**, **Seniority (months)**, **Contract type (required to calculate)**, **Contract start**, **Contract end (fixed term)**, establishment unit, **Joint Committee agreement** | `BE_CLASSIFICATION_MISSING`, `BE_JOINT_COMMITTEE_MISSING` |
| **Declarations** | Withholding declarations (**Dependants (count, when relevant)** …) | — (invalid ones block: `BE_DECLARATION_INVALID`) |
| **Absence episodes** | **Kind**, **From - to**, **Relapse of**, **Declared different cause** | — (no diagnosis is ever stored) |
| **Holiday certificates** | **Prior employer**, **Reference period**, **Days paid**, **Double pay** | — |

**Applicability resolver** → **Resolve** shows, for a pay date, the decision, the employment line, and every
"Blocking reasons (payroll cannot run)" and "Exceptions (stop approval)". Use it before the first run.

Pay frequency must be **Monthly** (`BE_FREQUENCY_UNSUPPORTED` otherwise).

## 3. Contracts and Dimona

A hire is declared with a **Dimona IN** before the first payroll is approved (`BE_DIMONA_IN_MISSING` at preflight).

1. The employment classification needs a **Contract start** (`BE_DIMONA_START_MISSING` otherwise).
2. Belgium Compliance Centre → **Filing centre** → **Employee (Dimona)** → **Dimona IN / update / OUT** builds the
   events from the employment lines.
3. On the filing: **Validate** → a second person **Approve**s → **Transmit**. While no authority channel is
   certified (`BE_TRANSMISSION_NOT_CERTIFIED`), submit in the authority portal and use **Record submission**. When
   the answer arrives, record it: Accepted or **Rejected**.
4. **Cancel Dimona IN** works only after transmission. A change after transmission becomes a linked correction,
   never an edit.

## 4. The national number (NISS / INSZ or BIS)

Employee → Belgium statutory records → **Manage** → "National number (NISS / INSZ) or BIS number". It is stored encrypted and shown **only
masked**, everywhere: screens, payslips and filings.

To see the digits once:
1. You click **Request reveal** and give a reason.
2. A **second** person clicks **Approve reveal**.
3. You, the requester, click **Reveal (once)**. A second reveal needs a new request; the approver can never reveal.

Every step is logged (identifier access log) without the number.

## 5. Running payroll

1. **Payroll runs** → create the run for the month, with its **pay date**: every Belgian rule is selected by it.
2. Generate the payslips. A blocked employee shows the code in the run's remarks.
3. **Belgium preflight** (run detail) lists everything that stops approval:
   - **BLOCK** items (a missing record, missing Dimona, unsigned content): fix the cause and regenerate.
   - **Exceptions** (for example `BE_BSSC_PENDING`, `BE_MINIMUM_WAGE_BREACH`): the payslip is calculated, but
     approval waits. Click **Acknowledge** with a reason, after checking it. Exceptions are never paid automatically.
4. Submit for review, then a **different** user approves. The approver can't be the preparer, or anyone who created
   a Belgian record these payslips use (four-eyes). Approval stores a fingerprint of the calculation and posts the
   ledger.
5. **Payslips**: the Belgian payslip shows bases, employee lines, net pay, the employer contributions (not
   deducted) and obligations; see [PAYSLIP_EXPLAINER.md](PAYSLIP_EXPLAINER.md). The PDF is the Belgian layout;
   organisation payslip templates do not apply to Belgium.

## 6. Payment batches (run detail → Belgium salary payment)

1. **Build payment batch**: a SEPA pain.001 batch from the approved run ("a second person must approve it").
2. A second person clicks **Approve**, then **Download file** and upload it to the bank, then **Mark submitted**.
3. After the bank statement: **Reconcile**. Rejected and returned items are shown separately.

DEMO batches are labelled "DEMO — NEVER PAID" and can never be submitted.

## 7. Filing centre and obligations (Belgium Compliance Centre)

- **Build declarations**: **Build DmfA** (quarter), **Build withholding** (FinProf, month or quarter, matching the
  employer's frequency) and **Build Belcotax fiches** (after the income year closes).
- Every filing goes **Validate** → second-person **Approve** → **Transmit** / **Record submission** → response.
  A rejected filing is fixed and rebuilt as a CORRECTION.
- **Authority calendar** shows due dates. The **Exception queue** shows what needs attention now.
- **Obligations and reconciliation**:
  - **Record ONSS advance** for the monthly advance notices;
  - **Record payment** with the bank reference;
  - **Reconcile** once paid;
  - differences open **Variances**, which must be resolved with a reason before reconciliation
    (`BE_VARIANCE_OPEN`).

## 8. Parallel cycles (release gate G4)

Before go-live, compare Zoiko's committed runs with your current payroll provider for the agreed number of months:

1. "Parallel cycles (release gate G4)" → **Independent payroll \*** (provider name), **Committed run id \***, the
   CSV and its **Employee-code column \*** → **Import and compare**.
2. Each difference above tolerance is listed. **Explain** it with a reason, or have **another user** accept it.
3. **Accept cycle (not the importer)**, done by a second person, closes the month for G4. **Withdraw** replaces a
   wrong import.

The CSV must contain employee codes and amounts only. National numbers are refused in an import.
