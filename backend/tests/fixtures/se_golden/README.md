# Sweden golden-test fixtures (ZP-SE-ENG-001 §15)

Run through the shared harness in `app/modules/payroll/hmrc_golden_harness.py` by
`tests/test_sweden_golden.py` and by Super Admin's Test Certification console
(`run_golden_test_certification(jurisdiction_country="SE")`).

Sweden is fail-closed (no engine fallback), so every case supplies its own
`rate_map` — the same values `scripts/seed_sweden_canonical_packs.py` seeds.

## What these vectors are — and are not

Every expected figure is computed by hand from the rates the specification
states in §3 (31.42% standard, 10.21% / 0% cohorts, 20.81% youth relief up to
SEK 25,000 per month, SINK 22.5% / 20%, supplementary 30%, SLP 24.26%). They
exercise cohorts, the youth window and threshold accumulator, SINK, the 30%
path and SLP.

They are NOT the "locally reviewed reference calculations" §15 requires for a
production release, and they do not cover tax-table withholding at all —
Skatteverket's tables 29–42 are not yet entered. A PASS here satisfies only the
certification gate; activation still requires the tax tables, the Swedish
specialist review and the other §16 gates (see the Readiness tab).
