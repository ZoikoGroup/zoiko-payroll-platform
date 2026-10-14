# Migration alignment note (for venu)

**Date:** 2026-10-13 · **Branch with the change:** `feature/hk-launch-readiness` (proposed; not merged into main yet)

## What happened

Production is at Alembic revision **`b08f04497195`** (your Saudi Arabia foundation). Main stopped at `f898189cb4e3`, so a deploy of main that ran `alembic upgrade head` would have failed with *"Can't locate revision identified by 'b08f04497195'"*.

## What is now on the branch (going to main)

| Revision | File | Down revision | Status |
|---|---|---|---|
| `6b5a4c3d2e1f` | `6b5a4c3d2e1f_ch_step14_elm_payload_column.py` | `f898189cb4e3` | copied from `origin/venu`, **byte-identical** (git blob `edbd2c18537c603ed36936a4034db1df91233a73`) |
| `b08f04497195` | `b08f04497195_saudi_arabia_foundation.py` | `6b5a4c3d2e1f` | copied from `origin/venu`, **byte-identical** (git blob `1b9499d8116b8a55aa392d27dc49320e06fae30f`) |
| `8b14824fb575` | `8b14824fb575_hk_launch_readiness_controls.py` | `b08f04497195` | **new** on this branch (additive: `payroll_user_permissions`, `payroll_hk_contribution_day_disruptions`, consent / break-glass columns on `assisted_access_sessions`) |

Same revision IDs as yours, unchanged. The SA models are not on main; the SA tables and columns exist in the database but nothing on main reads them. All SA columns are nullable or defaulted, so main's inserts are unaffected.

**Not taken:** `c7d3e8f1a2b4_saudi_arabia_approval_fingerprint` (your next one). It is not in production and stays on your branch.

## What you need to do

Your next migration (`c7d3e8f1a2b4` and anything after it) must have the **current single head** as its `down_revision`:
* if this branch is merged first: `down_revision = "8b14824fb575"`;
* if yours is merged first: `8b14824fb575` is rebased onto your head instead. Tell us before merging, so only one person re-parents.

Do **not** change the IDs or contents of `6b5a4c3d2e1f` or `b08f04497195`. Production already has them.

## Commands to verify after the rebase (backend directory)

```bash
git fetch origin
git rebase origin/main                      # or merge, per team practice
python -m alembic heads                     # must print exactly ONE line, ending "(head)"
python -m alembic history -r b08f04497195:head   # b08f04497195 -> 8b14824fb575 -> c7d3e8f1a2b4 ... (no fork)
python -m pytest tests/test_alembic_metadata.py -q   # single head + revision count + branchpoints
```

To rehearse against production's schema without touching production, use a local throwaway database:

```bash
pg_dump --schema-only --no-owner --no-privileges "$PROD_READONLY_URL" > prod_schema.sql      # read-only
pg_dump --data-only -t alembic_version "$PROD_READONLY_URL" > prod_alembic_version.sql
createdb prod_rehearsal && psql prod_rehearsal -f prod_schema.sql && psql prod_rehearsal -f prod_alembic_version.sql
PAYROLL_DATABASE_URL=postgresql://localhost/prod_rehearsal python -m alembic upgrade head   # never against production
```

This rehearsal was run on 2026-10-13 for `b08f04497195`: `alembic current` = `b08f04497195 (head)`, and `upgrade head` was a no-op with exit 0. The step to `8b14824fb575` was rehearsed the same way on 2026-10-13T06:41Z: upgrade exit 0 → `8b14824fb575 (head)`; both new tables and the consent columns present; `downgrade b08f04497195` and a second `upgrade head` also clean. Re-run it right before deploy.
