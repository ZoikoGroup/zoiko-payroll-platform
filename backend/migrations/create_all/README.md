# Create All — schema bootstrap

The standalone Payroll Platform has **no alembic**. Schema is created fresh,
in one shot, via `Base.metadata.create_all` against an **empty** database.
This directory is that bootstrap.

## When to run

| Scenario | Action |
|---|---|
| First-time setup on an empty Postgres DB | `python -m migrations.create_all.create_all` |
| Dev with no `PAYROLL_DATABASE_URL` set | same command — falls back to SQLite at `app/data/payroll_dev.sqlite3` |
| Wipe + recreate a scratch/dev DB | `python -m migrations.create_all.create_all --drop` |

`initialize_database()` in `app/database.py` already calls the same
`create_all` on app startup (`/health` / lifespan), so running this script is
optional for dev — it exists as the documented, repeatable bootstrap and for
CI/staging provisioning.

## Table inventory (created by this bootstrap)

Every table is registered by importing the model modules at the bottom of
`app/database.py`:

- **Auth / users** — `users`, `security_action_tokens`
- **Organizations** — `organizations`
- **Payroll core** — `payroll_employees`, `payroll_runs`, `payslip_items`,
  `payroll_attendance_records`, `payroll_holidays`, `payroll_contribution_rates`,
  `payroll_tax_slabs`, `payroll_company_compliance`, `payroll_compliance_documents`,
  `payroll_leave_allocations`, `payroll_leave_requests`, `payroll_activity_log`,
  `payroll_custom_field_definitions`, `payroll_update_forms`,
  `payroll_update_form_sends`, `payroll_update_form_submissions`
- **Payroll policy** — `payroll_policies`, `payroll_policy_employee_categories`,
  `payroll_policy_leave_rules`, `payroll_policy_overtime_rules`,
  `payroll_policy_integrations`
- **Payroll enterprise** — `payroll_enterprise_jurisdictions`
  (global, not org-scoped: `payroll_jurisdiction_packs`)
- **Payroll mail** — `payroll_email_settings`, `payroll_inbound_messages`,
  `payroll_inbound_attachments`
- **Super Admin** — `platform_settings`, `platform_statutory_rates`
  (global statutory rate table)

## Post-bootstrap seeds

```sh
set SETUP_KEY=...            # required
set PAYROLL_SUPER_ADMIN_EMAIL=admin@example.com
set PAYROLL_SUPER_ADMIN_PASSWORD=...
python -m scripts.seed_super_admin

python -m scripts.seed_org   # demo org + org_admin
```

## Schema changes

Any model change takes effect on the next `create_all` run **only for a
fresh/empty database**. On a DB that already has data, `create_all` is
additive (new tables/columns are created; existing columns are not altered).
There is no destructive migration — that is a deliberate trade-off for this
standalone build.
