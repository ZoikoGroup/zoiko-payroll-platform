# Your Belgian payslip, explained

For: employees paid through Zoiko Payroll in Belgium. This is plain English; each section names the label **key**
(`be.payslip.…`) used by the payslip, so the Dutch, French and German versions can be produced from the same
structure (translators: keep the keys, translate the text).

> Your payslip never shows your national number (NISS / INSZ) in full. It shows a masked version, or "held in the
> identifier vault (not printed)". If a payslip says **DEMO — NOT FOR PAYROLL**, it is a test document and was
> never paid.

## 1. Header

`be.payslip.header` (proposed key: the header labels are not yet content-keyed)

- **Employee**, **Payslip** number and **Pay date**: which month this pays and when.
- **NISS / BIS**: masked (see above).
- **Joint committee**, **Sub-committee**, **Function class**: your sector and job classification. They decide
  which sector minimum wage and sector rules apply to you.
- **Employment line**: your contract line, usually `MAIN`.
- **Document version** (`BE-PAYSLIP-1`): the payslip layout version, for support.

## 2. Bases

`be.payslip.base.*`

The amounts each contribution or tax is calculated **on**. Belgium uses separate bases, and they are not always
equal to your gross pay:

| Line | Key | What it means |
|------|-----|---------------|
| onss employee | `be.payslip.base.onss_employee` | Pay subject to your own social security contribution |
| onss employer | `be.payslip.base.onss_employer` | Pay your employer's contributions are calculated on |
| withholding regular | `be.payslip.base.withholding_regular` | Pay subject to the regular professional withholding tax |
| holiday base | `be.payslip.base.holiday_base` | Pay that counts toward your holiday pay |
| sector min wage | `be.payslip.base.sector_min_wage` | Pay compared with your sector's minimum wage |

Manual workers' employer base can include an uplift (the "108%" rule); that is why it may differ from the employee
base.

## 3. Employee (what is deducted from your pay)

`be.payslip.employee.*`, `be.payslip.withholding.*`

| Line | Key | What it means |
|------|-----|---------------|
| Employee ONSS — base | `be.payslip.employee.onss.base` | Your social security contribution (ONSS / RSZ) on the employee base |
| Social work bonus — reduction | `be.payslip.employee.onss.work_bonus` | A reduction of that contribution for lower wages (the "work bonus") |
| Employee ONSS after reduction | `be.payslip.employee.onss.total` | What is actually deducted for social security |
| Professional withholding — regular | `be.payslip.withholding.regular` | Income tax withheld on your regular pay; an advance on your yearly tax |
| Fiscal work bonus — reduction (already in the withholding) | `be.payslip.withholding.work_bonus` | A tax reduction linked to the work bonus, **already included** in the withholding above (shown for information) |
| Professional withholding — exceptional (…) | `be.payslip.withholding.exceptional.*` | Withholding on one-off pay (for example a bonus or double holiday pay), at its own rate |

## 4. Net pay

`be.payslip.net` (proposed key: not yet content-keyed)

Gross pay minus the employee lines above. This is the amount transferred to your bank account (IBAN on file).

## 5. Employer (not deducted)

`be.payslip.employer.*`

Shown for transparency. **None of this is taken from your pay**; your employer pays it on top.

| Line | Key | What it means |
|------|-----|---------------|
| Employer ONSS — base | `be.payslip.employer.onss.base` | Your employer's basic social security contribution |
| Employer ONSS — special (wage moderation) | `be.payslip.employer.onss.wage_moderation` | The wage-moderation contribution |
| Employer ONSS — special (workforce test) | `be.payslip.employer.onss.special_workforce` | A special contribution some employers owe, depending on their workforce |
| Employer fund — special (…) | `be.payslip.employer.fund.*` | Sector or social fund contributions |
| Occupational pension — special | `be.payslip.employer.pension_special` | The special contribution on employer pension premiums |

## 6. Obligations (paid to funds)

`be.payslip.obligation.*`

Amounts your employer owes to a fund because of this payslip, for example
`be.payslip.obligation.holiday_fund` (the holiday fund that pays **manual workers'** holiday pay). They are not
deducted from you.

## 7. Questions

- **Holiday pay as a manual worker** is paid by the holiday fund, not on this payslip.
- **An amount looks wrong?** Ask your HR or payroll team. Corrections are made as a separate correction payslip
  that refers to this one; a payslip is never changed after approval.
- **Your annual tax form (281.10 / Belcotax)** sums the withholding shown on your payslips for the year.
