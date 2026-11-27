# Tech debt

Known gaps that are not bugs in shipped behaviour but cost time or hide risk.
Each entry says what breaks, why, and the smallest fix we know of.

---

## TD-001 · The migration chain cannot build a database from empty

**Found:** 2026-11-27, setting up a local development database.

**What happens.** `alembic upgrade head` on an empty PostgreSQL database stops
at migration 8 of 284:

```
71d815f06d78 (add US locality, SUI, reciprocity …)
DROP INDEX uq_contribution_rate_canonical_country_state_component
psycopg.errors.UndefinedObject: index "…" does not exist
```

**Why.** The first revision, `0b624a4a7481` ("baseline: existing schema"), is a
baseline stamped over a schema that already existed when alembic was
introduced. It never creates the original tables or indexes, so any later
migration that alters them fails on an empty database. Every database the
project runs today was built with `Base.metadata.create_all()` and then
`alembic stamp` (see `scripts/be_deploy_rehearsal.py`), and the deploy
workflow's "self-healing orphan revisions" step exists partly because of it.

**Impact.**
- No one can create a fresh environment (local, staging, disaster recovery)
  with migrations alone; they must know the create_all + stamp recipe.
- A database built that way never runs the migrations' own SQL, so anything
  that exists only in migrations (RLS policies, triggers, functions, see
  TD-002) is silently missing.
- Migration code paths are exercised only on databases that were already at
  their parent revision.

**Fix options.**
1. *Squash to a real baseline (preferred):* generate one migration that
   creates the full current schema (including RLS, triggers and functions),
   mark it as the new root for fresh databases, and keep the existing chain
   for upgrading old ones (`alembic` supports this with a second base and a
   merge, or by stamping existing databases at the squash point).
2. *Minimal:* make `0b624a4a7481` create the pre-alembic schema, so the chain
   runs end to end. Requires reconstructing that schema exactly.

Add a CI job that runs `alembic upgrade head` on an empty PostgreSQL service
container, then `scripts.check_schema_drift`, so this can't regress.

---

## TD-002 · Databases built from the models have no row-level security

**Found:** 2026-11-27, same local setup.

**What happens.** A database created with `Base.metadata.create_all()` (the
only way to build one today, see TD-001) has no `zoiko_rls` policies, no
`zoiko_rls_mode()` / `zoiko_rls_tenant()` helper functions and no
`zoiko_rls_settings` table. At startup the backend logs
`[rls] Row-level security is NOT enforced …` at CRITICAL and carries on,
because `DB_RLS_REQUIRE_ENFORCED` defaults to `false`.

**Why.** RLS is created only by migration `d7f9b1c3e5a6`
(`postgres_row_level_security.py`) through raw SQL. `create_all` knows nothing
about it, and stamping past that revision skips it.

**Impact.**
- Local and test databases behave differently from production on tenant
  isolation: a query that is missing its tenant filter returns other
  organizations' rows locally instead of failing, so isolation bugs can pass
  local testing.
- Any new environment built this way (including a rebuilt staging) has no
  database-level tenant isolation until someone notices the log line.

**Fix options.**
1. *Now, per database:* call the migration's own idempotent helper after
   create_all:
   ```python
   # run from backend/; load by file path (the "alembic" package name is the
   # installed library, not this folder)
   import importlib.util
   from app.database import engine
   spec = importlib.util.spec_from_file_location(
       "rls_migration", "alembic/versions/d7f9b1c3e5a6_postgres_row_level_security.py")
   rls = importlib.util.module_from_spec(spec)
   spec.loader.exec_module(rls)
   with engine.begin() as conn:
       rls.apply_rls(conn)
   ```
   (Run it as the database owner; the app must still connect as a
   NOSUPERUSER NOBYPASSRLS role for the policies to apply.)
2. *Properly:* fold `apply_rls` into the bootstrap recipe / squashed baseline
   from TD-001, and set `DB_RLS_REQUIRE_ENFORCED=true` in every non-test
   environment so a database without RLS refuses to start instead of
   logging.
