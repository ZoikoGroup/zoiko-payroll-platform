# Ops instruction: read-only production verification (HK-PRODUCTION-VERIFICATION)

**For:** an operator who already has production database access. Claude did **not** run this against production.

## What it is

`backend/scripts/hk_production_readonly_verification.py`:
* runs fixed SELECT statements only, checked before sending;
* switches the session to `default_transaction_read_only = on` and `SET TRANSACTION READ ONLY`, so PostgreSQL refuses any write;
* prints counts, statuses and revision ids only, never personal data;
* ends with `reportSha256`.

## Rehearsal done on 2026-10-13 (not production)

* Run against a local restore of production's **schema only** (`pg_dump --schema-only` taken read-only, no data).
* Every query ran on the production schema. `transaction_read_only` reported `on`.
* An `UPDATE` in the same session was refused by PostgreSQL ("cannot execute UPDATE in a read-only transaction"), and a `DELETE` was refused by the script's guard before sending.
* Rehearsal output digest: `f5b6e376588139802b62ed96c112af4fd6a8c2a5f8ec849d638eea78f02f3fb9`. This was a schema-only copy, so the data checks were empty.

## Steps

1. On the production backend host, in the backend directory, with the normal production environment loaded:
   `python -m scripts.hk_production_readonly_verification --out hk_prod_verification_<date>.json`
2. Check that the script printed `transactionReadOnly: on`. It aborts otherwise.
3. Compare each check's rows with its `expected` text. Before launch:

| Check | Expected |
|---|---|
| `alembic_version` | `b08f04497195` |
| HK registry | PLANNED |
| HK packs | Draft / Approved, none Active |
| HK templates | Draft |
| HK workflow tables | 0 rows |
| `hk_governed_evidence` | lists what has been submitted and reviewed |

4. Upload the JSON under the tag `HK-PRODUCTION-VERIFICATION` (Super Admin → Hong Kong → Statutory Summary & Gates → Production read-only verification). A different Super Admin reviews it.
5. Also record the restore rehearsal and backup evidence named in `docs/HONG_KONG_RELEASE_EVIDENCE/HK_PRODUCTION_RESTORE_REHEARSAL.md`.

Run by — Name / Role / Date / Signature: ________
Reviewed by (a different person) — Name / Role / Date / Signature: ________
