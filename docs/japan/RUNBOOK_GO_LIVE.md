# Japan go-live runbook (ZP-JP-ENG-001)

Japan ships switched off. Deploying the code changes nothing for tenants: the Japan routes answer 404, the
rule pack is Draft, and every Japan calculation blocks with a named reason until the official data is
signed. This runbook is the order of the steps that turn it on. Each step needs its named owner; none is
done from a developer machine against production.

## 1. Deploy (engineering)

1. Open the PR from `venu` to `main`. Before merging, fetch `main`: if it gained migrations after
   `668472e4eb72`, merge `main` into `venu` and re-parent the first Japan migration (`9c1d7e4a2b6f`) onto
   `main`'s head so there is one head. Update `tests/test_alembic_metadata.py`, the deploy test's pending
   sets, `alembic/MIGRATIONS_MANIFEST.txt` and the drift tests.
2. Full test suite, `python -c "import app.main"`, and the frontend gates (`npm run build`,
   `npm run check:undefined`, `npm test`).
3. Merge. The deploy pipeline applies the additive Japan migrations:
   `9c1d7e4a2b6f`, `a7c4e9d1b2f8`, `a1a748b50902`, `41a1fafbbfdc`, `b8bd939fffca`.
4. Check the production `alembic_version`, that `/api/payroll/japan/*` answers 404, and that another
   country's run approval and the retention report still work.

## 2. Secrets (security)

1. Put `JP_MY_NUMBER_KEYRING` (versioned AES-256 keys) and `JP_MY_NUMBER_FINGERPRINT_KEY` (never rotated)
   in Secret Manager. Never in `.env` files or the repository.
2. Rehearse a key rotation on a non-production copy:
   `python -m scripts.rotate_jp_my_number_keys` (dry run), then `--apply`. The output is counts only.

## 3. Official data (G1–G5 owners)

1. Seed the canonical pack once if it is not there: `python -m scripts.seed_japan_canonical_packs`
   (refuses a non-local database; production seeding goes through the approved pipeline).
2. Enter each authority table and value through the Super Admin pack editor from the archived source,
   remove its `[PENDING G1]` marker only when a second reviewer has checked it, and record the gate's
   evidence (`JP-GATE-Gn`) as described in `docs/japan/release-gates/`.
3. Watch the Readiness tab: every check must turn green from the data itself.

## 4. Parallel cycles (payroll operations, G7)

1. Run at least two pay months for the pilot organisation in parallel with the current provider.
2. Import the provider's figures (no identifiers in the file) under Compliance Centre → parallel cycles,
   explain every difference, have a second person accept them, and accept each cycle.

## 5. Sign-off and switch-on (CTO)

1. Record the owner decisions D-1 to D-5 and the three sign-offs (`JP-SIGNOFF-PRODUCT`,
   `JP-SIGNOFF-COMPLIANCE`, `JP-SIGNOFF-ENGINEERING`).
2. Activate the pack (refused while anything is pending).
3. Move Japan's service availability to AVAILABLE (refused unless every gate passes).
4. Set `JP_TENANT_ONBOARDING_ENABLED=True` and enable the pilot organisation only.
5. Supervise its first live run end to end: exceptions, approval, payment, remittances.

## Rollback

- Switch `JP_TENANT_ONBOARDING_ENABLED` back to False: Japan routes return 404 again and no data is lost.
- Move the service availability back to PLANNED.
- The Japan migrations are additive; their downgrades exist but are not needed to switch Japan off.
