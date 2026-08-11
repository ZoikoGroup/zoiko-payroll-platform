# Alembic — schema migrations

Use this for any schema change to a database that already has data
(including the live database). For standing up a brand-new **empty**
database, `migrations/create_all` is still the right tool — see its own
README.

`env.py` connects using the app's own engine (`app.database.engine`), so it
always resolves `PAYROLL_DATABASE_URL` from `.env` exactly the way the app
itself does (including the sqlite dev fallback when unset). There is nothing
to configure per-environment — running `alembic` commands from `backend/`
already targets whichever database that environment's `.env` points at.

## Workflow for a schema change

1. Change the model(s) in `app/modules/*/models.py` as usual.
2. Generate a migration from the diff:
   ```sh
   alembic revision --autogenerate -m "add foo column to bar"
   ```
3. **Read the generated file in `alembic/versions/` before running it.**
   Autogenerate is a starting point, not a guarantee — it can miss data
   migrations, column renames (sees them as drop+add), and check constraints.
4. Apply it:
   ```sh
   alembic upgrade head
   ```
5. Commit the generated migration file alongside the model change, in the
   same PR — a model change without its migration is exactly the bug this
   setup exists to prevent.

## Other common commands

```sh
alembic current          # what revision is this database at
alembic history          # full migration history
alembic check            # does the DB match the models right now? (used to
                          # validate the baseline — safe to run any time)
alembic downgrade -1     # roll back one migration
```

## Notes

- The `playing_with_neon` table is excluded from autogenerate/check —
  it's a sample table Neon auto-provisions in new databases, unrelated to
  this app's schema. See `_IGNORED_TABLES` in `env.py` if another such table
  ever needs excluding.
- Baseline revision `0b624a4a7481` ("baseline: existing schema") was
  generated against the models as of the Alembic setup and verified with
  `alembic check` to have **zero drift** against both the live database and
  a fresh local sqlite database — every table/column that existed before
  Alembic was introduced is captured, nothing missing, nothing extra.
