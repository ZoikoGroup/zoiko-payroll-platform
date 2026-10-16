# Mexico golden vectors (`mx_golden`)

**Status: no cases.** This directory holds no golden vectors on purpose.

- **What a case is.** Each case is a signed engineering control: input record, pay date, ISR tariff, UMA / minimum-wage version, SBC trace, every IMSS branch, the expected CFDI fields, employer-state ISN and the journal (MX-063). Every expected value is reconciled to an independent reference: SAT/PAC validation, the current SUA release, INFONAVIT, or the state return (MX-042, MX-064).
- **When cases arrive.** In Phase 5, with the Mexico engine. The first cases are F1–F5 and F7 of spec §21. Until then:
  - `service.run_golden_test_certification("MX")` reports `NO_REAL_CASES`, which is not a PASS.
  - `mexico_service.pack_golden_check` finds no case in any pack window.

  So no Mexico pack can be activated.
- **What would happen to a case added before the engine exists.** It would FAIL, because `engine/countries/mexico.py` blocks with `MX_ENGINE_NOT_IMPLEMENTED`.

Case format: the shared `hmrc_golden_harness` JSON shape (see `tests/fixtures/sa_golden/` for an example).
