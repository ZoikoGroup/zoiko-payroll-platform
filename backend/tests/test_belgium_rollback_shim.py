"""Belgium (ZP-BE-ENG-001) Block I1: the code-only rollback shim (scripts/belgium_rollback_shim.py).

On a synthetic "reverted" tree (models without the two Belgian columns, a manifest without the three Belgian
lines) the shim restores exactly the three revision files, the manifest lines, the two nullable column
declarations and the re-pinned alembic tests — idempotently, and a dry run writes nothing. The end-to-end proof
against the real pre-Belgium code (deploy_migrate.sh, drift, payroll operations) is
scripts/be_rollback_orm_check.py (needs git history; recorded in DEPLOY_NOTES.md §4)."""
import importlib.util
import pathlib
import shutil

REPO = pathlib.Path(__file__).resolve().parents[2]


def _shim():
    spec = importlib.util.spec_from_file_location("belgium_rollback_shim",
                                                  REPO / "backend" / "scripts" / "belgium_rollback_shim.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _reverted_tree(tmp_path, shim):
    target = tmp_path / "revert"
    models = (REPO / shim.MODELS).read_text(encoding="utf-8")
    for _anchor, addition in shim.COLUMNS:
        column = addition.splitlines()[-1]
        models = "\n".join(ln for ln in models.split("\n") if ln != column)
    manifest = "".join(ln for ln in (REPO / shim.MANIFEST).read_text(encoding="utf-8").splitlines(keepends=True)
                       if not any(f"|{rev}|" in ln for rev in shim.REVISIONS))
    for rel, text in ((shim.MODELS, models), (shim.MANIFEST, manifest)):
        (target / rel).parent.mkdir(parents=True, exist_ok=True)
        (target / rel).write_text(text, encoding="utf-8", newline="")
    return target


def test_the_shim_restores_only_the_schema_pieces_and_is_idempotent(tmp_path):
    shim = _shim()
    target = _reverted_tree(tmp_path, shim)
    assert "be_calculation_snapshot = Column(" not in (target / shim.MODELS).read_text(encoding="utf-8")

    planned = shim.apply(REPO, target, "HEAD", None, dry_run=True)
    assert len(planned) == len(shim.MIGRATIONS) + len(shim.PIN_TESTS) + len(shim.REVISIONS) + 2
    assert not any((target / p).exists() for p in shim.MIGRATIONS)                    # dry run wrote nothing

    shim.apply(REPO, target, "HEAD", None, dry_run=False)
    for path in shim.MIGRATIONS + shim.PIN_TESTS:
        assert (target / path).read_text(encoding="utf-8") == (REPO / path).read_text(encoding="utf-8"), path
    models = (target / shim.MODELS).read_text(encoding="utf-8")
    for column in ("be_calculation_snapshot", "be_approval_fingerprint"):
        assert models.count(f"    {column} = Column(JSON, nullable=True)") == 1
    manifest = (target / shim.MANIFEST).read_text(encoding="utf-8")
    revs = [ln.split("|")[1] for ln in manifest.splitlines() if ln.count("|") >= 2]
    assert manifest == (REPO / shim.MANIFEST).read_text(encoding="utf-8")                  # same lines, same order
    assert all(revs.count(rev) == 1 for rev in shim.REVISIONS)

    again = shim.apply(REPO, target, "HEAD", None, dry_run=False)
    assert not [a for a in again if a.startswith(("insert", "declare"))]                    # idempotent


def test_the_shim_refuses_a_pin_test_changed_after_the_merge(tmp_path):
    shim = _shim()
    target = _reverted_tree(tmp_path, shim)
    changed = target / shim.PIN_TESTS[0]
    changed.parent.mkdir(parents=True, exist_ok=True)
    changed.write_text("# changed on main after the merge\n", encoding="utf-8")
    import pytest

    with pytest.raises(SystemExit, match="changed on main after the merge"):
        shim.apply(REPO, target, "HEAD", "HEAD", dry_run=False)
    shutil.rmtree(target)
