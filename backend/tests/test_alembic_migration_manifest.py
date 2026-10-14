"""CI guard for the migration history (deploy failure 4c5d6e7f8a9b, 2026-10-14).

Production can only be migrated safely if every migration it may already have run is
still in the repository, unchanged. These tests fail when a migration is deleted,
renamed or edited, when a new one is not registered in alembic/MIGRATIONS_MANIFEST.txt,
when revision ids repeat, or when there is more than one head. Regenerate the manifest
only when adding a migration on purpose: python -m scripts.update_migration_manifest.
Pure file checks - no database, no app import."""
import pathlib
import re
import subprocess

BACKEND = pathlib.Path(__file__).resolve().parent.parent
REPO = BACKEND.parent


def _manifest() -> dict:
    lines = (BACKEND / "alembic" / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8").splitlines()
    return {l.split("|")[0]: l for l in lines if l.strip()}


def _current() -> dict:
    from scripts.update_migration_manifest import entries

    return {l.split("|")[0]: l for l in entries()}


def test_no_registered_migration_is_deleted_renamed_or_edited():
    registered, current = _manifest(), _current()
    missing = sorted(set(registered) - set(current))
    changed = sorted(f for f in registered if f in current and registered[f] != current[f])
    assert not missing, f"migration file(s) deleted or renamed: {missing}"
    assert not changed, (f"migration file(s) edited after registration: {changed}. An applied migration must never "
                         "change; add a new migration instead.")


def test_every_migration_file_is_registered():
    unregistered = sorted(set(_current()) - set(_manifest()))
    assert not unregistered, (f"new migration(s) not in alembic/MIGRATIONS_MANIFEST.txt: {unregistered}. "
                              "Run: python -m scripts.update_migration_manifest")


def test_revision_ids_are_unique_and_there_is_one_head():
    rows = [l.split("|") for l in _current().values()]
    revs = [r[1] for r in rows]
    assert all(revs) and len(revs) == len(set(revs)), "duplicate or missing revision ids"
    parents = {p for r in rows for p in r[2].split(",") if p}
    assert not parents - set(revs), f"down_revision(s) pointing at no file: {sorted(parents - set(revs))}"
    heads = sorted(set(revs) - parents)
    assert len(heads) == 1, f"expected exactly one alembic head, found {heads}"


def test_no_migration_deleted_or_renamed_against_origin_main():
    """Only where git and origin/main are available (local runs; a shallow CI checkout skips)."""
    import pytest

    probe = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "origin/main"], cwd=REPO,
                           capture_output=True, text=True)
    if probe.returncode != 0:
        pytest.skip("origin/main not available in this checkout")
    out = subprocess.run(["git", "diff", "--name-status", "--diff-filter=DR", "origin/main", "--",
                          "backend/alembic/versions"], cwd=REPO, capture_output=True, text=True).stdout
    removed = [l for l in out.splitlines() if re.match(r"^[DR]", l)]
    assert not removed, f"migration files deleted/renamed relative to origin/main: {removed}"
