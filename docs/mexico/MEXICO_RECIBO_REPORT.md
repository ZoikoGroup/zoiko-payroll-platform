# Mexico — Recibo de nómina v2.0 (dedicated Mexican payslip)

**Review required: Rugvedh (ZP-PRIV) before merge.** The recibo reads RFC, CURP, NSS, registro patronal and the fiscal postal code (masked in every output), and three new read routes return worker data.

**For:** the associate who pushes these commits, Rugvedh (ZP-PRIV), and the G1 owner.
**Branch:** `rugvedh` (equal to `origin/main` `6d081c9` at the start). The master prompt names `nikhil`, which stopped at 28 Oct and is behind main. Changing branch needs the associate's say, so the work stayed on `rugvedh`.
**Production at the start:** backend deploy run 42005864005 of `6d081c9`, green, 5 Nov. Repository Alembic head `a8cde2482ef0`. **No migration in this work.**

## 1. The gap that was fixed

`generate_payslip_pdf_bytes` (`backend/app/modules/payroll/service.py`) had dedicated branches for UK, and US/DE/HK/SG wording inside the default layout, but nothing for Mexico. A Mexican payslip PDF therefore used the India layout and printed "House Rent Allowance (HRA)", "LOP Deduction" and "Bank Transfer (NEFT)". It now dispatches country MX, after the FAILED / PARTIAL branches and before the default layout, to `_render_mx_payslip_pdf_bytes`.

## 2. What was built

| Step | What | Where |
|---|---|---|
| B1 | One masked **recibo view** built from the committed snapshot, the payslip's stored totals, the CFDI document row, the stored stamped XML and the payment items. The PDF, the screen and the mobile summary all read it, so they cannot disagree. | `mexico_payslip_service.py` |
| B1 | The **PDF** (reportlab, A4 portrait, one page for an ordinary payslip): the design's header, ribbon, Parties, Nómina/Periodo, Percepciones, Otros pagos, Deducciones, Resumen, employer note, Timbre fiscal and footer (renderer version and the snapshot's input hash). Navy `#14243F`, teal `#16A091`, Times headings, alternating rows. | `mexico_payslip_pdf.py`, `service._render_mx_payslip_pdf_bytes` |
| B2 | **On-screen payslip:** `PayslipStub` hands any calculated Mexican payslip to `MexicoRecibo`, which shows the same sections and labels from `GET /api/payroll/mexico/payslips/{id}/recibo`. A blocked Mexican payslip keeps the existing blocked view. | `frontend/.../PaySlips/MexicoRecibo.jsx`, `PayslipStub.jsx` |
| B3 | **Mobile summary MX24-PAY-003:** at phone width the view leads with net, period, CFDI state, payment state and the main deduction lines, in a labelled region with a spoken label ("Neto a pagar … pesos mexicanos, periodo …, CFDI …, pago …"). | `mobile_summary`, `MexicoRecibo.jsx` |
| B4 | **Duplicate MX24-PAY-010:** the same recibo re-rendered with "DUPLICADO" and its own document code. It is a read, never a new issuance. **Pay history MX24-PAY-011:** one employee's committed Mexican payslips in a pay-date range, as JSON or PDF, labelled "extracto informativo · no es un CFDI". | `generate_mx_payslip_duplicate_pdf_bytes`, `pay_history`, `render_history`, two routes |

### Where each figure comes from

| Printed | Source |
|---|---|
| Earnings lines, taxed / exempt | `result.concepts[]` (`gross`, `isr_taxable`, `isr_exempt`) |
| SAT code | earnings: the classification's `cfdi_concept_code` frozen in the snapshot; special kinds (aguinaldo, PTU, …), subsidy: the **APPROVED** system-concept mapping of the document's release (or the Active release). No approved code → "clave pendiente". |
| ISR retenido and its base | `result.isr_withheld`; base text from `tariff_period`, `isr`, `subsidy.applied`, `annual_adjustment` |
| Cuota obrera IMSS | `result.imss_employee`, `contribution_days` |
| Crédito INFONAVIT | `result.infonavit_credit`; justificante = the notice's authority reference, **masked** to its last 4 |
| Otras deducciones autorizadas | the payslip's stored `total_deductions` minus the lines above, shown only when positive; a negative value refuses |
| Totals | the payslip row's `gross_pay`, `total_deductions`, `net_pay` |
| Employer costs (information only) | `result.imss_employer`, `infonavit_employer`, `isn.amount`, `employer_total` |
| UUID, stamp time, SAT certificate | **only** the stored stamped XML (`mexico_cfdi_receipt.receipt_from_xml`) |
| Payment status | the latest `payroll_mx_payment_items` row outside a cancelled batch |

Nothing statutory is recomputed. The only arithmetic is summing the printed lines and checking them against the stored totals. A mismatch is refused, never adjusted for display.

**Two places the prompt and the code differ:**
- The prompt lists `result.net`, which doesn't exist. The net is the payslip row's stored `net_pay`, which equals `gross − total_deductions`.
- `isr_withheld` is already the tariff ISR **minus** the employment subsidy (`engine/jurisdictions/mexico/subsidy.offset`). The subsidy is therefore shown under "Otros pagos" with the note "aplicado contra el ISR … no se suma al devengado", and in the ISR base text. Adding it to earnings would double-count it and break gross − deductions = net.

## 3. States

| CFDI document (latest for the payslip) | Ribbon | Fiscal block |
|---|---|---|
| none, or not stamped (GENERATED, SUBMITTED, REJECTED, UNKNOWN, …) | `BORRADOR / NO TIMBRADO · SIN UUID · SIN SELLO SAT · NO FISCALMENTE VÁLIDO · NO ACREDITA PAGO` | NO DISPONIBLE / SIN TIMBRADO / NO DISPONIBLE / NO EMITIDOS |
| STAMPED (CANCEL_REQUESTED adds "CANCELACIÓN SOLICITADA") | `CFDI TIMBRADO · PAGO: <estado>` | UUID, stamp time and SAT certificate from the stored XML |
| STAMPED, stored XML missing | `CFDI TIMBRADO · XML TIMBRADO NO DISPONIBLE · DATOS FISCALES NO MOSTRADOS` | NO DISPONIBLE (the row's UUID is not trusted) |
| CANCELLED / REPLACED | `CFDI CANCELADO · NO ES EL RECIBO VIGENTE · SUSTITUIDO POR <uuid>` | UUID marked "(CANCELADO)"; `fiscal.current = false` |

- **Payment** is a separate phrase ("Pago: pendiente / pagado / no pagado (fallido|devuelto)").
- **Pilot and evaluation** watermarks are kept.
- **FAILED / PARTIAL** payslips keep their existing renderers. A Mexican payslip with no committed result gets the blocked document, never fabricated zeros.

**QR.** The payslip draws no QR and no seal image. The fiscal block points to the printed representation of the CFDI (W4-3b, `GET /cfdi/documents/{id}/receipt`). That receipt carries the Anexo 20 I.D QR and is still labelled "NOT AN OFFICIAL FILE" because RMF 2.7.1.7 V has no saved formation rule. Putting a QR on the payslip too would be a second, unofficial copy.

## 4. Tests

`backend/tests/test_mexico_recibo.py` (23 tests) and `backend/tests/test_payslip_pdf_country_pins.py` (7).

| Required | Test |
|---|---|
| No HRA / LOP / NEFT on an MX PDF | `test_mx_pdf_is_the_recibo_and_has_no_india_layout` |
| Every amount equals the snapshot | `test_every_amount_equals_the_snapshot` |
| MX-T013 draft shows no UUID / QR | `test_draft_has_no_uuid_seal_or_qr` |
| MX-T012 cancelled not current | `test_a_cancelled_cfdi_is_never_the_current_receipt` |
| MX-T038 masking | `test_identifiers_are_masked_everywhere` (PDF text, view JSON and summary) |
| MX-T018 employer INFONAVIT not a deduction | `test_employer_infonavit_is_never_a_deduction` |
| MX-T045 gross − deductions = net | `test_gross_minus_deductions_is_net_and_inconsistent_data_refuses` |
| MX-T043 es-MX formatting and accents | `test_es_mx_formatting_and_accents` (reads á é í ó ú and – · back out of the PDF) |
| Green "issued" from approval alone | `test_payroll_approval_alone_is_never_issued` |
| Unmasked identifiers in a shared preview | `test_identifiers_are_masked_everywhere`, `test_recibo_routes_are_org_scoped_and_masked` |
| A single opaque net figure | `test_no_single_opaque_net_figure` |
| Employer INFONAVIT as a deduction | `test_employer_infonavit_is_never_a_deduction` |
| A stamp presented as bank payment | `test_stamped_reads_the_uuid_…_keeps_payment_separate`, `test_a_settled_payment_is_shown_as_paid_and_never_as_a_stamp` |
| A fictional stamp / clickable fake QR | `test_no_fake_qr_or_seal` (no annotations, no images), `test_stamped_view_does_not_trust_the_document_row_for_the_uuid` |
| An overwritten historical issuance | `test_rendering_never_writes_or_reissues` (report, document and event counts, document status / UUID / updated_at unchanged after a render and a duplicate) |
| One page | `test_an_ordinary_recibo_is_one_page_in_every_state` |
| Other countries byte-for-byte | `test_payslip_pdf_bytes_are_pinned[UK, US, DE, HK, SG, IN, NL]`: reportlab invariant mode, SHA-256 recorded at `6d081c9` before the renderer existed, unchanged after |

Run together with the dormancy, pilot and printed-receipt tests: **208 passed**. The full suite is in §7.

## 5. Browser check

Harness: `docs/mexico/recibo-evidence/harness/` (scratch SQLite, synthetic builder and signer, the test-only mock PAC, `@example.com` users). Four organisations (draft, stamped, cancelled with a synthetic replacement UUID, pilot), each at 1280 px and 390 px. Every page loaded with no page errors and no horizontal page overflow. Screenshots inspected against the design:

| File | Shows |
|---|---|
| `draft-desktop.png`, `draft-phone.png` | draft ribbon, no UUID; phone leads with the MX24-PAY-003 summary |
| `stamped-desktop.png`, `stamped-phone.png` | "CFDI TIMBRADO · PAGO: PENDIENTE", the mock PAC's UUID from the stored XML |
| `cancelled-desktop.png`, `cancelled-phone.png` | red "CFDI CANCELADO · NO ES EL RECIBO VIGENTE · SUSTITUIDO POR …" |
| `pilot-desktop.png`, `pilot-phone.png` | pilot organisation |
| `pdf-draft.png`, `pdf-stamped.png`, `pdf-cancelled.png`, `pdf-pilot.png` | the PDFs (pilot: evaluation and pilot watermarks) |
| `pdf-duplicate.png`, `pdf-history.png` | MX24-PAY-010 and MX24-PAY-011 |

The check found and fixed four issues:
- The "•" mask glyph is not in the standard PDF fonts and vanished, so a masked RFC printed as "AB1". Masks now use `*`.
- Letter-spacing from the small-caps lines leaked into all later PDF text.
- Section headings sat too tight under the previous table.
- The two-column tables scrolled sideways on a phone; they now wrap.

## 6. Not done, and why

- **Employee self-service view.** There is none: employee logins were removed from the platform (`frontend/src/service/orgAdminService.js`). B2 therefore covers the operator's payslip view. The only employee-facing path is the Assist tool `payroll.getMyPayslips`, which returns period, net and status, with no identifiers and no lines. Building an employee login is an authorisation decision, not part of this prompt.
- **FONACOT.** Not built ("prompt 4"), so no line.
- **Rows with no SAT code** print "clave pendiente". Nothing is invented.

## 7. Production effect

| Commit | Production effect | Migration | ZP-PRIV |
|---|---|---|---|
| `Mexico Recibo B1` | Every Mexican payslip PDF (the generic `/payslips/{id}/download` and run ZIP) becomes the recibo; other countries byte-identical (pinned). Mexico is dormant in production, so no live payslip changes today. | none | **Yes**: reads identifiers (masked) |
| `Mexico Recibo B2–B4` | Three read routes on `/api/payroll/mexico` (dormant guard, payroll operator, own organisation): `GET /payslips/{id}/recibo`, `GET /payslips/{id}/recibo/duplicate`, `GET /employees/{id}/pay-history`. Route registry and privacy inventory regenerated. The shared payslip download and approval routes now list the Mexico CFDI / payment tables as reachable (call graph). The on-screen Mexican payslip is replaced. | none | **Yes**: three worker-data routes |
