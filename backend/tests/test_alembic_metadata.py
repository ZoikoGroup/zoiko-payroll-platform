"""Metadata-only checks for the checked-in Alembic revision graph.

The graph must have one head, no duplicate revision IDs, and retain the
known Germany migration chain wiring. These tests inspect the files directly
and also load the real Alembic ScriptDirectory without touching a database.
The current graph has head ``8596179ade04`` and 144 revisions — Puerto
Rico's own PR withholding-certificates migration, re-parented onto
``d4e5f6a7c8b9`` (Rugvedh's auth_email_events table, merged via main PR
#67) during the venu/main alembic-fork reconciliation (2026-09-24).
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


def test_alembic_heads_is_single_head():
    revs = _parse_revisions()
    children = _children_map(revs)
    heads = sorted(r for r in revs if r not in children)
    assert heads == ["8596179ade04"]


def test_real_alembic_script_directory_loads_single_head():
    """Exercises the actual Alembic API (not the hand-rolled parser above) to
    confirm the graph is genuinely loadable."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert list(script.get_heads()) == ["8596179ade04"]


def test_alembic_branchpoints_are_only_the_known_existing_ones():
    """Branch points == revisions with more than one child. Reconciliation
    adds exactly one new branchpoint (`2b3c4d5e6f70`, where Germany's
    post-fork history diverges from `main`'s own); every other branchpoint
    here is pre-existing on `main`'s own independently-evolved graph, plus
    the commercial billing fork points on `1dc04f15a9b7` and `a3f5c9d1b2e4`."""
    revs = _parse_revisions()
    children = _children_map(revs)
    branchpoints = sorted(k for k, v in children.items() if len(v) > 1)
    assert branchpoints == [
        "1dc04f15a9b7", "2b3c4d5e6f70", "40efec6cf8b7", "4b296dbd4181",
        "737e7bfa2d77", "a3f5c9d1b2e4", "b6c7d8e9f0a1", "c1f5a9d22e10",
        "d6e7f8a9b0c1", "d7e2f4a91b53", "dde9b427b6bf", "f1b78410d568",
        "fbfe6d7eeb2e",
    ]


def test_no_duplicate_revision_ids_in_versions_directory():
    revs = _parse_revisions()
    assert len(revs) == len(set(revs))
    assert len(revs) == 144


def test_germany_head_chain_wiring_is_intact():
    revs = _parse_revisions()

    # main's canonical merge point -> nikhil's chain-recovery graft
    # (re-parented during Phase 8DT reconciliation) -> the elstam
    # uniqueness migration.
    assert revs.get("b7c8d9e0f2a3") == ["65bc3ca96fd6"]
    assert revs.get("d3e4f5a6b7c8") == ["b7c8d9e0f2a3"]

    # The shared fork point -> Germany's schema-only migrations.
    assert revs.get("13ce5f1cf7a1") == ["2b3c4d5e6f70"]
    assert revs.get("abaca1105dbb") == ["13ce5f1cf7a1"]

    # The final reconciliation merge unifies main's own two heads with
    # Germany's tip.
    assert sorted(revs.get("752aa7829541") or []) == sorted(
        ["1dc04f15a9b7", "a3f5c9d1b2e4", "abaca1105dbb"]
    )


def test_no_active_revision_uses_nikhils_dropped_duplicate_rename_ids():
    """`nikhil` had independently renamed the same 4 shared collision points
    to IDs different from `main`'s own choices. Reconciliation adopted
    `main`'s canonical IDs throughout and dropped `nikhil`'s duplicates —
    none of the 4 dropped IDs should appear as an ACTIVE revision or
    down_revision anywhere. (`c7d8e9f0a1b2`/`f61cb4b650f4` are intentionally
    NOT checked here: both are legitimately reused by real, unrelated `main`
    migrations post-reconciliation — `add_payroll_ytd_accumulators_table_
    widen_tax_year` and `add_us_w4_step2_checkbox` respectively — historical
    docstring mentions of the old Germany-side meaning are expected.)"""
    dropped_ids = {"a6b7c8d9e0f2", "a4dcd30e7ec1", "cda89a810e94", "824bb1b61dc2"}
    revs = _parse_revisions()
    assert not (set(revs) & dropped_ids)
    for rev, parents in revs.items():
        assert not (set(parents) & dropped_ids), (
            f"{rev} still references a dropped duplicate rename id "
            f"{sorted(set(parents) & dropped_ids)} as down_revision"
        )
