# Mexico (MX) — Phase 10c Implementation Report: Privacy and retention

Spec ZP-MX-ENG-001 v1.0 MX-061 / MX-062 · plan `MEXICO_PHASE_10_PLAN.md` (approved 2026-10-21; this is 10c, built under D7–D9).

**Base.**
- `nikhil` = `a08f3e7` (10b), on top of `7124fc8` (10a). Neither is merged yet.
- Production is at `e7a2c4f9b1d6`.

**Alembic.** No migration. The head stays **`b3f7c1e9d5a2`**.

**Git.** Committed on `nikhil`, **not pushed**.

> **Needs Rugvedh's review before merge (D7).** Part A changes `app/core/redaction.py`, his ZP-PRIV module. The change only **adds** masking rules; nothing that was masked before is unmasked. It applies to every log line and Sentry event on the platform, not only Mexican ones.

## 1. Result

| Check | Result |
|---|---|
| Full backend suite | **7,114 passed**, 4 failed: all local-only, none Mexico (§5). |
| 10c tests | `tests/privacy/test_redaction_mexico.py` (37) and `test_mexico_retention.py` (3). All pass. The existing ZP-PRIV redaction tests (`test_redaction_federation_governance.py`) still pass. |
| Migration / routes / screens | None changed. No route registry change, and no browser check needed (nothing operator-facing changed). |

## 2. What was built

### A. Mexican identifiers in logs and error reports (MX-061, D7)

**Before**
- Free text masked NSS (11 digits) and CLABE (18 digits) only as generic long digit runs (`[NUMBER]`).
- **RFC and CURP passed through unmasked**, and so did a CFDI XML document (with every RFC, CURP, name and amount in it).
- The keys `rfc`, `curp`, `nss` and `clabe` were not sensitive.

**Now**, in `app/core/redaction.py`:

| Rule | Masks | Notes |
|---|---|---|
| CFDI document | `<cfdi:Comprobante …>…</cfdi:Comprobante>` (with an optional `<?xml?>` header) → `[CFDI XML]` | Whole, so nothing inside survives. A **truncated** document (a cut-off log line) is masked to the end. |
| Nómina complement | `<nomina12:Nomina …>…` → `[CFDI XML]` | A fragment logged on its own. |
| CURP | 18 characters → `[CURP]` | Applied before RFC. |
| RFC | personal (13) or company (12) → `[RFC]` | Case-insensitive. |
| Keys | `rfc`, `curp`, `nss`, `clabe`, `csd*`, `cfdi_xml`, `xml_body` (any casing or prefix, e.g. `employerRfc`, `employee_nss`) → `[REDACTED]` | `nss` only at a word start, so `business` is untouched. |

**Where it applies.** The same functions back the log filter (message, arguments, `extra` attributes, tracebacks) and Sentry (`before_send`, breadcrumbs). The tests prove each path with SYNTHETIC identifiers.

**What it never touches.** Codes (`MX_JOURNAL_UNBALANCED`), dates, UUIDs, journal line types and batch references are left alone (tested). API responses to an authorised user are not changed; this is about logs and error reports.

**For the reviewer (Rugvedh):**
1. **Platform-wide.** An RFC- or CURP-shaped string in any country's log is now masked. False positives only mask more.
2. **Key over-match.** `rfc` is matched as a substring, so a key such as `perfcounter` would be redacted. This is harmless.
3. **An existing over-mask.** The HKID value pattern has no closing word boundary, so it already masks part of an IMSS employer registration number (`Y1234567101` → `[HKID]101`). Harmless (over-masking), and left as is. A trailing `\b` would fix it.

### B. Retention and legal holds (D8, D9)

- **Categories.** `mexico_service.MX_RETENTION_CATEGORIES` declares the Mexican record categories in the shared retention service:
  - payroll records;
  - **CFDI** (never deleted);
  - IMSS and INFONAVIT;
  - authority filings;
  - payments and journal;
  - terminations;
  - PTU and annual adjustment;
  - employee identity.
- **No period is decided.** The owner decision `MX-D-RETENTION-PERIOD` stays OPEN, so **every category is BLOCKED_UNDECIDED, every purge is refused**, and proposing a period is refused (tested). The platform never chooses a period.
- **Employee deletion.** An employee with retained Mexican records cannot be deleted; they are deactivated instead. The records counted are CFDI documents, IMSS movements, terminations, PTU allocations, annual adjustments, salary payments and vacation records (tested with a payment).
- **Legal holds** work now:
  - the platform's ZP-PRIV holds (Org Admin → Data governance) cover every jurisdiction, Mexico included;
  - the shared retention service's Mexico holds block deletion, and their release needs a second person (tested).
- **Hosting and cross-border transfers (D9).** An open legal item in the release checklist (10d). Not built.

**For the reviewer (Rugvedh).** The ZP-PRIV `governance.retention_candidates` lists any worker who left more than 7 years ago and is not on hold. It does **not** consult a jurisdiction's retention policy, so Mexican workers (and HK / NL, all still BLOCKED_UNDECIDED) would appear. There is **no purge script in the repo** (`scripts/audit_retention.py` is referenced but absent), so nothing is deleted today. Whatever purge is written must call `retention_service.purge_refusal(country, category)` and refuse when it answers. Left unchanged here, since it is his module.

### C. UNKNOWN-state recovery runbook (MX-062)

`docs/mexico/MEXICO_UNKNOWN_STATE_RUNBOOK.md` covers, for operators and on-call:
- what can be UNKNOWN (CFDI, IMSS movement, authority liability, ISN return, SUA period, salary payment);
- how to resolve each (status query or check, then a confirmed retry with the same payload and key);
- what to do after an outage or a restore (`POST /cfdi/reconcile` first);
- what never happens (no automatic retry, no second document, filing or payment, no edit or delete, no reset).

Every route and rule in it was checked against the code.

## 3. What this does in production when merged

| Change | Production effect |
|---|---|
| Redaction | RFC- and CURP-shaped strings, CFDI XML and the new keys are masked in **all** logs and Sentry events. Nothing else changes. |
| Retention | The shared service has 8 Mexico categories, all BLOCKED_UNDECIDED (not shown on any screen yet). No Mexican employee exists in production, so the deletion guard cannot be reached. |
| Runbook | Documentation. |

**Net:** additive masking, and no behaviour change for any jurisdiction's payroll.

## 4. Not done here

- Retention periods, deletion vs anonymisation, and the hosting stance: legal decisions (D8, D9).
- A Mexico retention screen or route: the categories exist in the shared service only. **No route or screen shows them yet** (Hong Kong has its own). 10d adds them to the Super Admin readiness view.

## 5. Full suite

Five sequential chunks on scratch SQLite, run 2026-10-22: **7,114 passed**, 104 skipped, 2 xfailed, **4 failed**. **None of the 4 is Mexico's, and none comes from 10c.**

| Chunk | Result |
|---|---|
| 0 | 853 passed, 15 skipped, 3 failed |
| 1 | 2,283 passed, 1 skipped, 2 xfailed, 1 failed |
| 2 | 1,321 passed, 31 skipped (includes the 40 Phase 10c tests) |
| 3 | 1,615 passed, 51 skipped |
| 4 | 1,042 passed, 6 skipped |

The 4 failures:
- **`tests/privacy/test_route_registry.py`, 3 tests:** caused only by the 4 uncommitted `/health/version` and `/health/ready` routes in the working-tree `main.py`. CI does not have them.
- **`test_hong_kong_configuration.py::test_every_hk_configuration_row_is_governed_documented_sourced_consumed_and_exposed`:** it checks the uncommitted Hong Kong docs in the working tree. Not Mexico.

The flaky `test_deactivate_organization_response_precedes_email_send` (see the 10b report) passed this time.

## 6. Next

**10d:** the G1–G8 evidence register, the production activation runbook and the release checklist (including D9), linked from the Super Admin readiness view. Nothing switches Mexico on.
