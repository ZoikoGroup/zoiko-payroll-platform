# G2 — Authority documents and workflows required (DRAFT for review)

**Status:** DRAFT — Zoiko internal, internally reviewed – pending approval. Not accepted evidence.
**Gate:** HK-GATE-G2 — "Current IRD XML schemas/test files and eMPF workflows pass end-to-end in approved environment" (wireframe v1.0 §16).
**Execution status:** **PENDING – requires credentials.** No IRD or eMPF test submission has been made. None can be made until Zoiko holds the official schemas, an IRD software-approval route and eMPF test credentials.

## 1. Where the product stands today (from the code)

* IRD filings are prepared in an internal canonical form (`ZOIKO-HK-IR56-INTERNAL-1`, `engine/jurisdictions/hong_kong/ird.py`). The status `IRD_SCHEMA_NOT_ARCHIVED` is shown on every HK report. No e-filing file is produced, and "FILED" only records the reference of a filing the employer made through IRD's own channel.
* The IRD forms covered are BIR56A, IR56B, IR56E, IR56F and IR56G. Their case lifecycle is DUE → PREPARED → VALIDATED → FILED → ACCEPTED / ACKNOWLEDGED / REJECTED → AMENDED, with four-eyes on FILED.
* The IRD software-approval register (`hong_kong_service.software_approval`) runs NOT_APPLIED → APPLICATION_PREPARED → APPLICATION_SUBMITTED → TEST_DATA_SUBMITTED → APPROVAL_RECEIVED. Each step needs a reviewed document tagged for it.
* eMPF batches run PREPARED → VALIDATED → SUBMITTED → ACCEPTED / PARTIAL / REJECTED → PAID → RECONCILED, with four-eyes on SUBMITTED. Member identifiers are masked, and the connection method is one of `EMPF_PORTAL_MANUAL`, `EMPF_FILE_UPLOAD` or `EMPF_API`. No certified eMPF interface exists. Outcomes are recorded from operator evidence, and an eMPF certification must be a reviewed `HK-EMPF-CERTIFICATION` document.

## 2. Documents to obtain, archive and hash

The manifest is `authority_documents.csv` (35 rows), processed by `backend/scripts/hk_archive_authority_documents.py`.

The 11 rows below are **not yet held**. Their URLs are deliberately blank: a person must find the current official file on the authority's own page. Nothing here guesses a URL.

| doc_id | Document |
|---|---|
| IRD-S2-COMPUTERISED | IRD "Submission of Employer's Return in Computerized Format" specification (wireframe S2) |
| IRD-XSD-BIR56A, -IR56B | XML schemas for the year of the first production filing |
| IRD-XSD-IR56E, -IR56F, -IR56G | Electronic formats for the event-driven forms |
| IRD-SAMPLE-FILES | IRD sample / test files and validation rules |
| IRD-SOFTWARE-APPROVAL | IRD requirements for approval of software that produces computerised returns |
| EMPF-INTERFACE-SPEC | eMPF contribution remittance file / API specification (S4) |
| EMPF-ONBOARDING | eMPF employer onboarding, test environment and credentials procedure |
| EMPF-MEMBER-ENROLMENT | eMPF member enrolment / termination data requirements |

The other 24 rows are the official sources the platform already cites (S1, S3, S5–S8 and two IRD pages outside S1–S10). Re-archiving them gives the PDF digest for the G1 worksheet column `source_document_sha256`.

### Archiving procedure

1. Download each document from the authority's site, save it beside the manifest, and put its file name in `local_file`. Alternatively, run with `--fetch` for rows that have an official https URL; only HK government and authority domains are allowed.
2. Run `python -m scripts.hk_archive_authority_documents --manifest docs/hk-evidence/G2/authority_documents.csv --archive <secure-archive-dir>`.
3. The script writes `register.csv` and `register.json` (with `registerSha256`) into the archive directory. A row that could not be hashed is listed as MISSING, and the script exits with code 1.
4. Upload each archived file to Source Evidence. Upload the register itself as part of this gate's evidence.
5. The schema hashes must be locked into the country pack before any IRD-layout template is activated (wireframe open decision 2).

The script was smoke-tested on 2026-10-13 with a throwaway file. It archived the file under its SHA-256 and reported the two unusable rows as MISSING with exit code 1. No real authority document was downloaded in this session.

## 3. What a reviewer must confirm

* The list above is complete for the launch scope (see owner decision D-1, eMPF interface, and D-7, launch-scope exclusions).
* Who in Zoiko owns obtaining the IRD software approval and the eMPF credentials.

## Sign-off (leave blank until signed by the named person)

Engineering lead — Name / Role / Date / Signature: ________
Payroll Operations — Name / Role / Date / Signature: ________
