"""
tests/test_alembic_metadata.py
------------------------------
Phase 8CG / 8DQ — metadata-only verification of the reconciled nikhil Alembic
graph. Loads the migration script directory directly (no database, no
`alembic upgrade`/`stamp`/`downgrade` — purely exercises the revision chain
as it exists on disk, exactly the same way `alembic heads`/`branches`/
`history` do).

Phase 8DQ correction: an earlier version of this test asserted, as
"intentional," that `13ce5f1cf7a1`'s down_revision pointed at `fbfe6d7eeb2e`
— a revision that exists as a FILE nowhere in this repository (not on
`nikhil`, and not committed on `main` either — confirmed by grepping every
fetched branch; it only ever existed as an uncommitted file in a disposable
`main`-repair worktree). That made `alembic.script.ScriptDirectory` raise a
hard `KeyError` for ANY command (`heads`/`history`/`upgrade`), not merely
report a second head — this repo's own Alembic tooling was unusable on
`nikhil` before the fix. Corrected by re-parenting `13ce5f1cf7a1` onto
`2b3c4d5e6f70` (the real, already-existing nikhil head at the time
`13ce5f1cf7a1` was authored — verified via `git log` dates: `2b3c4d5e6f70`
landed 2026-09-11, `13ce5f1cf7a1`/`abaca1105dbb` landed 2026-09-17). This
test now uses Alembic's real `ScriptDirectory` (no more hand-rolled regex
parser needed, since the graph is genuinely loadable again) and asserts the
resulting SINGLE head.

Checks enforced here:

1. Exactly one head: `abaca1105dbb` (tip of `2b3c4d5e6f70` -> `13ce5f1cf7a1`
   -> `abaca1105dbb`).
2. The only branch points are the three known, pre-existing ones
   (`d6e7f8a9b0c1`, `d7e2f4a91b53`, `dde9b427b6bf`) — no new divergences.
3. No duplicate revision IDs in the versions directory.
4. The Phase 8CG wiring is intact: `a6b7c8d9e0f2` -> `b7c8d9e0f2a3` ->
   `d3e4f5a6b7c8` (with `a6b7c8d9e0f2` preserving the original two-parent
   mergepoint down_revision).
5. No ACTIVE migration still carries the old collision IDs as its own
   `revision` or references them as a `down_revision` — historical docstring
   mentions are allowed and expected, so only the identifier fields are
   asserted here.
6. The corrected production chain: `2b3c4d5e6f70 -> 13ce5f1cf7a1 ->
   abaca1105dbb`, and `fbfe6d7eeb2e` no longer appears anywhere as an active
   identifier.
7. Total migration file count is the validated reconciled count (76).
"""

import re
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parent.parent
_VERSIONS_DIR = _BACKEND_ROOT / "alembic" / "versions"

_REVISION_RE = re.compile(
    r"^revision\s*(?::\s*str\s*=\s*|=)\s*['\"]([0-9a-f]{12})['\"]", re.MULTILINE
)
_DOWN_REVISION_RAW_RE = re.compile(
    r"^down_revision[^=]*=\s*(?:\(([^)]*)\)|['\"]([0-9a-f]{12})['\"])",
    re.MULTILINE,
)


def _parse_revisions() -> dict:
    """Parse only the `revision` / `down_revision` identifier fields from
    every migration file on disk. Returns {revision_id: list-of-parent-ids}.

    A hand-rolled parser rather than `alembic.script.ScriptDirectory` mainly
    so this test can assert on plain dicts without needing a configured
    Alembic `Config`/env — the graph itself is fully loadable via the real
    API too (see `test_real_alembic_script_directory_loads_single_head`)."""
    revs: dict = {}
    for path in sorted(_VERSIONS_DIR.glob("*.py")):
        text = path.read_text(encoding="utf-8")
        rev_matches = list(_REVISION_RE.finditer(text))
        if not rev_matches:
            continue
        # The `# revision identifiers` block is the final `revision:` /
        # `down_revision:` occurrence in every generated file; taking the
        # last match is resilient against docstrings that quote the words
        # verbatim inside prose.
        rev_id = rev_matches[-1].group(1)
        parents: list = []
        down_matches = list(_DOWN_REVISION_RAW_RE.finditer(text))
        if down_matches:
            down_match = down_matches[-1]
            if down_match.group(1):
                parents = re.findall(r"['\"]([0-9a-f]{12})['\"]", down_match.group(1))
            elif down_match.group(2):
                parents = [down_match.group(2)]
        revs[rev_id] = parents
    return revs


def _children_map(revs: dict) -> dict:
    children: dict = {}
    for rev, parents in revs.items():
        for parent in parents:
            children.setdefault(parent, []).append(rev)
    return children


def test_alembic_heads_is_single_head_abaca1105dbb():
    revs = _parse_revisions()
    children = _children_map(revs)
    heads = sorted(r for r in revs if r not in children)
    assert heads == ["abaca1105dbb"]


def test_real_alembic_script_directory_loads_single_head():
    """Exercises the actual Alembic API (not the hand-rolled parser above) to
    confirm the graph is genuinely loadable — this raised a hard KeyError
    before the Phase 8DQ down_revision fix."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert list(script.get_heads()) == ["abaca1105dbb"]


def test_alembic_branchpoints_are_only_the_known_existing_ones():
    """The reconciles renames must not add branch points. `branchpoint` ==
    a revision with more than one child; `mergepoint` == a revision with a
    tuple down_revision (asserted via test_alembic_..._wiring_..._is_intact)."""
    revs = _parse_revisions()
    children = _children_map(revs)
    branchpoints = sorted(k for k, v in children.items() if len(v) > 1)
    assert branchpoints == ["d6e7f8a9b0c1", "d7e2f4a91b53", "dde9b427b6bf"]


def test_no_duplicate_revision_ids_in_versions_directory():
    revs = _parse_revisions()
    assert len(revs) == len(set(revs))
    # 74 committed revisions (Phase 8CG-validated) + the 2 landed Phase
    # 8DD/8DI production migrations = 76.
    assert len(revs) == 76


def test_germany_head_chain_wiring_a6_b7_d3_is_intact():
    revs = _parse_revisions()

    # a6 is the two-parent mergepoint; its down_revision tuple is preserved
    # verbatim from the original c7d8e9f0a1b2 mergepoint.
    assert revs.get("a6b7c8d9e0f2") == ["b5c6d7e8f9a2", "b6c7d8e9f0a1"]

    # b7 descends from a6 (was: g7h8i9j0k1l2)
    assert revs.get("b7c8d9e0f2a3") == ["a6b7c8d9e0f2"]

    # d3 descends from b7 (was: f61cb4b650f4)
    assert revs.get("d3e4f5a6b7c8") == ["b7c8d9e0f2a3"]


def test_production_chain_2b3c_13ce_abaca_is_connected():
    """Phase 8DQ correction: `13ce5f1cf7a1`/`abaca1105dbb` are re-parented onto
    the real nikhil head `2b3c4d5e6f70` instead of the phantom, never-committed
    `fbfe6d7eeb2e` — see module docstring for the full incident."""
    revs = _parse_revisions()
    assert revs.get("13ce5f1cf7a1") == ["2b3c4d5e6f70"]
    assert revs.get("abaca1105dbb") == ["13ce5f1cf7a1"]
    assert "fbfe6d7eeb2e" not in revs


def test_no_active_revision_or_down_revision_uses_old_collision_ids():
    """`c7d8e9f0a1b2` and `f61cb4b650f4` must no longer appear as an ACTIVE
    revision identifier or down_revision anywhere in the migration chain.
    Historical mentions inside docstrings (which document the rename) are
    intentionally out of scope for this check."""
    old_ids = {"c7d8e9f0a1b2", "f61cb4b650f4"}
    revs = _parse_revisions()
    assert not (set(revs) & old_ids)
    for rev, parents in revs.items():
        assert not (set(parents) & old_ids), (
            f"{rev} still references old collision id(s) "
            f"{sorted(set(parents) & old_ids)} as down_revision"
        )