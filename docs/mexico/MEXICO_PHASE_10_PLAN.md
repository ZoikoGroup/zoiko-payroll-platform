# Mexico (MX) — Phase 10 Plan: Payments, journal, privacy and retention, release gates

Spec ZP-MX-ENG-001 v1.0 §20–§22, MX-060–MX-064 · implementation plan v1.1 §13 · Phase 6 reset rule ("a RELEASED bank instruction refuses reset").

**Base.** `main` = `78bc913` (PR #117, Phase 9e). Its deploy (`39584366118`) is being verified. Production was at `c6e1a9d4f2b7` and should move to `e7a2c4f9b1d6`. Phase 9 (9a–9e) is complete in mechanics.

**Status.** Plan only. **Waiting for approval.**

## 1. What Phase 10 is — four sub-phases

| Sub-phase | Contents | Why separate |
|---|---|---|
| **10a** | **Salary payments:** payment batches from committed runs, maker-checker release, the payment file, returned payments and re-issue, and "released refuses reset" | The largest, and the one an employer touches every run. |
| **10b** | **Payroll journal:** the posting of each committed run (gross, deductions, employer cost, every authority liability kept separate, §20) to configurable accounts, exported | Independent of payments. |
| **10c** | **Privacy and retention:** Mexican identifiers (RFC, CURP, NSS, CLABE) and CFDI XML redacted in logs and errors (MX-061); the Mexico retention and legal-hold policy; the UNKNOWN-state recovery runbook (MX-062) | Touches Rugvedh's ZP-PRIV redaction, so it needs his review. |
| **10d** | **Release gates:** the G1–G8 evidence register (one folder and checklist per gate), the production activation runbook and the release checklist; the Super Admin readiness view links each gate to its evidence | Documentation and sign-off; nothing switches Mexico on. |

## 2. What is buildable now, and what is blocked

| Buildable now | Blocked until a source or decision |
|---|---|
| Batches, maker-checker, statuses (the Phase 8 lifecycle: PENDING → RELEASED → SETTLED / FAILED / UNKNOWN, retry only with confirmation), returns, re-issue, the reset rule | **The bank's SPEI file layout:** no bank format is saved (implementation plan "Open"). |
| A **Zoiko payment worklist** (CSV, labelled "not a bank file") for keying payments into online banking | **CEP / settlement confirmation:** Banxico's payment receipt; no integration. |
| The journal mapping and export (CSV) | The employer's chart of accounts: the employer configures it. |
| Identifier redaction; the retention / legal-hold mechanics | **Retention periods and the hosting / cross-border stance** (2025 privacy law): legal decisions. |
| The G1–G8 evidence structure, runbook and checklist | **Signing any gate:** needs real evidence (sources transcribed, parallel payroll run, etc.). |

## 3. Data model (one migration per sub-phase, new tables only, RLS on the new tables only)

| Sub-phase | Migration | Tables |
|---|---|---|
| 10a | `mx_payments_m12` | `payroll_mx_payment_batches`: run, file mode, status, maker / checker, released_at, file hash, idempotency key.<br>`payroll_mx_payment_items`: batch, employee, CLABE **last 4 only**, amount, status, return reason, `reissued_by_item_id`. |
| 10b | `mx_journal_m13` | `payroll_mx_journal_mappings`: employer, account per line type, version, approved_by.<br>`payroll_mx_journal_exports`: run, mapping version, file hash. |
| 10c | none | Configuration and code only. |
| 10d | none | Documentation only. |

## 4. What this does in production when merged

The same pattern as before: new, empty tables with their RLS policy, measured on PostgreSQL 17. Every route is refused while dormant. No behaviour changes for other countries. 10c changes logging for **Mexican identifier patterns only** (an additional redaction rule), and is reviewed with Rugvedh.

## 5. Decisions needed from you (recommendation first)

| # | Decision | Recommendation |
|---|---|---|
| **D1** | Order | **10a → 10b → 10c → 10d**, one PR each. |
| **D2** | Payment file without a bank layout | **Worklist mode** (as Phase 8 D1). A CSV labelled "Zoiko payment worklist — not a bank file", built on request, never stored with the full CLABE. The real SPEI layout comes later as a per-bank content seam (`MX_BANK_FILE_FORMATS`, empty: no bank file can be generated). |
| D3 | Release | A **committed** run only; maker-checker (four-eyes); a released batch refuses the run's reset (Phase 6 rule). |
| D4 | Outcome | The operator records SETTLED / FAILED / RETURNED per item, with a reference. UNKNOWN follows the Phase 8 rule (same payload reused on retry, no automatic retry). |
| D5 | Returns | A returned item is re-issued in a new batch, linked to it. The payslip is never edited. |
| D6 | Journal | The employer maps line types to their own account codes (versioned, four-eyes). The export is a CSV; nothing is posted to an ERP. Authority liabilities are never netted (§20). |
| D7 | Redaction (MX-061) | Add RFC / CURP / NSS / CLABE patterns (and CFDI XML bodies) to the ZP-PRIV redaction filter and error scrubbing. **Built with Rugvedh's review**, since it is his module. |
| D8 | Retention | The Mexico retention policy stays **"decision OPEN — nothing is deleted"** until legal decides the periods. Legal holds work now. CFDI XML is never deleted. |
| D9 | Hosting / cross-border | Documented as an open legal item in the release checklist. Not built. |
| D10 | Gates | 10d only **prepares** the evidence register and runbook. Signing a gate stays with two real Super Admins and real evidence. Nothing in Phase 10 turns Mexico on. |
