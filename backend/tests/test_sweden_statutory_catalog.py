"""Sweden statutory catalog <-> engine <-> seed <-> frontend contract
(ZP-SE-ENG-001). engine/countries/sweden.py's SE_PARAMETER_KEYS is the one
backend list of seedable keys; the seed, the readiness registry and the
frontend's seComponentConfig.js must never silently drift from it."""
import re
from pathlib import Path

from app.modules.payroll.engine.countries import sweden as se
from app.modules.payroll.engine.countries.shared import _VALIDATION_ENABLED_COUNTRIES
from app.modules.payroll.engine.fallback_registry import get_required_parameter_keys

REPO = Path(__file__).resolve().parents[2]
FRONTEND_CONFIG = REPO / "frontend" / "src" / "components" / "jurisdiction" / "sweden" / "seComponentConfig.js"


def _frontend_keys() -> set:
    text = FRONTEND_CONFIG.read_text(encoding="utf-8")
    keys = set()
    for block in re.findall(r"export const SE_\w+_COMPONENT_KEYS = \[(.*?)\];", text, re.S):
        keys.update(re.findall(r'"(se_[a-z0-9_]+)"', block))
    return keys


def test_frontend_config_matches_engine_catalog():
    assert _frontend_keys() == set(se.SE_PARAMETER_KEYS)


def test_seed_rows_only_use_catalog_keys():
    from scripts import seed_sweden_canonical_packs as seed

    for spec in (seed._spec_2026(), seed._spec_2027()):
        keys = {k for k, _label, _kw in spec["rows"]}
        assert keys <= set(se.SE_PARAMETER_KEYS), keys - set(se.SE_PARAMETER_KEYS)
    assert {k for k, _l, _v in seed.ER_COMPONENTS_2026} == set(se.SE_ER_COMPONENT_KEYS)


def test_2026_components_sum_to_standard_rate():
    from decimal import Decimal
    from scripts import seed_sweden_canonical_packs as seed

    assert sum(Decimal(v) for _k, _l, v in seed.ER_COMPONENTS_2026) == Decimal("31.42")
    # The youth rate is the pension component plus half of the rest (spec §3
    # states 20.81%); a component-split change that breaks this is a review flag.
    pension = Decimal(dict((k, v) for k, _l, v in seed.ER_COMPONENTS_2026)["se_er_age_pension"])
    # 10.21 + 21.21 / 2 = 20.815, published (rounded) as 20.81.
    assert abs(pension + (Decimal("31.42") - pension) / 2 - Decimal("20.81")) <= Decimal("0.01")


def test_sweden_is_fail_closed():
    assert "SE" in _VALIDATION_ENABLED_COUNTRIES
    assert all(getattr(se, name) is None for name in dir(se) if name.startswith("_SE_"))


def test_required_keys_exclude_window_conditional_youth_rows():
    """The youth rows are legitimately absent outside 1 Apr 2026 – 30 Sep 2027;
    requiring them would block every Swedish payroll for Jan–Mar 2026."""
    required = {r["key"] for r in get_required_parameter_keys("SE")}
    assert "se_youth_reduced" not in required and "se_youth_monthly_threshold" not in required
    assert set(se.SE_ER_COMPONENT_KEYS) <= required
    assert {"se_sink", "se_supplementary_rate", "se_slp", "se_older_cohort_max_birth_year",
            "se_zero_cohort_max_birth_year"} <= required
    assert required <= set(se.SE_PARAMETER_KEYS)


def test_seeded_2026_pack_satisfies_every_required_key():
    from scripts import seed_sweden_canonical_packs as seed

    keys = {k for k, _l, _kw in seed._spec_2026()["rows"]}
    assert {r["key"] for r in get_required_parameter_keys("SE")} <= keys


def test_no_national_collective_agreement_type_exists():
    from app.modules.payroll import service

    assert "NATIONAL" not in service._CBA_TYPES
    assert "NATIONAL" not in FRONTEND_CONFIG.read_text(encoding="utf-8").split("SE_CBA_TYPES")[1].split("]")[0]


def test_report_field_paths_fit_the_postgres_column():
    """payroll_report_template_component_fields.source_column / field_key are
    VARCHAR(50). SQLite (the test DB) does not enforce lengths, so a longer
    path only fails on PostgreSQL — found 2026-10-01 seeding the shared DB."""
    from app.modules.payroll import service
    from app.modules.payroll.models import ReportTemplateComponentField as ReportTemplateField
    from scripts import seed_sweden_canonical_packs as seed

    limit = ReportTemplateField.__table__.c.source_column.type.length
    assert all(len(p) <= limit for p in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG["SE"]), \
        [p for p in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG["SE"] if len(p) > limit]
    import inspect
    src = inspect.getsource(seed._seed_agi_template)
    import re
    assert all(len(p) <= limit for p in re.findall(r'"(se_calculation_snapshot\.[a-z_.]+)"', src))
