# Poland go-live runbook (ZP-PL-ENG-001)

**Who this is for:** engineering, security, payroll operations, compliance and the CTO.

Poland ships switched off. Deploying the code changes nothing for tenants:
- the Poland organisation routes answer 404;
- the rule pack is Draft, and every open value is `[PENDING G1]`;
- every Polish calculation blocks with a named reason until the official data is signed;
- filings are canonical previews only: approval is refused until the official form schemas are archived.

This runbook is the order of the steps that turn it on. Each step needs its named owner, and none is done from a developer machine against production.

The live gate state is the Super Admin Poland page's **Release gates** tab. The gate checklists are in [`release-gates/`](release-gates/README.md).

## 1. Deploy (engineering)

1. Open the PR from `venu` to `main`.
   - Before merging, fetch `main`. If it gained migrations, merge `main` into `venu` and re-parent the first Poland migration that is not on `main` onto `main`'s head, so there is one head.
   - Update `tests/test_alembic_metadata.py`, the deploy test's pending sets, `alembic/MIGRATIONS_MANIFEST.txt` and the drift tests.
2. Run the full test suite in a clean checkout with no `.env`, plus the frontend gates (`npm run build`, `npm test`, the undefined-component lint).
3. Merge. The deploy pipeline applies the additive Poland migrations in order: `1ee3bbde33bb`, `e11c2c36df17`, `e75b9219e1f8`, `e7ec6c1933b4`.
4. The backend image now installs `fonts-dejavu-core` (Polish letters in bank-export PDFs, PL-023). A host deployed without the image (systemd) needs a Unicode TTF installed too; without one, a bank PDF with Polish characters is refused, not printed wrongly.
5. Check:
   - the production `alembic_version`;
   - that `/api/payroll/poland/*` answers 404;
   - that another country's run approval, bank export and retention report still work.

## 2. Secrets (security, gate G5)

1. Put `PL_IDENTIFIER_KEYRING` (a JSON map of key version → 32-byte key) and `PL_IDENTIFIER_FINGERPRINT_KEY` in Secret Manager. The fingerprint key is **never rotated**. Neither key ever goes in a `.env` file or the repository.
2. Rehearse a rotation on a non-production copy:
   - add the next key version to the keyring;
   - run `python -m scripts.rotate_pl_identifier_keys` (dry run, writes nothing), then `--apply`.
   - The output is counts and row ids only. Any row that fails to decrypt stops the run with nothing written.
3. Production rotation is done only by the approved operator, with `--confirm-remote`.

## 3. Statutory content (G1–G4 owners)

1. **Seed the Draft pack once.** A Super Admin clicks **"Create draft pack from the specification"** on the Poland page (Signing status tab; only while no Poland pack exists; a reason is required; audited). Seeding never activates anything.
2. **Sign every value** in the signing console from the archived ZUS, KAS / Ministry of Finance, PFR (PPK) and labour-law sources. A row is signed only with a stored, hashed source reviewed by a second Super Admin. A policy the specification does not define may be signed `NOT_SUPPORTED`; the feature then stays blocked.
3. **Decide every earning-class treatment** (Earning classification tab): no `REVIEW` may remain (G2).
4. **Record the authority examples** (Release gates tab → Add example), each with its reviewed source, in the compact format `G=…;AR=…;D=…;PIT2=…;PPK=… => pit=…;zusEe=…;health=…;net=…`. Then **run the golden check**: every example must match exactly (AC-PL-02).
5. **Archive the form schemas** (G4): add each official DRA / RCA / RSA / ZUA / ZZA / ZWUA / PIT-11 / PIT-4R schema version to `poland_content.PL_FORM_SCHEMA_CATALOG` with its effective date and evidence (a code change, reviewed). Until then filings stay previews.
6. **Record the evidence** `PL-GATE-G1` … `PL-GATE-G4`.
7. **Approve, then activate.** A Super Admin who made none of the edits approves the pack. Activation is refused while anything is pending or empty.
8. **2027:** a `PL-PAYROLL-2027` pack is added only when the 2027 values (minimum wage, 30x cap, …) are sourced (decision D-3). Without it, January 2027 payroll blocks with `CONTENT_PACK_OUT_OF_DATE`.

## 4. Parallel cycles (QA + implementation, G6)

1. For at least **two legal employers**, run at least **two pay months each** in parallel with the current provider (AC-PL-03).
2. Under Compliance Centre → Parallel cycles, import the provider's figures for each PAID run. The file carries no PESEL, NIP or bank account; a file with any of them is refused whole.
3. Explain every difference, have a second person accept it, and have someone other than the importer accept each cycle. Record the signed variance report as `PL-GATE-G6`.

## 5. Sign-off and switch-on (CTO)

1. Record owner decision D-7 (`PL-DECISION-D-7`) and approve the retention periods for payroll, tax and social-insurance records under the retention policies. Record D-1 to D-6 for completeness.
2. Record `PL-GATE-G5` and `PL-GATE-G7` (this runbook, reviewed and rehearsed), plus the four `PL-SIGNOFF-*` documents.
3. Move Poland's service availability to AVAILABLE. The server refuses unless every gate and the launch-blocking decision pass.
4. **Canary first (AC-PL-08):**
   - set `PL_CANARY_ORG_IDS` to the one internal pilot organisation;
   - run its first live month end to end: preflight, approval, payment, ZUS / PIT filing previews and manual submission records, settlements and reconciliation, journal.
5. Only then set `PL_TENANT_ONBOARDING_ENABLED=True` for everyone.

## 6. Incidents

- **ZUS / e-Deklaracje rejection.**
  - A rejection is recorded with its error codes and leaves payroll unchanged.
  - Fix the cause. The next build makes a new filing version; after submission or acceptance a change is a CORRECTION. An unchanged payload is never stored twice, and a repeated submission or receipt with the same reference is the same event (PL-020).
- **Payments.**
  - A filing's acceptance never marks a liability paid. Payments are recorded by hand with their bank reference; a difference becomes a variance that only a second person can resolve, with a reason.
  - A liability that changes after a payment raises `CHANGED_AFTER_PAYMENT`.
- **Corrections.** A paid payslip is never edited (PL-018, PL-024); a retro change is a new version of the record (statement, episode, profile) and the next run recalculates.
- **Privacy breach** (a PESEL, NIP, NRS, bank account or medical pointer exposed).
  - Contain the exposure and preserve the vault access log.
  - Notify the supervisory authority (UODO) within **72 hours** of becoming aware of a notifiable breach (GDPR Art. 33).
  - Rotate the identifier keyring (section 2) if key exposure is suspected.

## Rollback (AC-PL-08)

- Remove the organisation from `PL_CANARY_ORG_IDS`, or switch `PL_TENANT_ONBOARDING_ENABLED` back to False. The Poland routes answer 404 again and no data is lost.
- Move the service availability back to PLANNED.
- A bad pack is fixed by **re-activating the prior signed pack version** for future payrolls. Committed payroll is never rewritten: every payslip keeps its frozen calculation and replays to the same hashes.
- The Poland migrations are additive. Their downgrades exist but are not needed to switch Poland off.
