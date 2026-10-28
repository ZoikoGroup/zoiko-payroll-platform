# Mexico configuration audit (final mile X8)

**For:** the release owner, the gate owners and Rugvedh (ZP-PRIV).
**Written:** 2026-10-28.
**Scope:** spec §11 panels A–H, the §14 Social Security Center cards, and the X1–X5 additions. For each item: where it is configured, who can change it, four-eyes, effective dating, and whether anything statutory can change outside a governed path.

The evidence (file:line) was gathered by a read-only code trace on 2026-10-28. The spot checks and fixes below were made against the code.

- **Abbreviations:** SA = Super Admin; OA = org admin; PO = payroll operator.
- **Route prefixes:** `/api/super-admin/compliance/mexico` (`mexico_router.py`) and `/api/payroll/mexico` (`mexico_org_router.py`, dormancy-guarded).

## Platform (Super Admin)

| Item | Where | Who | Four-eyes | Effective-dated | Outside a governed path? |
|---|---|---|---|---|---|
| National Mexico packs | Generic pack screen; status / approve routes (super_admin router). Rows only from `seed_mexico_canonical_packs.py` | SA | Yes: self-approval refused; the approver cannot activate; approval needs QA plus content, evidence and VERIFIED checks | Yes (effective_from / to, overlap guard) | Generic editor and hotfix refused (W5-2). **Row move fixed in X8 (finding 1).** Retiring an Active pack is single-person → **D-27** |
| State ISN packs (CDMX) | Same as above | SA | Same | Same | Same |
| Earning classifications | `POST /earning-classifications`, `/approve`, `/archive` | SA | Approve: yes. Archive: **no** → **D-27** | Yes (the prior version is superseded the day before) | None |
| CFDI catalog releases, entries and system concepts | `/cfdi-releases…`, `/cfdi-system-concepts…` | SA | Release approve: the creator was refused, **and since X8 any entry author (finding 4)**. Concepts: yes. Activate: always refused (Phase 7 PAC validation) | Entries valid_from / to | None. Entries are frozen once a release leaves Draft |
| Mexico report templates | Generic template routes; `/report-templates/coverage`, `/compare`, `/sandbox-preview` (X3) | SA | The last editor could not approve; **since X8 no editor of the version can approve (finding 3)**. Activation gate: G1–G8, Active pack, proven fields | reporting_year | None |
| Source manifest (VERIFIED) | `scripts/verify_mexico_sources.py verify` only | Repository committer | Code review of the CSV change | — | `set` refuses VERIFIED; a hand-added log row is caught only by review (`SOURCE_DOWNLOAD_RUNBOOK.md`) |
| Release-gate and decision evidence (MX-GATE-Gn, MX-DECISION-…) | Sources tab (generic Source Evidence) | SA | The reviewer must differ from the creator; SIGNED needs a file. **Since X8 a reviewed file is never replaced, and review needs an uploaded file (finding 2)** | — | Fixed (finding 2) |
| Decision register (X1) | `/decisions…` | SA | Yes | Versioned | None. An approved decision changes no calculation |
| Pilot grants, onboarding pause, master copies | `/pilot-grants…`, `/onboarding-pause…`, `/master-copies…` | SA | Yes (revoke is single-person by design: an immediate stop) | Grants expire | None |
| Mexico general availability (service registry) | `POST /super-admin/compliance/jurisdictions/MX/service-registry` | SA | **No** → **D-26** | — | Gated: G1–G8 SIGNED, Q9 recorded, identity key set. No UI by design until D-26 |
| Kill switch, expiry window, identity key | Environment (`app/config.py`) | Deployer | — | — | Not settable through the platform-settings table |
| PAC adapters, CSD custody providers, XML store (X5) | Code only (empty in `app/`) | Code review | — | — | None |
| CSD expiry alerts (X5) | Employer tab | SA (read-only) | — | `on` date | Read-only |

## Organisation (panels A–H, §14)

| Item | Where | Who | Four-eyes | Effective-dated | Notes |
|---|---|---|---|---|---|
| A/B employer profile and versions | `/employers`, `/employers/{id}/versions` | OA | No → **D-28** | Yes | — |
| Establishments | `/employers/{id}/establishments`, `/establishments/{id}/deactivate` | OA | No → D-28 | **No** (active flag) → D-28 | Zone derived from content |
| IMSS registrations; risk premiums | `/imss-registrations…`, `/risk-premiums/{id}/approve` | OA | Premiums: yes. Registrations: no → D-28 | Yes (overlap check) | — |
| D INFONAVIT operating model | `PUT /imss-registrations/{id}/infonavit` | OA | No → D-28 | **No** (overwritten in place) → D-28 | — |
| E state ISN registrations | `/employers/{id}/isn-registrations`, `/isn-registrations/{id}/close` | OA | No → D-28 | Yes | Only in-scope states |
| F/G labour policy | `/labor-policies…`, `/activate` | OA | No → D-28 | Yes | Activation refused unless the floor check passes |
| Credential references and public certificates | `/credentials…` | OA | No → D-28 | validTo stored | Secret references only; rotation keeps history |
| H readiness | `GET /readiness` | PO | — | `on` date | Read-only |
| §14 movements, SUA, liabilities, ISN returns | `/authorities/…` | OA | Yes for accept / approve / reconcile | period_key | Confirm-retry needs a prior status query |
| Journal mappings; payment batches; parallel differences; hours; opening balances | `/journal…`, `/payment-batches…`, `/parallel…`, `/hours…`, `/opening-balances…` | OA | Yes (approve / release / accept) | — | — |

## Findings and what was done

| # | Finding | Kind | Done |
|---|---|---|---|
| 1 | **A row of an Active Mexico pack could be moved into another country's editable pack and changed.** The generic slab and rate editors (`upsert_canonical_tax_slab` / `_contribution_rate`) looked up the row by id and checked only the *target* pack. Not re-checked until the next Mexico activation | Statutory value outside a governed path | **Fixed.** `_existing_row_pack` checks the row's current pack first and refuses a Mexico row (`service.py`). The same hole exists for **every other country**: reported, not changed (zero-behaviour-change rule) |
| 2 | Mexico gate / decision evidence was not governed evidence: the file could be replaced after review, and the gate stayed SIGNED on a file the reviewer never saw | Governance | **Fixed.** `_GOVERNED_EVIDENCE_PREFIXES["MX"] = ("MX-GATE-G", "MX-DECISION-")`; review refuses without an upload; upload refuses after review (as HK) |
| 3 | An earlier editor of a Mexico template version could approve it (only the last editor was refused) | Four-eyes | **Fixed.** MX added to `_ANY_EDITOR_APPROVAL_REFUSED_COUNTRIES` (as HK) |
| 4 | A Super Admin who added CFDI catalog entries could approve their own release | Four-eyes | **Fixed.** `transition_release` refuses any entry author (from the audit rows) |
| 5 | General availability is single-person | Policy | **D-26** |
| 6 | Retiring an Active pack, or archiving an Active earning classification, is single-person | Policy | **D-27** |
| 7 | Organisation-side configuration has no four-eyes; establishments and the INFONAVIT model are not effective-dated | Policy | **D-28** |
| 8 | An org payroll operator can create or activate *policy* packs with country MX | Finding | **No effect on Mexico:** no Mexico module or engine file reads policy packs or `policy_defaults` (searched 2026-10-28). Shared behaviour; reported only |
| 9 | Four-eyes checks pass when the maker id is NULL (system-created rows) | Finding | By design for system rows; reported |
| 10 | The UNKNOWN-state runbook tells an org admin to call `POST /cfdi/reconcile`, but no screen did | UI wiring | **Fixed.** "Reconcile after restore" on the run's CFDI stage, behind a confirmation |
| 11 | The Readiness tab did not say that a reviewed evidence file is never replaced | UI text | **Fixed** |
| 12 | Master-copy propose / approve routes are live, but the UI only lists copies and a comment calls them "retired" | Inconsistency | Reported, not changed: whether the routes should be removed or the UI restored is for the release owner |
| 13 | Pack status changes send no reason from the UI (the API accepts one) | Shared UI | Reported (shared screen, every country) |
