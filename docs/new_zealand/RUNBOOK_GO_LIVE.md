# New Zealand go-live runbook (ZP-NZ-ENG-001)

**Who this is for:** engineering, security, payroll operations, compliance and the CTO.

New Zealand ships switched off. Deploying the code changes nothing for tenants:
- the NZ organisation routes answer 404;
- the rule pack is Draft, and every value is `[PENDING G1]`;
- every NZ calculation blocks with a named reason until the official data is signed.

This runbook is the order of the steps that turn it on. Each step needs its named owner, and none is done from a developer machine against production.

The live gate state is the Super Admin New Zealand page's **Release gates** tab. The gate checklists are in [`release-gates/`](release-gates/README.md).

## 1. Deploy (engineering)

1. Open the PR from `venu` to `main`.
   - Before merging, fetch `main`. If it gained migrations, merge `main` into `venu` and re-parent the first New Zealand migration that is not on `main` onto `main`'s head, so there is one head.
   - Update `tests/test_alembic_metadata.py`, the deploy test's pending sets, `alembic/MIGRATIONS_MANIFEST.txt` and the NZ drift tests.
2. Run the full test suite in a clean checkout with no `.env`, plus the frontend gates (`npm run build`, `npm run check:undefined`, `npm test`).
3. Merge. The deploy pipeline applies the additive NZ migrations in order: `0e697c2388bf`, `ac08988ecd3a`, `c6ea8c6c35ce`, `dd8a60634320`, `a8cde2482ef0`.
4. Check:
   - the production `alembic_version`;
   - that `/api/payroll/new-zealand/*` answers 404;
   - that another country's run approval and the retention report still work.

## 2. Secrets (security, gate G4)

1. Put `NZ_IRD_KEYRING` (a JSON map of key version → 32-byte key) and `NZ_IRD_FINGERPRINT_KEY` in Secret Manager. The fingerprint key is **never rotated**. Neither key ever goes in a `.env` file or the repository.
2. Rehearse a rotation on a non-production copy:
   - add the next key version to the keyring;
   - run `python -m scripts.rotate_nz_ird_keys` (dry run, writes nothing), then `--apply`.
   - The output is counts and row ids only. Any row that fails to decrypt stops the run with nothing written.
3. Production rotation is done only by the approved operator, with `--confirm-remote`.

## 3. Statutory content (G1–G3 owners)

1. **Seed the Draft pack once.** Either:
   - a Super Admin clicks **"Create draft pack from the specification"** on the New Zealand page (only while no NZ pack exists; a reason is required; audited); or
   - an operator runs `python -m scripts.seed_nz_canonical_packs`: a dry run first, then `--apply`. A non-local database needs the deliberate `ZOIKO_ALLOW_NONLOCAL_DB_WRITES=I_UNDERSTAND`.

   Seeding never activates anything. It refuses to re-seed a pack that has left Draft or is already being signed.
2. **Sign every value** in the signing console from the archived Inland Revenue, ACC, MBIE and Employment New Zealand sources. A row is signed only with a stored, hashed source reviewed by a second Super Admin.
3. **Fill the authority tables** (Authority tables tab):
   - PAYE method, secondary and ND rates, IETC, child-support variation codes, lump-sum and holiday-advance methods;
   - **Inland Revenue worked examples** in the compact format `F=…;C=…;G=… => payeTotal=…`;
   - national and regional public holidays.
4. **Run the golden check** (Release gates tab). Every example must match exactly.
5. **Record the evidence** `NZ-GATE-G1`, `NZ-GATE-G2` and `NZ-GATE-G3`. G3 also needs Inland Revenue's gateway certification and the certified schema in `NZ_EXPORT_SCHEMAS`. Until G3, payday filings are a JSON preview and submission is refused.
6. **Approve, then activate.** A Super Admin who made none of the edits approves the pack. Activation is refused while anything is pending or empty.

## 4. Parallel cycles (payroll operations, G5)

1. For at least **two legal employers**, run at least **two pay months each** in parallel with the current provider.
2. Under Compliance Centre → Parallel cycles, import the provider's figures for each PAID run. The file carries no IRD numbers or bank accounts; a file with either is refused whole.
3. Explain every difference, have a second person accept it, and have someone other than the importer accept each cycle.

## 5. Sign-off and switch-on (CTO)

1. Record owner decisions D-1 to D-7 (`NZ-DECISION-D-n`). For D-7, approve the retention periods for tax, wage/time and holiday/leave records under the retention policies.
2. Record `NZ-GATE-G4`, `NZ-GATE-G5` and `NZ-GATE-G6` (this runbook, reviewed and rehearsed), plus the four `NZ-SIGNOFF-*` documents.
3. Move New Zealand's service availability to AVAILABLE. The server refuses unless every gate and decision passes.
4. **Canary first (Option 3):**
   - set `NZ_CANARY_ORG_IDS` to the one internal pilot organisation;
   - run its first live payday end to end: preflight, approval, payment, filing preview, remittance, settlement matching, journal.
5. Only then set `NZ_TENANT_ONBOARDING_ENABLED=True` for everyone.

## 6. Incidents

- **Inland Revenue outage or filing rejection.**
  - A rejection is recorded with its error codes and leaves payroll unchanged.
  - Fix the cause. A changed payday makes a new filing version (or an amendment after submission), and an unchanged payload is never sent twice.
  - Track the due date shown on each filing.
- **Payment recovery.**
  - A filing's acceptance never marks anything paid. Only settlements matched by a second person do.
  - A bank recall is recorded by reversing the settlement, with a reason. The remittance then shows PART_PAID or OPEN again.
- **Corrections.**
  - A paid payslip is never edited. A correction replays the frozen calculation with corrected inputs, and a CORRECTION run carries only the differences.
  - That run makes an amendment of the original payday's filing. Its remittance delta lands in the original period and is flagged late if that period was already due.
- **Privacy breach** (an IRD number, bank account, notice content or family-violence detail exposed).
  - Contain the exposure and preserve the access log.
  - Notify the Privacy Commissioner **as soon as practicable** for a notifiable breach (Privacy Act 2020). The internal target is assessment within **72 hours**.
  - Rotate the IRD keyring (section 2) if key exposure is suspected.

## Rollback (NZ-026)

- Remove the organisation from `NZ_CANARY_ORG_IDS`, or switch `NZ_TENANT_ONBOARDING_ENABLED` back to False. The NZ routes answer 404 again and no data is lost.
- Move the service availability back to PLANNED.
- A bad pack is fixed by **re-activating the prior signed pack version**. Committed payroll is never rewritten; any money already paid is put right through corrections.
- The NZ migrations are additive. Their downgrades exist but are not needed to switch New Zealand off.
