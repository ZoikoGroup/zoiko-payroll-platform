"""Poland sickness and benefits (ZP-PL-ENG-001 Phase 6; spec §9, PL-017 / PL-018;
QA matrix "Sickness": 33/14-day transitions, 80%/100% cases, calendar-year
boundary, benefit-payer transition and retro absence)."""
import importlib.util
import json
import re
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
import sqlalchemy as sa

from app.core.exceptions import BadRequestException
from app.modules.payroll.engine.countries.poland import PLCalculationBlockedError, calculate
from tests._pl_engine_helpers import build_pack, ctx

MARCH = (date(2026, 3, 1), date(2026, 3, 31))
# TEST earning classes for employer sick pay (G1 signs the real ones): PIT and
# health include it; social insurance, funds, PPK and the minimum-wage test exclude it.
SICK_CLASSES = {(o, "SICK_PAY_EMPLOYER"): "EXCLUDED" for o in ("EMERYTALNE", "RENTOWE", "CHOROBOWE", "WYPADKOWE",
                                                                "FP_FS", "FGSP", "FEP", "PPK", "MIN_WAGE")}
SICK_CLASSES.update({("PIT", "SICK_PAY_EMPLOYER"): "INCLUDED", ("ZDROWOTNE", "SICK_PAY_EMPLOYER"): "INCLUDED"})


def episode(start, end, category="ILLNESS", base="250", ident=1, status="APPROVED"):
    return {"id": ident, "date_from": start, "date_to": end, "category": category, "daily_base_amount": base,
            "base_reference_from": date(2025, 3, 1), "base_reference_to": date(2026, 2, 28), "status": status}


def sick_ctx(sick_pay, episodes, salary="6000", ytd_days=0, dob=date(1990, 5, 1), pack=None, period=MARCH, **extra):
    sick_pay, salary = Decimal(str(sick_pay)), Decimal(str(salary))
    components = {"SALARY": salary}
    if sick_pay:
        components["SICK_PAY_EMPLOYER"] = sick_pay
    return ctx(gross=salary + sick_pay, components=components, pack=pack or build_pack(classes=SICK_CLASSES),
               pl_incapacity_episodes=episodes, pl_date_of_birth=dob, period_start=period[0], period_end=period[1],
               ytd_overrides={"SICK_DAYS_EMPLOYER": ytd_days}, **extra)


def _sick(context):
    return calculate(context)["pl_result"]["trace"]["sickness"]


def _blocks(context, prefix):
    with pytest.raises(PLCalculationBlockedError) as raised:
        calculate(context)
    assert raised.value.key.startswith(prefix), raised.value.key


# ── employer period and rate ───────────────────────────────────────────────
def test_ten_days_at_the_standard_rate():
    out = calculate(sick_ctx("2000", [episode(date(2026, 3, 2), date(2026, 3, 11))]))["pl_result"]
    sick = out["trace"]["sickness"]
    assert (sick["employerDays"], sick["zusDays"], sick["amount"]) == (10, 0, "2000.00")    # 10 x 250 x 80%
    assert sick["episodes"][0]["ratePct"] == "80.0000"
    assert out["accumulatorDeltas"]["SICK_DAYS_EMPLOYER"] == "10.00"


def test_full_rate_category_is_paid_at_100_percent():
    sick = _sick(sick_ctx("2500", [episode(date(2026, 3, 2), date(2026, 3, 11), category="PREGNANCY")]))
    assert sick["episodes"][0]["ratePct"] == "100.0000" and sick["amount"] == "2500.00"


def test_the_33rd_day_hands_over_to_zus():
    sick = _sick(sick_ctx("600", [episode(date(2026, 3, 2), date(2026, 3, 11))], ytd_days=30))
    line = sick["episodes"][0]
    assert (line["employerDays"], line["zusDays"], line["zusBenefitFrom"]) == (3, 7, "2026-03-05")
    assert sick["amount"] == "600.00"                                        # 3 x 250 x 80%


def test_after_the_limit_every_day_is_zus_and_no_employer_pay():
    sick = _sick(sick_ctx("0", [episode(date(2026, 3, 2), date(2026, 3, 11))], ytd_days=33))
    assert (sick["employerDays"], sick["zusDays"], sick["amount"]) == (0, 10, "0.00")


def test_the_older_limit_follows_the_signed_age_rule():
    # TEST rule FROM_YEAR_AFTER_REACHING_AGE: born 1970 -> 2026 > 1970 + 50 -> 14-day limit.
    sick = _sick(sick_ctx("800", [episode(date(2026, 3, 2), date(2026, 3, 11))], ytd_days=10, dob=date(1970, 6, 1)))
    assert (sick["employerDays"], sick["zusDays"], sick["episodes"][0]["limit"]) == (4, 6, 14)
    # AGE_AT_EPISODE_START: 49 at the episode start -> still the 33-day limit.
    at_start = build_pack({"pl_sick_age_rule": "AGE_AT_EPISODE_START"}, classes=SICK_CLASSES)
    sick = _sick(sick_ctx("2000", [episode(date(2026, 3, 2), date(2026, 3, 11))], ytd_days=10,
                          dob=date(1976, 3, 5), pack=at_start))
    assert sick["episodes"][0]["limit"] == 33 and sick["employerDays"] == 10


def test_two_episodes_share_the_yearly_limit_in_date_order():
    sick = _sick(sick_ctx("1600", [episode(date(2026, 3, 20), date(2026, 3, 25), ident=2),
                                   episode(date(2026, 3, 2), date(2026, 3, 6), ident=1)], ytd_days=25))
    first, second = sick["episodes"]
    assert (first["episodeId"], first["employerDays"]) == (1, 5)
    assert (second["episodeId"], second["employerDays"], second["zusDays"]) == (2, 3, 3)
    assert sick["amount"] == "1600.00"                                       # 8 x 250 x 80%


def test_days_are_clipped_to_the_pay_period():
    sick = _sick(sick_ctx("800", [episode(date(2026, 2, 25), date(2026, 3, 4))]))
    assert sick["episodes"][0]["from"] == "2026-03-01" and sick["employerDays"] == 4


def test_episodes_outside_the_period_or_not_approved_are_ignored():
    sick = _sick(sick_ctx("0", [episode(date(2026, 2, 1), date(2026, 2, 10)),
                                episode(date(2026, 3, 2), date(2026, 3, 5), status="DRAFT", ident=2)]))
    assert sick["status"] == "NONE"


# ── fail-closed ────────────────────────────────────────────────────────────
def test_sick_pay_without_an_episode_blocks():
    _blocks(sick_ctx("2000", []), "PL_SICKNESS_EPISODE_MISSING")


def test_sick_pay_must_equal_days_base_and_rate():
    _blocks(sick_ctx("1999", [episode(date(2026, 3, 2), date(2026, 3, 11))]), "PL_SICK_PAY_MISMATCH")


@pytest.mark.parametrize("kwargs, code", [
    ({"episodes": [episode(date(2026, 3, 2), date(2026, 3, 11), base=None)]}, "PL_BENEFIT_BASE_MISSING"),
    ({"episodes": [episode(date(2026, 3, 2), date(2026, 3, 11))], "dob": None}, "PL_FACT_MISSING:date_of_birth"),
    ({"episodes": [episode(date(2026, 3, 2), date(2026, 3, 11))], "period": (None, None)}, "PL_PERIOD_MISSING"),
    ({"episodes": [episode(date(2026, 3, 2), date(2026, 3, 11), category="FLU")]},
     "PL_SICKNESS_EPISODE_INVALID:FLU"),
])
def test_missing_or_invalid_facts_block(kwargs, code):
    episodes = kwargs.pop("episodes")
    _blocks(sick_ctx("2000", episodes, **kwargs), code)


@pytest.mark.parametrize("key", ["pl_sick_age_rule"])
def test_unsigned_sickness_policy_blocks(key):
    _blocks(sick_ctx("2000", [episode(date(2026, 3, 2), date(2026, 3, 11))],
                     pack=build_pack({key: "PENDING_G1"}, classes=SICK_CLASSES)), f"PL_POLICY_PENDING:{key}")


def test_the_shipped_unsigned_pack_never_pays_sick_pay():
    _blocks(sick_ctx("2000", [episode(date(2026, 3, 2), date(2026, 3, 11))],
                     pack=build_pack(signed=False, classes=SICK_CLASSES)), "PL_PACK_UNSIGNED")


def test_the_zus_benefit_itself_is_not_paid_here():
    classes = {**SICK_CLASSES}
    _blocks(ctx(gross="7000", components={"SALARY": Decimal("6000"), "SICKNESS_BENEFIT": Decimal("1000")},
                pack=build_pack(classes=classes)), "PL_EARNING_CLASS_REVIEW:PIT:SICKNESS_BENEFIT")


def test_no_medical_detail_reaches_the_result():
    out = calculate(sick_ctx("2000", [episode(date(2026, 3, 2), date(2026, 3, 11))]))["pl_result"]
    text = json.dumps(out, default=str)
    assert "certificate" not in text and "medical" not in text.replace("medicalDetail", "")


# ── service: episodes, restriction, retro supersession ─────────────────────
@pytest.fixture
def world(db):
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    t = make_org(db, name="Sick Org", code="PLSICK", admins=2, country="PL")
    employee = PayrollEmployee(organization_id=t.org.id, employee_code="S1", name="Anna Nowak", country_code="PL",
                               date_of_birth=date(1990, 5, 1))
    db.add(employee)
    db.commit()
    return SimpleNamespace(db=db, org=t.org.id, a=t.users[0].id, b=t.users[1].id, employee=employee)


def _episode(w, **over):
    from app.modules.payroll import poland_service as pl

    payload = {"date_from": "2026-03-02", "date_to": "2026-03-11", "category": "illness",
               "certificate_ref": "e-ZLA 123", "medical_record_ref": "HR-SAFE-9", "daily_base_amount": "250",
               "base_reference_from": "2025-03-01", "base_reference_to": "2026-02-28", "base_evidence_ref": "calc-1"}
    payload.update(over)
    row = pl.record_pl_incapacity_episode(w.db, w.org, w.employee.id, payload, w.a, "e-ZLA received")
    w.db.commit()
    return row


def test_episode_needs_evidence_and_an_evidenced_base(world):
    from app.modules.payroll import poland_service as pl

    w = world
    with pytest.raises(BadRequestException, match="certificate reference or other evidence"):
        _episode(w, certificate_ref=None)
    with pytest.raises(BadRequestException, match="reference window and evidence"):
        _episode(w, base_evidence_ref=None)
    with pytest.raises(BadRequestException, match="category"):
        _episode(w, category="FLU")
    with pytest.raises(BadRequestException, match="unknown field"):
        pl.record_pl_incapacity_episode(w.db, w.org, w.employee.id, {"diagnosis": "J10"}, w.a, "x")


def test_episode_approval_is_four_eyes_and_retro_change_supersedes(world):
    from app.modules.payroll import poland_service as pl

    w = world
    first = _episode(w)
    with pytest.raises(Exception):
        pl.approve_pl_incapacity_episode(w.db, w.org, first.id, w.a)
    pl.approve_pl_incapacity_episode(w.db, w.org, first.id, w.b)
    w.db.commit()
    retro = _episode(w, date_to="2026-03-15", supersedes_id=first.id)
    pl.approve_pl_incapacity_episode(w.db, w.org, retro.id, w.b)
    w.db.commit()
    assert (first.status, retro.status, retro.previous_version_id) == ("SUPERSEDED", "APPROVED", first.id)
    facts = pl.pl_episode_facts(w.db, w.org, w.employee.id, date(2026, 3, 31))
    assert [f["id"] for f in facts] == [retro.id] and facts[0]["date_to"] == date(2026, 3, 15)
    pl.cancel_pl_incapacity_episode(w.db, w.org, retro.id, w.a, "certificate withdrawn")
    assert pl.pl_episode_facts(w.db, w.org, w.employee.id, date(2026, 3, 31)) == []


def test_payroll_sees_only_what_calculation_needs(world):
    from app.modules.payroll import poland_service as pl

    w = world
    row = _episode(w)
    pl.approve_pl_incapacity_episode(w.db, w.org, row.id, w.b)
    w.db.commit()
    facts = pl.pl_episode_facts(w.db, w.org, w.employee.id, date(2026, 3, 31))
    assert "certificate_ref" not in facts[0] and "medical_record_ref" not in facts[0]
    restricted = pl.list_pl_incapacity_episodes(w.db, w.org, w.employee.id)[0]
    assert restricted["certificate_ref"] is None and restricted["medical_record_ref"] is None
    full = pl.list_pl_incapacity_episodes(w.db, w.org, w.employee.id, restricted=False)[0]
    assert full["certificate_ref"] == "e-ZLA 123"
    inputs = pl.calc_inputs(w.db, None, w.employee, None, as_of=date(2026, 3, 31))
    assert inputs["pl_date_of_birth"] == date(1990, 5, 1)
    assert "e-ZLA" not in json.dumps(inputs, default=str) and "HR-SAFE" not in json.dumps(inputs, default=str)


def test_episode_facts_through_the_engine_and_frozen_replay(world):
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.engine.base import PayrollContext
    from app.modules.payroll.engine.resolver import calculate_payroll

    w = world
    row = _episode(w)
    pl.approve_pl_incapacity_episode(w.db, w.org, row.id, w.b)
    w.db.commit()
    facts = pl.pl_episode_facts(w.db, w.org, w.employee.id, date(2026, 3, 31))
    context = sick_ctx("2000", facts)
    original = calculate_payroll(context, "standard")
    replayed = pl.pl_replay(json.loads(json.dumps(pl.pl_freeze_context(context))))
    assert original.pl_result["trace"]["sickness"]["amount"] == "2000.00"
    assert replayed.pl_result["hashes"] == original.pl_result["hashes"]
    assert isinstance(context, PayrollContext)


# ── migration e11c2c36df17 ─────────────────────────────────────────────────
VERSIONS = Path(__file__).resolve().parents[1] / "alembic" / "versions"


def _load(prefix):
    path = next(VERSIONS.glob(f"{prefix}_*.py"))
    spec = importlib.util.spec_from_file_location(f"rev_{prefix}", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_is_the_single_child_and_listed():
    module = _load("e11c2c36df17")
    assert (module.revision, module.down_revision) == ("e11c2c36df17", "1ee3bbde33bb")
    manifest = (VERSIONS.parent / "MIGRATIONS_MANIFEST.txt").read_text(encoding="utf-8")
    assert "e11c2c36df17_pl_incapacity_episodes.py|e11c2c36df17|1ee3bbde33bb|" in manifest
    text = next(VERSIONS.glob("e11c2c36df17_*.py")).read_text(encoding="utf-8")
    assert 'op.create_table(\n            "payroll_pl_incapacity_episodes"' in text
    for body in re.findall(r'CheckConstraint\((.*?)name=', text, re.S):
        assert set(re.findall(r"\b\d+\b", body)) <= {"0"}, body                # no statutory number
    assert not re.search(r'sa\.Column\("[a-z_]*(diagnos|icd|illness_code)', text)   # PL-017: no medical column


def test_migration_matches_the_model_and_round_trips(db):
    from alembic.operations import Operations
    from alembic.runtime.migration import MigrationContext

    from app.database import Base

    engine = db.get_bind()
    table = "payroll_pl_incapacity_episodes"
    model_cols = {c.name for c in Base.metadata.tables[table].columns}
    module = _load("e11c2c36df17")

    def run(name):
        with engine.begin() as conn:
            with Operations.context(MigrationContext.configure(conn)):
                getattr(module, name)()

    run("downgrade")
    assert table not in sa.inspect(engine).get_table_names()
    run("upgrade")
    assert {c["name"] for c in sa.inspect(engine).get_columns(table)} == model_cols
    run("upgrade")                                                          # idempotent


def test_rls_classifies_the_episode_table_as_worker_data():
    from app.database import Base
    import app.modules.payroll.models  # noqa: F401

    rls = _load("d7f9b1c3e5a6")
    metadata = Base.metadata
    cols = {n: {c.name for c in t.columns} for n, t in metadata.tables.items()}
    fks = {n: {fk.column.table.name for fk in t.foreign_keys} for n, t in metadata.tables.items()}
    rls._schema = lambda bind: (cols, fks, set(metadata.tables))
    worker, tenant = rls.classify(None)
    assert worker.get("payroll_pl_incapacity_episodes") == "org"
