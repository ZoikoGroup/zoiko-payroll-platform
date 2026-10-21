# Test data lineage (control D09)

Status: engineering complete, awaiting review. The restore drill that proves the production-to-non-production
block on real infrastructure is awaiting Infrastructure owner proof (HP-02).

## 1. Sources of test data

| Source | Used by | Content | Personal data |
|---|---|---|---|
| `backend/tests/privacy/conftest.py` | Privacy suite (T01-T12, D, E, F tests) | Tenants PRIVA / PRIVB, workers A1, A2, B1, personas SA, SP, APP, PS2, TA, TB, PA, EA; emails on `*.example`; phone `+440000000000` | Synthetic only |
| `backend/tests/conftest.py` | Whole backend suite | Isolated in-memory SQLite per test; fixture users and orgs | Synthetic only |
| `backend/app/core/synthetic.py` | Generator and scanner | Value factories and real-checksum validators | Synthetic by construction |
| `backend/scripts/generate_synthetic_data.py` | Local / staging seeding | Tenants `SYN001..`, workers per tenant; idempotent; refuses production and non-local databases (`scripts/_local_db_guard.py`) | Synthetic only |
| `backend/scripts/seed_org.py`, `seed_super_admin.py`, plan / price / jurisdiction seeds | Local / demo setup | Organizations and admins (`*.test` in examples), statutory reference data | No worker data |

## 2. Synthetic identifier rules (`app/core/synthetic.py`)

Every identifier is shaped like a real one but fails the real check, so it can never belong to a person and
the CI scanner can tell it apart from a leaked value.

| Identifier | Rule |
|---|---|
| Email | Reserved domains only (`example.com`, `*.example`, `*.test`) |
| IBAN | Check digits `00` (always fail ISO 13616 mod-97) |
| Dutch BSN | Fails the 11-proof |
| US SSN | Area `000` (never issued) |
| UK NINO | Prefix `QQ` (never issued) |
| Indian PAN | Invalid holder-type character (4th letter `X`) |
| Phone | Non-routable placeholder numbers |

## 3. Non-production restore guard (`backend/app/core/nonprod_guard.py`)

| Rule | Behaviour |
|---|---|
| Production marks its data | At startup, an environment named `production` / `prod` (`ENVIRONMENT` or `APP_ENV`) stamps `platform_settings.data_origin = production` |
| Non-production refuses production-origin data | Any named non-production environment (staging, test, qa, demo, uat, ...) refuses to start on a database stamped `production` unless `data_deidentified_at` is set. Local development (`development`, `dev`, `local`, unset) logs CRITICAL instead |
| Restore tooling | `assert_safe_restore(source_origin, target_env, deidentified)` refuses a production-origin copy into non-production without de-identification |
| De-identification | `backend/scripts/deidentify_database.py --confirm-nonprod-copy` on the restored copy: replaces personal / secret string columns, empties worker JSON columns, kills credentials, empties audit tables, stamps `data_deidentified_at` |

Preconditions and limits (review items):
- The guard only works if production runs with `ENVIRONMENT=production` (or `prod`); otherwise the origin stamp is never written.
- A dump taken before the first stamped startup carries no marker.
- De-identification keeps numeric pay values and does not touch text/XML columns whose names do not match
  the personal-field pattern (for example statutory filing payloads) or object-storage files. Treat a
  de-identified copy as still sensitive.

## 4. CI scan (`backend/scripts/scan_test_data.py`)

Scans fixtures, test data, dumps and scripts for: IBANs with valid check digits, Luhn-valid card numbers
(published processor test cards allowed), 11-proof-valid BSNs, issued-prefix NINOs, valid PANs, consumer-provider
email addresses, and secrets (live payment keys, webhook signing secrets, cloud keys, private keys). Existing
findings live in `docs/privacy/test_data_scan_baseline.json` as a ratchet that may only shrink.

## 5. Rules for dumps and copies

1. Never restore a production backup or dump into any non-production environment without running
   `scripts/deidentify_database.py` on the isolated copy first, inside the production region.
2. Restore drills use `deploy/scripts/restore_drill.sh` into an isolated drill database; the script
   refuses the production URL / host and de-identifies non-production targets.
3. No dump, `.sql`, `.sqlite`, log or export file is committed to the repository. The scanner and code review enforce this.
4. Local `.env` files must not point at a shared or production database (`scripts/_local_db_guard.py`
   documents that the default `.env` targeted a shared remote Postgres - developers must override it).
5. Bug reproduction uses synthetic data recreated from the shape of the problem, never a copy of a tenant's records.

## 6. Tests

| Test | Status |
|---|---|
| `backend/tests/privacy/test_nonprod_data.py` | Referenced by the register; not present in the repo at time of writing |
| CI step running `scripts/scan_test_data.py` | To be confirmed in the privacy-isolation job (not present in `backend-deploy.yml` at time of writing) |

## Sign-off

| Role | Name | Signature | Date (UTC) |
|---|---|---|---|
| Platform Engineering owner | | | |
| Infrastructure owner (restore drill, HP-02) | | | |
| Independent reviewer | | | |
