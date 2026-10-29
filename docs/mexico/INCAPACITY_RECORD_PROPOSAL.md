# Proposal: the IMSS incapacity record (gap A10, Incapacidades)

> **ZP-PRIV.** **Review required: Rugvedh (ZP-PRIV) and legal before any build.** This is worker health data. **Nothing in this document is built.** There is no code, no migration and no table, and none is to be written until the questions in §9 are answered.

**For:** Rugvedh (privacy and security) and legal.
**Written:** 2026-10-28, final mile X6 (`MEXICO_FINAL_MILE_MASTER_PROMPT.md`).

## 1. Why a record is needed at all

Two things in Mexican payroll depend on IMSS-certified incapacity, and today neither has a proper input:

| Use | Where | Today |
|---|---|---|
| **CFDI `Incapacidades` node** (perception 014) | `mexico_cfdi_xml.py`: `PERCEPTION_DETAIL["014"]` | **Refused** (`R-DETAIL-NODE`, "perception 014 needs Incapacidades (S4 p. 48)"). No CFDI can carry an incapacity |
| **Contribution days per IMSS branch** (LSS Art. 31 IV; Ley INFONAVIT Art. 29) | W3-3, `mexico_rules.Lss31ContributionDays.branch_days(branch, days, absence_days, incapacity_days)` | Built and cited (S10 Art. 31, PDF p. 12; S27 Art. 29, PDF p. 17). It takes a **number of incapacity days** per period |

### Finding: the current input is not certified

`mexico_run_service._attendance_counts` counts **any attendance row with leave type "sick"** as an incapacity day. The W3-3 rule, and LSS Art. 31 IV, apply only to absences "amparadas por incapacidades médicas expedidas por el Instituto" (covered by medical incapacity certificates issued by IMSS). An uncertified sick day is an *absence* under Art. 31 I, not an incapacity under IV.

The two produce different contribution days (sickness-and-maternity keeps absence days but drops incapacity days). So today a synthetic "sick" day would be treated as certified.

It has no effect in production because Mexico is dormant, and the engine blocks a period with absences across more than one contribution segment. It must still be fixed before G2, and the record proposed here is that fix. **This is reported, not changed:** changing how sick leave is read is part of the build this proposal asks permission for.

## 2. The minimum fields

From the pinned SAT schema `backend/app/modules/payroll/mx_cfdi_schemas/sat_2026_08/nomina12.xsd` (S28, lines 609–642), node `Nomina/Incapacidades/Incapacidad`, one per incapacity in the period:

| CFDI attribute | Schema says | Needed |
|---|---|---|
| `DiasIncapacidad` | required, whole number, at least 1: "número de días enteros que el trabajador se incapacitó en el periodo" | Yes |
| `TipoIncapacidad` | required, catalogue `c_TipoIncapacidad` (the reason category) | Yes |
| `ImporteMonetario` | optional: "monto del importe monetario de la incapacidad" | Only if an employer pays an amount against it. **S4 p. 48** states when; transcription pending |

W3-3 needs only the **number of certified days falling in each contribution period**, and later (to remove `MX_ABSENCE_SEGMENT_UNKNOWN`) the **dates**, so each day can be placed in its SBC segment.

Proposed record (per worker, per certificate):

| Field | Why | Sensitivity |
|---|---|---|
| `employee_id`, `organization_id` | Owner, tenant scope | Worker link |
| `start_date`, `end_date` (or `days`) | Days per period and per segment (W3-3); `DiasIncapacidad` | Health-related: the fact of an incapacity |
| `incapacity_type` | `TipoIncapacidad`, a code from the **Active** `c_TipoIncapacidad` catalogue (never typed text) | Health-related category |
| `certificate_folio` | Proves IMSS certification (Art. 31 IV), lets an auditor match the IMSS record | IMSS reference |
| `evidence_ref` | Pointer to the scanned certificate in the evidence store, **if legal requires keeping it** (Q4) | The document itself |
| `amount` (optional) | `ImporteMonetario`, only if S4 requires it | Pay |
| `status` (RECORDED / VOIDED), `created_by`, `voided_by`, reason, timestamps | Four-eyes and audit | — |

## 3. Deliberately not stored

- **Diagnosis**, ICD codes, symptoms, treatment, medication.
- The doctor's name, notes, the clinic, and any free-text medical description.
- **Prognosis** or a return-to-work assessment.
- Any data about family members (for example maternity details beyond the type and dates).
- A free-text "reason" field. The catalogue code is the only reason.

The input screen and the API must refuse fields outside §2. The certificate scan, if kept at all (Q4), is stored as evidence and never parsed.

## 4. Legal basis (S23, Ley Federal de Protección de Datos Personales en Posesión de los Particulares, DOF 20 March 2025)

Health data is **sensitive personal data** under the 2025 Law. Zoiko does not decide the basis. Legal must answer:
- whether processing rests on a **legal obligation** of the employer (LSS contributions, CFDI issuance), or needs **express written consent**;
- which **privacy notice** (aviso de privacidad) covers it, and who issues it: Zoiko as processor (encargado), the employer as controller (responsable);
- whether Zoiko may keep the certificate scan or only its folio.

S23 is listed in `verify_mexico_sources.py` (its DOF URL) but is **not saved** in `docs/mexico/sources/` and not transcribed, so no article is cited here. Saving it is a step in `SOURCE_DOWNLOAD_RUNBOOK.md` (X7).

## 5. Access

| Role | Can |
|---|---|
| Org admin (the employer's payroll admin) | Record and void, four-eyes (a second org admin approves) |
| Payroll operator | See days and type for runs they process; not the certificate scan |
| The worker (self-service) | See their own records |
| Super Admin | **Nothing by default.** Support access only through the ZP-PRIV support-grant path, audited |
| Reports | Counts and days only. Never the type in a cross-worker report unless legal allows it (Q6) |

Route classification: `worker` / tenant-scoped, under the ZP-PRIV route registry. No `platform` route reads it.

## 6. Encryption, retention, audit, redaction

- **Encryption:** the shared database encryption at rest, plus **field-level encryption** of `incapacity_type`, the dates and the folio if Rugvedh requires it (Q7). Any scan goes in the evidence store with the CFDI XML's controls (`CFDI_XML_STORAGE_CONTRACT.md`).
- **Retention:** a new Mexico retention category, `HEALTH_INCAPACITY`, next to `mexico_service.MX_RETENTION_CATEGORIES`. It starts **BLOCKED_UNDECIDED** like the others: nothing is deleted until legal sets the period, and legal holds apply.
- **Audit:** every create, void and view of a record writes an audit row (who, when, which record), with no health detail in the row.
- **Redaction:** add the record's fields to the Mexico log and error redaction (`tests/privacy/test_redaction_mexico.py`); none in exception messages. CFDI XML already carries the node and is never logged (MX-061).
- **CFDI:** the stamped XML will contain `TipoIncapacidad` and `DiasIncapacidad`. That is a SAT requirement; the existing XML controls apply.

## 7. What a build would touch (after approval)

| Area | Files |
|---|---|
| Model and migration (new WORKER table, RLS through the d7f9 helper on that table only) | `backend/app/modules/payroll/models.py`; a new revision after the single head; `tests/test_mexico_migrations.py` pins; the deploy pending-object pins |
| Service (record / void four-eyes, catalogue-checked type, no extra fields) | a new `mexico_incapacity_service.py` |
| Run input: certified days from the record **instead of** "sick" leave | `mexico_run_service._attendance_counts`; uncertified sick days become absences (§1 finding) |
| Contribution days by segment (dates known) | `mexico_rules.Lss31ContributionDays.check` (`MX_ABSENCE_SEGMENT_UNKNOWN`) |
| CFDI node | `mexico_cfdi_input.py` (document input), `mexico_cfdi_xml.py` (remove the 014 refusal; build `Incapacidades`) |
| Routes and UI | `mexico_org_router.py`; the employee panel in the Mexico Compliance Centre; the route registry and inventory regenerated |
| Privacy | the redaction tests; the retention category; the audit |
| Tests | a new `test_mexico_incapacity.py` (four-eyes, refusal of extra fields, catalogue type, tenant isolation, no health detail in logs or reports); `test_mexico_engine_content.py` (W3-3 with certified vs uncertified days); `test_mexico_cfdi_builder.py` (the node validates against `nomina12.xsd`); PostgreSQL 17 migration tests (lock, RLS) |

## 8. What does not change

Mexico stays dormant. No other jurisdiction is touched. No real health data is used in any test (synthetic only).

## 9. Questions for Rugvedh and legal

1. **Legal basis (S23):** legal obligation, or express written consent? Who is the controller and who the processor, and which privacy notice covers it?
2. May Zoiko store the incapacity **type** at all, or only the days and the certificate folio? (The CFDI needs the type, so if it cannot be stored, it must be entered for each CFDI.)
3. Is the **certificate folio** enough evidence of IMSS certification, or must a scan be kept?
4. If a scan is kept: where, with what encryption, and who may open it?
5. **Retention period** for incapacity records and scans, and from which event.
6. Which reports may show the type (none, the employer's own payroll register, IMSS reconciliation only)?
7. Is field-level encryption required beyond encryption at rest?
8. May the worker see and correct their own records in self-service?
9. **Sick leave without an IMSS certificate** (§1 finding): confirm it is treated as an absence (Art. 31 I), not an incapacity. This is also a statutory reading for the G2 owner.
10. Does Super Admin support need any access, and through which grant?
