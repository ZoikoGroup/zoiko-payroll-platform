"""
tests/test_alembic_metadata.py
------------------------------
Phase 8CG / 8DQ / 8DT — metadata-only verification of the reconciled Alembic
graph. Loads the migration script directory directly (no database, no
`alembic upgrade`/`stamp`/`downgrade` — purely exercises the revision chain
as it exists on disk, exactly the same way `alembic heads`/`branches`/
`history` do).

Phase 8DT — this file previously asserted `nikhil`'s own standalone chain
(single head `abaca1105dbb`, 76 files). This branch (`reconcile/germany-
2026-main-integration`) merges `nikhil` into `origin/main`, which brings in
`main`'s own 126 files (including a pre-existing, unrelated two-heads split
of its own: `1dc04f15a9b7`/AU SAPTO and `a3f5c9d1b2e4`/legal entities) plus
the 4 previously-collided rename pairs each branch had independently
resolved differently. Reconciliation, in order:

1. The 4 rename-collision pairs were unified onto `main`'s canonical IDs
   (`main` is the actually-deployed lineage): `65bc3ca96fd6`,
   `0800e995078f`, `185332840016`, `b4241285b6dd`. `nikhil`'s redundant,
   byte-identical renamed duplicates (`a6b7c8d9e0f2`, `a4dcd30e7ec1`,
   `cda89a810e94`, `824bb1b61dc2`) were dropped.
2. `nikhil`'s own `b7c8d9e0f2a3` (the Germany production chain recovery
   graft, which has no `main` equivalent) was re-parented from the dropped
   `a6b7c8d9e0f2` onto `main`'s canonical `65bc3ca96fd6`.
3. `nikhil`'s Germany-schema-only migrations (`13ce5f1cf7a1`, `abaca1105dbb`)
   are unchanged, still descending from the shared fork point
   `2b3c4d5e6f70`.
4. A new no-op merge migration, `752aa7829541`, unifies all three remaining
   tips (`1dc04f15a9b7`, `a3f5c9d1b2e4`, `abaca1105dbb`) into a single head.

Total: 126 (main) + 4 new/kept (`b7c8d9e0f2a3`, `13ce5f1cf7a1`,
`abaca1105dbb`, `752aa7829541`) = 130. The 4 dropped nikhil-only duplicates
were never part of `main`'s 126, so they don't need subtracting.

Checks enforced here:

1. Exactly one head: `799b28d80edd`.
2. Branch points are exactly the reconciled set — `main`'s own pre-existing
   ones plus `2b3c4d5e6f70` (where `main`'s and Germany's post-fork
   histories diverge).
3. No duplicate revision IDs in the versions directory; total count is 132.
4. The Germany chain wiring is intact: `65bc3ca96fd6 -> b7c8d9e0f2a3 ->
   d3e4f5a6b7c8` and `2b3c4d5e6f70 -> 13ce5f1cf7a1 -> abaca1105dbb`.
5. `nikhil`'s 4 redundant renamed duplicates no longer appear as an ACTIVE
   revision anywhere (dropped in favor of `main`'s canonical IDs).

Germany 2026 all-Länder jurisdiction task — two more additive, linear
migrations landed on top of `752aa7829541` (schema-drift fixes found while
seeding the real Germany 2026 registries against Postgres for the first
time; SQLite doesn't enforce VARCHAR length so these went uncaught until
now): `00a912d5306c` (widen GermanyEarningTaxabilityRule.gkv_pv_treatment/
rv_alv_treatment to match the model's already-declared String(40)) ->
`799b28d80edd` (widen TaxConfigurationAudit.entity_type from String(30) to
String(50) — several existing Germany audit call sites already exceeded
30 chars). Neither touches a branchpoint or the Germany chain wiring below
— they're a new, single-parent tail after the existing head, so only the
head literal and total revision count change; the 5 checks above except
1 and 3 are otherwise unaffected. 130 + 2 = 132.
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


def test_alembic_heads_is_single_head_799b28d80edd():
    revs = _parse_revisions()
    children = _children_map(revs)
    heads = sorted(r for r in revs if r not in children)
    assert heads == ["799b28d80edd"]


def test_real_alembic_script_directory_loads_single_head():
    """Exercises the actual Alembic API (not the hand-rolled parser above) to
    confirm the graph is genuinely loadable."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert list(script.get_heads()) == ["799b28d80edd"]


def test_alembic_branchpoints_are_only_the_known_existing_ones():
    """Branch points == revisions with more than one child. Reconciliation
    adds exactly one new branchpoint (`2b3c4d5e6f70`, where Germany's
    post-fork history diverges from `main`'s own); every other branchpoint
    here is pre-existing on `main`'s own independently-evolved graph."""
    revs = _parse_revisions()
    children = _children_map(revs)
    branchpoints = sorted(k for k, v in children.items() if len(v) > 1)
    assert branchpoints == [
        "2b3c4d5e6f70", "40efec6cf8b7", "4b296dbd4181", "737e7bfa2d77",
        "b6c7d8e9f0a1", "c1f5a9d22e10", "d6e7f8a9b0c1", "d7e2f4a91b53",
        "dde9b427b6bf", "f1b78410d568", "fbfe6d7eeb2e",
    ]


def test_no_duplicate_revision_ids_in_versions_directory():
    revs = _parse_revisions()
    assert len(revs) == len(set(revs))
    # 126 (main) + 4 new/kept from nikhil (b7c8d9e0f2a3, 13ce5f1cf7a1,
    # abaca1105dbb, the 752aa7829541 merge) = 130, + 2 additive Germany
    # 2026 all-Länder schema-drift fixes (00a912d5306c, 799b28d80edd) = 132.
    assert len(revs) == 132


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
