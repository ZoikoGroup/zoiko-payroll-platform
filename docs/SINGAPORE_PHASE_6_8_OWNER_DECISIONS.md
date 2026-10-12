# Singapore Payroll — Phase 6.8 Owner Decision Matrix

- **Date:** 2026-09-28. Branch `nikhil` @ `83601eb`, uncommitted.
- **Rule:** engineering documents the options; **the product / compliance owner decides**. No option below has been
  chosen or implemented. Current behaviour is left exactly as it is until a decision is recorded.

## Decision 1 — G3 submission mode
**Current state:**
- IR8A original extract + manual myTax Portal filing lifecycle.
- Phase 6.7 acknowledged-year guard.
- Phase 6.8 Revision / Amendment (manual myTax Portal "Modify previously submitted data").
- AIS-API 2.0 **not implemented**.

| | A. Export-only / manual IRAS submission | B. AIS API 2.0 later | C. Both |
|---|---|---|---|
| Engineering impact | None beyond Phase 6.8 (originals, revisions, amendments already built) | New integration phase: payload builder per the IRAS AIS-API 2.0 specification, submission client, validation-error and acknowledgement handling, retries / idempotency | B, plus keep A as the fallback route |
| External dependency | IRAS validation of the YA2027 field mapping; real acknowledgements | IRAS APEX onboarding; IRAS sandbox; Corppass authorisation per employer / tax agent | Both |
| Operational impact | Operators key or upload in myTax Portal (200 records per submission) and record the IRAS reference in Zoiko (maker-checker) | Direct submission; operators handle IRAS validation responses | Choose the route per employer |
| Security requirements | Existing: masking, tenant isolation, distinct operator, audit | Credentials and certificates in a secrets store (never in code or DB clear text), key rotation, outbound allow-listing, audit of every API call | Both |
| Credentials / certificates | None | IRAS APEX application credentials / certificates; Corppass | Both |
| Still blocked | IRAS acknowledgement evidence (G3 §J.3) | Everything in the row above until onboarding | Both |

## Decision 2 — Hotfix policy (Singapore)
**Current state:**
- Emergency hotfix path with every Singapore evidence gate enforced.
- Atomic record (6.6); refusals audited (6.5).
- The reviewer must differ from the activator, and a completed review is final (6.6, Singapore).

| | A. Keep current | B. Prohibit for Singapore | C. Allow with mandatory independent follow-up |
|---|---|---|---|
| Technical | No change | One country check in `activate_jurisdiction_pack_hotfix` (refusal audited) | New: block further Singapore pack / template activations while an unreviewed Singapore hotfix exists; optional review deadline |
| Audit | Hotfix record + status audit + distinct review | Refusals audited | Adds enforcement evidence |
| Operational | A lone Super Admin can act in an emergency | Two Super Admins always needed | Emergency allowed; follow-up forced |
| Maker-checker | Deferred to a distinct review | Up-front, always | Deferred, enforced |
| Risk | An open review has no enforcement window | Slower emergency fix | Design effort; must not deadlock a needed follow-up fix |

## Decision 3 — Universal scope of the Singapore-only controls
- **Singapore only today:**
  - refused-action audit (6.5);
  - Approve-step self-approval refusal (6.5);
  - distinct hotfix reviewer and final review (6.6);
  - IR8A acknowledged-year guard (6.7).
- **All countries already:** hotfix atomicity (6.6) and the report-template lifecycle (5.8/6.3).

| | A. Singapore only (current) | B. All jurisdictions |
|---|---|---|
| Change | None | Constants `_REFUSAL_AUDIT_COUNTRIES`, `_SELF_APPROVAL_REFUSED_COUNTRIES`, `_HOTFIX_DISTINCT_REVIEWER_COUNTRIES` widened |
| Effect on other countries | None | Refusals audited everywhere; editors can't approve their own packs; single-Super-Admin countries could not close hotfix reviews (operational deadlock) |
| Tests | Green | Needs a cross-jurisdiction re-validation. Phase 6.0 showed a universal approver≠activator rule broke 52 Germany/shared tests; each widening must be re-proven |

## Decision 4 — Deploy script (engineering confirmation, not a business choice)
- **Status:** `deploy_migrate_safety.patch` is **ready for release-line integration**.
  - It is still absent from origin main/venu (blob `21929e8`, unchanged) and applies cleanly.
  - Its 9 tests pass against the release-line head, including the Phase 6.8 migration (the test replica now also
    omits `sgp_ir8a_modifications`, like the shared DB).
- **No remaining defect was found; the script was not rewritten.**
- **Owner action:** apply it at the merge (see the integration manifest).
