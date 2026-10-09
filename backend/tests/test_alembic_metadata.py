"""Metadata-only checks for the checked-in Alembic revision graph.

The graph must have one head, no duplicate revision IDs, and retain the
known Germany migration chain wiring. These tests inspect the files directly
and also load the real Alembic ScriptDirectory without touching a database.
The current graph has head ``c4d5e6f7a8b9`` (drop the Ireland Revenue
submission + monthly return tables, undoing ``9f8e7d6c5b4a``) on top of
``7c3e1a9d5f20`` (merge of main's
``998877665544`` orphan IE/FR column drop with venu's chain, re-adding those
columns if missing) on top of ``998877665544`` (itself on ``f0b1c2d3e4f5``,
making that a branchpoint) and ``a1b2c3d4e5f7`` (add composite index on
payroll_attendance_records for attendance queries, Phase 1.1) on top of
``9f8e7d6c5b4a`` (recreate Ireland Revenue
submission + monthly return tables, ZP-IE-ENG-001 WP2, since dropped again by
``c4d5e6f7a8b9``) on top of
``2c7d9e0f3a5b`` (merge
payroll_ie_ytd_accumulators into payroll_ytd_accumulators, ZP-IE-ENG-001,
7 IE tables -> 3) on top of ``f6b2c4d8e1a3`` (drop the three dead Ireland
tables, same task) on top of ``e5a1c7b9d204`` (add
payroll_ie_statutory_sick_leave_records, ZP-IE-ENG-001 §11/IE-037) on top of
``c7d4e9f1a2b3`` (add ie_calculation_snapshot to payslip_items, also
ZP-IE-ENG-001) on top of ``4b13831d574b`` (ensure
communication_events, itself on top of merge ``5ae06cfda828``), and 160
revisions — the
merge of venu's branch (PR withholding certificates -> France compliance
tables -> France establishments/editable fields -> Ireland) with main's
(communication_events -> drop orphan SGP columns), which forked at
``d4e5f6a7c8b9`` (Rugvedh's auth_email_events table).

Note ``c4d5e6f7a8b9``, ``a1b2c3d4e5f7``, ``9f8e7d6c5b4a``, ``2c7d9e0f3a5b``,
``f6b2c4d8e1a3``, ``e5a1c7b9d204`` and ``c7d4e9f1a2b3`` are plain
single-parent revisions, so they
add no branchpoint: ``test_alembic_branchpoints_are_only_the_known_existing_ones``
is unchanged by them and keeps its own hardcoded list.
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
    # R2 (2026-09-29): origin/main's d4e5f6a7c8b9 -> e7f1a2b3c4d5 ->
    # f0b1c2d3e4f5 -> 998877665544 are carried byte-identically, and the
    # Singapore chain's first revision c3d9e1f4a7b2 now sits on 998877665544,
    # so the graph is linear and identical to the merged main + Singapore one.
    # cd62503afe26 (2026-09-30, Hong Kong ZP-HK-ENG-001): hk_* statutory
    # profile columns, payslip_items.hk_calculation_trace and the seven hk_
    # registries, down_revision 917a54ed2347 (re-parented from 445abd6a9083 at the
    # main integrations — linear, no new branchpoint).
    # 445abd6a9083 (2026-09-29, SG G3 IR8A Revision/Amendment): the
    # sgp_ir8a_modifications table models.SgpIr8aModification declares,
    # down_revision b8e3d5f2a9c7 (was parked on a release-line merge that
    # no longer exists; see the migration docstring).
    # b8e3d5f2a9c7 (2026-09-25, Phase 5.5 SG-018): sgp_pwm_overtime_schedules,
    # down_revision a7c2e9f4b1d6.
    # a7c2e9f4b1d6 (2026-09-24, Phase 5 S1): payroll_employees.sgp_wp_sector /
    # sgp_wp_skill_level / sgp_wp_levy_tier, down_revision f6a1b4c8d3e5
    # f6a1b4c8d3e5 (2026-09-24): sgp_ir21_cases, down_revision e5f9a3b7c2d4
    # (payroll_employees.sgp_work_pass_issue/end_date, on d4e8f2a6b9c1 —
    # payslip_items.sgp_calculation_trace, on c3d9e1f4a7b2 — which added the
    # Singapore CPF employee columns on a5f6e7d8c9b0).
    # 66072e2d80a9 (2026-09-29): merge of that Singapore head with venu's
    # c4d5e6f7a8b9 (Ireland Revenue tables, on 7c3e1a9d5f20 -> 998877665544).
    # e8f1a2b3c4d5 (2026-09-30, ZP-SE-ENG-001): Sweden jurisdiction support
    # (collective agreements, sick episodes, leave ledgers, se_* profile
    # columns), down_revision 66072e2d80a9 — idempotency-guarded.
    # 7a1b2c3d4e5f (ZP-IT-ENG-001): Italy jurisdiction support — Italy
    # employer profile + filing outbox tables, fifteen it_* profile columns,
    # payslip_items.it_calculation_snapshot; down_revision e8f1a2b3c4d5 —
    # idempotency-guarded, and it adds NO new branchpoint (single child of
    # e8f1a2b3c4d5, so the branchpoint list below is unchanged).
    # 917a54ed2347 (ZP-IT-ENG-001 P2): Italy ledgers — CCNL level terms, TFR
    # ledger, F24 lines, LUL entries + it_contractual_weekly_hours; single child
    # of 7a1b2c3d4e5f, so no new branchpoint.
# c9d8e7f6a5b4 (ZP-IT-ENG-001 3A): Italy F24 causale catalog
    # (payroll_it_f24_causales, seeded EMPTY — IT-043 forbids inventing causali)
    # plus uq_it_f24_line_identity on payroll_it_f24_lines; re-parented onto
    # cd62503afe26 (Hong Kong) when venu merged main (2026-10-06), so the chain
    # is linear: 917a54ed2347 -> cd62503afe26 -> c9d8e7f6a5b4 -> d7e6f5a4b3c2.
    # d7e6f5a4b3c2 (ZP-IT-ENG-001 3C): Italy LUL registered content — payload,
    # event_kind, method, registered_reference on payroll_it_lul_entries; single
    # child of c9d8e7f6a5b4, so no new branchpoint.
    # 3baddbaa011a (CH jurisdiction support): Switzerland data model — seven
    # payroll_ch_* tables, 29 nullable ch_* profile columns, five taxability-rule
    # lifecycle columns, CollectiveAgreement.jurisdiction_state,
    # payslip_items.ch_calculation_snapshot; single child of d7e6f5a4b3c2, so no
    # new branchpoint.
    # 376bb8637603 (CH Step 5): payroll_ch_entity_profiles versioned (unique
    # per organization + effective_from instead of per organization) and
    # payroll_ch_idempotency_records; single child of 3baddbaa011a, so no new
    # branchpoint.
    # c5981cbcbe13 (2026-10-06, attendance gate): payroll_policies attendance
    # settings + payroll_runs attendance override audit; single child of
    # 376bb8637603, so no new branchpoint.
    # cd62503afe26 (2026-09-30, Hong Kong ZP-HK-ENG-001), re-parented onto
    # 917a54ed2347 (Italy ledgers) when nikhil integrated main — linear, single head.
    # 2d0cdeeeecc4 (2026-10-05, Hong Kong remediation gap 6): partial unique
    # indexes on the hk_ tenant workflows, single child of cd62503afe26.
    # f898189cb4e3 (2026-10-06): merge of main's 2d0cdeeeecc4 (HK convergence)
    # with venu's c5981cbcbe13 (Italy 3A/3C -> CH -> attendance gate); both
    # chains grow from cd62503afe26. Pure graph merge, no schema change.
    # 6b5a4c3d2e1f (2026-10-07, CH Step 14): payroll_ch_elm_submissions gains
    # the nullable payload_xml body column; single child of f898189cb4e3, so
    # no new branchpoint.
    # b08f04497195 (2026-10-08, Saudi Arabia foundation): one additive migration
    # with sa_* profile columns, payslip_items SA columns, and 7 new SA tables;
    # single child of 6b5a4c3d2e1f, so no new branchpoint.
    assert heads == ["c7d3e8f1a2b4"]


def test_real_alembic_script_directory_loads_single_head():
    """Exercises the actual Alembic API (not the hand-rolled parser above) to
    confirm the graph is genuinely loadable."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    cfg = Config(str(_BACKEND_ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(_BACKEND_ROOT / "alembic"))
    script = ScriptDirectory.from_config(cfg)
    assert list(script.get_heads()) == ["c7d3e8f1a2b4"]


def test_alembic_branchpoints_are_only_the_known_existing_ones():
    """Branch points == revisions with more than one child. Reconciliation
    adds exactly one new branchpoint (`2b3c4d5e6f70`, where Germany's
    post-fork history diverges from `main`'s own); every other branchpoint
    here is pre-existing on `main`'s own independently-evolved graph, plus
    the commercial billing fork points on `1dc04f15a9b7` and `a3f5c9d1b2e4`,
    and `d4e5f6a7c8b9` where venu's France/Ireland chain and main's
    communications chain fork (rejoined by merge `5ae06cfda828`), and
    `f0b1c2d3e4f5` where main's `998877665544` and venu's chain fork
    (rejoined by merge `7c3e1a9d5f20`)."""
    revs = _parse_revisions()
    children = _children_map(revs)
    branchpoints = sorted(k for k, v in children.items() if len(v) > 1)
    assert branchpoints == [
        "1dc04f15a9b7", "2b3c4d5e6f70", "40efec6cf8b7", "4b296dbd4181",
        "737e7bfa2d77",
        # 998877665544: main's Singapore chain (c3d9e1f4a7b2) and venu's
        # 7c3e1a9d5f20 both grow from it; rejoined by merge 66072e2d80a9.
        "998877665544",
        "a3f5c9d1b2e4", "b6c7d8e9f0a1", "c1f5a9d22e10",
        # cd62503afe26: main's 2d0cdeeeecc4 (HK convergence) and venu's
        # c9d8e7f6a5b4 (Italy F24 causale) both grow from it; rejoined by
        # merge f898189cb4e3.
        "cd62503afe26",
        "d4e5f6a7c8b9", "d6e7f8a9b0c1", "d7e2f4a91b53", "dde9b427b6bf",
        "f0b1c2d3e4f5", "f1b78410d568", "fbfe6d7eeb2e",
    ]


def test_no_duplicate_revision_ids_in_versions_directory():
    revs = _parse_revisions()
    assert len(revs) == len(set(revs))
    assert len(revs) == 182   # + 6b5a4c3d2e1f (CH Step 14 ELM payload column) + f898189cb4e3 (merge HK convergence / venu chain) + 2d0cdeeeecc4 (HK uniqueness) + c5981cbcbe13 (attendance gate) + 376bb8637603 (CH Step 5 versioned entity profile + idempotency) + 917a54ed2347 (Italy P2 ledgers) + c9d8e7f6a5b4 (Italy F24 causale catalog) + d7e6f5a4b3c2 (Italy LUL registered content) + cd62503afe26 (Hong Kong) + 3baddbaa011a (Switzerland jurisdiction support) + b08f04497195 (Saudi Arabia foundation) + c7d3e8f1a2b4 (Saudi Arabia approval fingerprint)


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
