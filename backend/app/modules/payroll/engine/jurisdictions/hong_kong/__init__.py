"""
engine/jurisdictions/hong_kong
------------------------------
Hong Kong (ZP-HK-ENG-001) jurisdiction logic that is NOT the per-payslip
calculator itself — same split as engine/jurisdictions/singapore/ and
germany/. Every module here is pure (HK-020): no database access, no live
clock, no mutable configuration. Statutory values arrive as pack rows
resolved by the service layer; facts arrive as effective-dated profile
snapshots and verified hours.

  common.py              errors, dates, year of assessment, provenance refs
  mpf.py                 MPF coverage (60-day rule, exemptions), contribution
                         holiday, relevant-income thresholds (monthly/daily)
  minimum_wage.py        SMW test split by effective date + hours-record trigger
  continuous_contract.py 4-18 (before 18 Jan 2026) and 4-week 17/68 resolver
  average_wage.py        EO 12-month average wage with disregarded periods
  entitlements.py        holiday / annual leave / sickness / maternity / paternity
  termination.py         SP / LSP with the 1 May 2025 MPF-offset transition split
  salaries_tax.py        INFORMATIONAL Salaries Tax estimate (never withholding)
  ird.py                 IRD reporting year, event deadlines, duplicate suppression
  tax_clearance.py       IR56G hold state machine
"""
