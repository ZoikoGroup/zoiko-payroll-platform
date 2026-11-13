# Belgium (ZP-BE-ENG-001) — staging rehearsal with the DEMO pack

For: the QA / product person who clicks through Belgium on **staging** before anyone talks about activation.
Everything here uses the `BE-DEMO-2026` pack, labelled "DEMO — NOT FOR PAYROLL". The figures are AI-drafted
placeholders and are not Belgian law. Nothing is paid, and nothing is transmitted to any authority.

> **Never on production.** The demo is refused when `ENVIRONMENT`/`APP_ENV` is production / prod / live (or unset
> with DEBUG off), and the real `BE-PAYROLL-2026` pack is never touched.

## 0. Prerequisites (staging only)

| What | Value / action |
|------|----------------|
| Environment name | `ENVIRONMENT=staging` (anything but production / prod / live) |
| Demo switch | `BE_DEMO_PACKS_ENABLED=true` |
| Identifier keys (staging-only, never production keys) | `BE_IDENTIFIER_KEYRING={"1": "<64 hex chars>"}` and `BE_IDENTIFIER_FINGERPRINT_KEY=<64 hex chars>`. Generate fresh ones with `python -c "import secrets; print(secrets.token_hex(32))"`. Without them, the NISS steps refuse (fail closed) |
| Two staff users | Two **existing, different** staging user ids: preparer A and approver B. The seed script creates no accounts. For the click-through both must be able to sign in to the demo organisation (§1.3) |
| Database | The seed script refuses a non-local database (`scripts/_local_db_guard.py`). Run it on the staging host if its database is local; otherwise the staging DB owner decides how to run it |

## 1. Seed the demo

1. On the staging backend host (from `backend/`, venv active):

   ```bash
   BE_DEMO_PACKS_ENABLED=true ENVIRONMENT=staging \
     python -m scripts.seed_belgium_demo --preparer <A> --approver <B>
   ```

   Expected output: `DEMO seeded: {... 'pack': 'BE-DEMO-2026', 'organizationId': <ID>, 'status': 'Approved', 'demo': True, ...}`
   and `Add to the environment: BE_DEMO_ORG_IDS=<ID> (and BE_CANARY_ORG_IDS=<ID> ...)`.
   The script creates:
   - the `BE-DEMO` organisation as an EVALUATION workspace, so its screens open without a plan;
   - two demo employees, a white-collar and a manual worker;
   - one approved September 2026 demo run with two payslips;
   - a DRAFT payment batch;
   - Dimona and DmfA drafts.

   Running it again is safe: the pack is idempotent and the organisation is reused.
2. Add to the **staging** environment and restart the backend: `BE_DEMO_ORG_IDS=<ID>` and `BE_CANARY_ORG_IDS=<ID>`.
   The canary list opens the Belgium screens for that organisation only.
3. Give A and B access to the demo organisation through staging's normal user administration. This is an operator
   decision; the script never does it.

## 2. Click-through script

Sign in as **A** unless the step says **B**. "Expected" is what must happen. Anything else is a finding.

| # | Area | Do | Expected |
|---|------|----|----------|
| 1 | Org setup | Payroll → Compliance → **Belgium** tab | The Belgium Compliance Centre loads. The employer registration shows the demo legal employer as ACTIVE / VERIFIED (labelled DEMO) |
| 2 | Org setup | Open employer registration, mandates, component mappings | Records are shown read-only with their four-eyes history (recorded by A, approved by B). The ONSS number shows "On file (masked)" or "Missing", never digits |
| 3 | Statutory records | Employees → "DEMO White-collar" → Belgium records | Worker profile, work schedule and employment classification (MAIN line, joint committee 200) are ACTIVE. Every change shows who recorded it and who approved it |
| 4 | Statutory records | As A, record a new work-schedule version and try to approve it yourself | Self-approval is refused. Sign in as **B** and approve it: it becomes ACTIVE, and the previous version is closed, not overwritten |
| 5 | NISS | As A, put a synthetic NISS on file for the white-collar employee (use a test value from QA, never a real person's) | The response and the screen show only the masked form (no digits) |
| 6 | NISS reveal (four-eyes) | A: **Request reveal** (reason required) → B: **Approve** → A: **Reveal** once | The digits are shown once, to A only. A second reveal is refused. B cannot reveal A's request. Each step appears in the access log. A cannot approve their own request |
| 7 | Preview | Payroll runs → new run for the demo organisation, September 2026, both employees → **Preview** | Belgian lines appear (ONSS employee, work bonus, withholding, net). Preflight shows `BE_DEMO_DIMONA_SIMULATED` (a demo-only note) and no blocking reason. The frontend computes nothing; every amount comes from the engine |
| 8 | Approve | Submit for review (A) → approve (**B**) | A cannot approve their own run. B's approval records the Belgian approval fingerprint, and the run becomes Approved |
| 9 | Payslip view | Open a payslip from the demo run | The Belgian breakdown shows bases, employee lines, net, employer composition and obligations. The NISS / BIS appears masked or as "held in the identifier vault". "DEMO — NOT FOR PAYROLL" is visible |
| 10 | Payslip PDF | **Download PDF** (single) and the run's **Download all** ZIP | Every page carries the diagonal "DEMO — NOT FOR PAYROLL" watermark, plus the evaluation watermark. The content is the Belgian layout (document version BE-PAYSLIP-1, joint committee, bases, lines). No NISS digits appear anywhere. An organisation payslip template never applies to Belgium |
| 11 | Payslip templates | Settings → Payslip templates → create or assign a template for **BE** | Refused: "Belgian payslips use the Belgian statutory payslip layout … templates do not apply to Belgium". An "All countries" template still leaves the Belgian payslips in the Belgian layout |
| 12 | Payment batch | Run → Belgium payment panel | The DRAFT batch is labelled DEMO. B may approve it. **Submit**, **Download file** and **Record bank result** are all refused ("never paid"). It is never released |
| 13 | Dimona / DmfA | Compliance → Belgium → **Filing centre** | Dimona IN events and the DmfA quarter are DRAFT and labelled DEMO, and each rendition starts with "DEMO — NOT FOR PAYROLL". Recording a submission is refused (`BE_DEMO_FILING`). Nothing is transmitted |
| 14 | Filing centre | Obligations / reconciliation view | Obligations are listed from the demo month. Variances are shown, never auto-cleared |
| 15 | Super Admin overview | Sign in as a Super Admin → Belgium → **Overview** | The real `BE-PAYROLL-2026` (if seeded) is Draft with its rows unsigned. `BE-DEMO-2026` is labelled DEMO and is **not** offered for activation or assignment. The G1–G7 release gates are all red and are computed, not editable. The registry row stays PLANNED |
| 16 | Super Admin guard | Try to activate or assign `BE-DEMO-2026` to a non-demo organisation | Refused ("only a demo organisation (BE_DEMO_ORG_IDS) may use it") |
| 17 | Dormancy | Sign in as an admin of any **other** staging organisation → Belgium screens or `/api/payroll/belgium/...` | 404 / not shown |

Record each step as PASS / FINDING with a screenshot. Inspect the screenshots, not only the HTTP status.

## 3. Turning the demo off

1. Remove `BE_DEMO_PACKS_ENABLED`, `BE_DEMO_ORG_IDS` and `BE_CANARY_ORG_IDS` from the staging environment, and
   restart. Effects:
   - the demo organisation's Belgian screens answer 404;
   - the demo pack can no longer be used by anyone (`test_switching_demo_off_blocks_the_demo_organisation_too`);
   - existing demo payslip PDFs keep their DEMO watermark, because it is driven by the pack version in the frozen
     snapshot.
2. Remove the staging identifier keys if they were added only for this rehearsal. Vault rows written with them then
   become unreadable, by design.

## 4. Cleaning up demo data

Preferred: restore staging from its pre-rehearsal backup.

Otherwise, keep the rows and retire the organisation:
- deactivate the `BE-DEMO` organisation through staging's normal administration (`is_active = false`);
- leave its rows in place. They are labelled DEMO, belong only to that organisation, can't be paid or transmitted,
  and are unusable once the demo switch is off.

To see what exists first (read-only):

```sql
SELECT id, organization_name, workspace_type, is_active FROM organizations WHERE organization_code = 'BE-DEMO';
SELECT pack_id, version, status FROM payroll_jurisdiction_packs WHERE pack_id LIKE 'BE-DEMO-%';
SELECT id, period_label, status FROM payroll_runs WHERE organization_id = <ID>;
SELECT string_agg(format('SELECT %L AS t, count(*) FROM %I WHERE organization_id = <ID>', table_name, table_name),
                  ' UNION ALL ')
  FROM information_schema.columns
 WHERE table_schema = 'public' AND table_name LIKE 'payroll\_be\_%' AND column_name = 'organization_id';
```

A row-level delete is deliberately not scripted here, because foreign keys span many shared tables. If staging
needs the rows physically gone, restore the backup.
