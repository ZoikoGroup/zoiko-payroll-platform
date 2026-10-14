# G5 — Hong Kong data retention and deletion policy (DRAFT for counsel and owner)

**Status:** DRAFT — Zoiko internal, internally reviewed – pending approval. **No retention period is proposed here.** Periods are a legal decision (owner decision D-2, with privacy counsel). Engineering must not invent them.

## 1. What the platform enforces today (from code)

* **Retention policy records:** per data category, with status DRAFT → APPROVED → SUPERSEDED. Each record holds `retention_years`, `end_of_retention` (DELETE or ANONYMISE), `legal_basis`, `decision_reference`, `reason`, maker and approver (`retention_service.py:299-327`).
* **A proposal is refused until D-2 (period) and D-3 (delete vs anonymise) are recorded.** Approval must be by a Super Admin other than the maker (`retention_service.py:310-321, 347-348`).
* **Eight HK categories** are defined in `hong_kong_service.py:4811-4820`. The readiness centre shows "Retention periods approved (x/8)" and blocks the purge until all 8 are approved.
* **Hard delete is refused (HTTP 409)** while any of these exist: an active legal hold; a past legal hold; statutory profile versions; or retained HK records (IRD cases, IR56G cases, work hours, average-wage snapshots, termination results, corrections) (`retention_service.py:247-269`).
* **Legal holds** need a reason. Release needs a different user and is audited, including refused attempts (`retention_service.py:183-225`).
* **No scheduled purge or anonymisation job exists.** `purge_refusal` allows a purge only for an approved category, and nothing calls it on a schedule (`retention_service.py:19, 361-367`).

## 2. Policy to be completed by counsel and owner

| Category (as defined in code) | Legal basis | Retention period | End action (DELETE / ANONYMISE) | Who runs it, how often |
|---|---|---|---|---|
| PAYROLL_RECORDS — payroll runs, payslips and calculation traces | ________ | ________ | ________ | ________ |
| MPF_RECORDS — MPF contribution records and eMPF submissions | ________ | ________ | ________ | ________ |
| IRD_RETURNS — BIR56A / IR56B / E / F / G | ________ | ________ | ________ | ________ |
| TERMINATION_RECORDS — termination statements, SP / LSP, average-wage snapshots | ________ | ________ | ________ | ________ |
| EMPLOYEE_IDENTITY — HKID / passport and statutory profile data | ________ | ________ | ________ | ________ |
| WORK_HOURS — hours-worked records (minimum wage) | ________ | ________ | ________ | ________ |
| ACCESS_LOGS — HK access events and download logs | ________ | ________ | ________ | ________ |
| CORRECTIONS — payslip corrections and their evidence | ________ | ________ | ________ | ________ |

Points counsel is asked to confirm. These are questions, not answers:
* Retention for payroll records under the Employment Ordinance, for IRD employer returns, and for MPF records.
* Whether anonymisation is acceptable in place of deletion for statistics.
* The legal-hold policy (owner decision D-9): who may place and release a hold, and the review cadence.

## 3. Engineering consequences of the choices

* Choosing DELETE or ANONYMISE with automated execution needs a new shared-platform job. Today the product can only refuse unsafe deletes.
* Until all 8 categories are APPROVED, the readiness centre shows RETENTION as BLOCKED.

## Sign-off (leave blank until signed by the named person)

Privacy counsel — Name / Role / Date / Signature: ________
Platform owner (D-2 / D-3) — Name / Role / Date / Signature: ________
