# Mexico golden vectors (`mx_golden`)

**Status: no cases.** This directory holds no golden vectors yet, on purpose: the statutory content they would test is not transcribed (gap register §B).

- **What a case is.** Each case is a signed engineering control: input record, pay date, ISR tariff, UMA / minimum-wage version, SBC trace, every IMSS branch, the expected CFDI fields, employer-state ISN and the journal (MX-063). Every expected value is reconciled to an independent reference: SAT/PAC validation, the current SUA release, INFONAVIT, or the state return (MX-042, MX-064).
- **When cases arrive.** After the content they test is transcribed from saved sources and seeded (gap register B1–B18, item B21): ordinary, aguinaldo, PTU, vacation premium, finiquito / liquidación and annual-adjustment cases (G1 checklist), starting with F1–F5 and F7 of spec §21. Until then:
  - `service.run_golden_test_certification("MX")` reports `NO_REAL_CASES`, which is not a PASS.
  - `mexico_service.pack_golden_check` finds no case in any pack window.

  So no Mexico pack can be activated.
- **What would happen to a case added before its content exists.** It would FAIL: the engine (wired since Phase 6) blocks on the first missing content row (`MX_CONTENT_MISSING` and the other §B codes).

Case format: the shared `hmrc_golden_harness` JSON shape (see `tests/fixtures/sa_golden/` for an example). The schema test in `tests/test_mexico_engine_unreachable.py` lists the required keys.
