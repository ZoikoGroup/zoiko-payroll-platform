"""Malaysia tax-year rollover (SQLite only): MY-PAYROLL-2026 -> MY-PAYROLL-2027
as a Draft copy — every row re-marked PENDING G1 (values prefilled), the
year-specific tables (holidays, PCB tables, authority examples) not copied,
expired rows dropped, the source pack untouched, one rollover per year, the
Super Admin action and the operator script (dry run / --apply)."""
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy.orm import sessionmaker

from app.core.exceptions import BadRequestException
from app.modules.payroll import malaysia_service as mys
from app.modules.payroll import my_super_admin as msa
from app.modules.payroll.engine.countries import malaysia_content as content
from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxConfigurationAudit, TaxSlab
from scripts import rollover_malaysia_pack as script

MARK = mys.PENDING_G1_SUFFIX.strip()
LOCAL = "sqlite:///./my_rollover_test.sqlite3"


@pytest.fixture
def source(db):
    """The 2026 Draft pack with one signed row, one EPF schedule row, one
    holiday, one row that expired in 2026 and one that started mid-2026."""
    pack = mys.seed_malaysia_pack(db)
    rate = db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id, component_key="my_min_wage_monthly",
                                                organization_id=None).one()
    rate.label = rate.label.replace(mys.PENDING_G1_SUFFIX, "")                # signed in 2026
    expired = db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id, organization_id=None) \
        .filter(ContributionRate.component_key != "my_min_wage_monthly").order_by(ContributionRate.id).first()
    expired.effective_from, expired.effective_to = date(2026, 1, 1), date(2026, 9, 30)
    mid = db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id, organization_id=None) \
        .filter(ContributionRate.id.notin_([rate.id, expired.id])).order_by(ContributionRate.id).first()
    mid.effective_from, mid.effective_to = date(2026, 6, 1), None
    for rule, label in ((content.MY_EPF_SCHEDULE_RULE, "TEST EPF band"), (content.MY_PUBLIC_HOLIDAY_RULE, "TEST holiday")):
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country="MY", rule_type=rule,
                       min_amount=Decimal("0"), max_amount=Decimal("10"), rate_pct=Decimal("0"), rate_label=label,
                       tax_formula=""))
    db.commit()
    return pack, rate.id, expired.component_key, mid.component_key


def _rows(db, pack_id):
    rates = db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack_id, organization_id=None).all()
    slabs = db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack_id, organization_id=None).all()
    return rates, slabs


def test_the_plan_is_read_only_and_names_next_year(db, source):
    pack, *_ = source
    before = db.query(JurisdictionPack).count()
    plan = mys.my_rollover_plan(db, pack)
    assert plan["refusal"] is None and plan["targetPackId"] == "MY-PAYROLL-2027"
    assert (plan["effectiveFrom"], plan["effectiveTo"]) == ("2027-01-01", "2027-12-31")
    assert plan["rates"] == len(content.MALAYSIA_SCALAR_CONTENT) - 1                     # the expired row drops
    assert plan["slabs"] == len(content.MALAYSIA_EARNING_CLASSES) + 1                    # + the EPF band, no holiday
    assert content.MY_PUBLIC_HOLIDAY_RULE in plan["notCopied"] and content.MY_PCB_TABLE_RULE in plan["notCopied"]
    assert db.query(JurisdictionPack).count() == before


def test_rollover_creates_a_pending_draft_and_leaves_the_source_alone(db, source):
    pack, signed_id, expired_key, mid_key = source
    new = mys.rollover_malaysia_pack(db, pack, None, "TEST 2027")
    db.commit()
    assert (new.pack_id, new.status, new.tax_year) == ("MY-PAYROLL-2027", "Draft", "2027")
    assert (new.effective_from, new.effective_to) == (date(2027, 1, 1), date(2027, 12, 31))
    rates, slabs = _rows(db, new.id)
    assert all(r.label.endswith(MARK) and r.label.count(MARK) == 1 for r in rates)    # every row re-pended
    assert all(s.rate_label.endswith(MARK) for s in slabs)
    by_key = {(r.component_key, r.jurisdiction_state): r for r in rates}
    old_signed = db.get(ContributionRate, signed_id)
    assert not old_signed.label.endswith(MARK)                                          # source untouched
    copied = by_key[("my_min_wage_monthly", old_signed.jurisdiction_state)]
    assert copied.flat_amount == old_signed.flat_amount and copied.source_document_id == old_signed.source_document_id
    assert expired_key not in {k for k, _s in by_key}
    assert next(r for (k, _s), r in by_key.items() if k == mid_key).effective_from == date(2027, 1, 1)
    kinds = {s.rule_type for s in slabs}
    assert content.MY_EPF_SCHEDULE_RULE in kinds and content.MY_PUBLIC_HOLIDAY_RULE not in kinds
    assert db.get(JurisdictionPack, pack.id).status == "Draft" and len(_rows(db, pack.id)[1]) == len(slabs) + 1
    audit = db.query(TaxConfigurationAudit).filter_by(jurisdiction_pack_id=new.id, action="create").one()
    assert "TEST 2027" in audit.reason and "not copied" in audit.reason


def test_one_rollover_per_year_and_the_new_pack_cannot_activate(db, source):
    pack, *_ = source
    new = mys.rollover_malaysia_pack(db, pack)
    db.commit()
    assert "already exists" in mys.my_rollover_plan(db, pack)["refusal"]
    with pytest.raises(BadRequestException, match="already exists"):
        mys.rollover_malaysia_pack(db, pack)
    assert "unsigned" in mys.my_pack_activation_refusal(db, new)


def test_only_dated_malaysia_tax_packs_roll_over(db, source):
    pack, *_ = source
    pack.effective_to = None
    assert "no end date" in mys.my_rollover_plan(db, pack)["refusal"]
    other = JurisdictionPack(pack_id="PL-PAYROLL-2026", version="1.0", jurisdiction_country="PL", pack_type="tax",
                             status="Draft", effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    assert "Only a Malaysia tax pack" in mys.my_rollover_plan(db, other)["refusal"]


def test_payroll_dates_bind_to_the_right_year_and_2027_fails_closed_until_active(db, source):
    from app.modules.payroll.engine.tax_resolver import _find_active_tax_pack

    pack, *_ = source
    new = mys.rollover_malaysia_pack(db, pack)
    pack.status = "Active"
    db.commit()
    assert _find_active_tax_pack(db, "MY", None, None, date(2026, 12, 15)).id == pack.id
    assert _find_active_tax_pack(db, "MY", None, None, date(2027, 1, 15)) is None      # Draft 2027: no fallback
    new.status = "Active"
    db.commit()
    assert _find_active_tax_pack(db, "MY", None, None, date(2027, 1, 15)).id == new.id
    assert _find_active_tax_pack(db, "MY", None, None, date(2026, 12, 15)).id == pack.id


# ── Super Admin console ─────────────────────────────────────────────────────
def test_console_rollover_needs_a_reason_and_is_audited(db, source):
    pack, *_ = source
    assert msa.rollover_plan(db, pack.id)["targetPackId"] == "MY-PAYROLL-2027"
    with pytest.raises(BadRequestException, match="reason"):
        msa.rollover(db, pack.id, {"reason": " "}, 7)
    out = msa.rollover(db, pack.id, {"reason": "Start 2027"}, 7)
    db.commit()
    assert out["created"]["packId"] == "MY-PAYROLL-2027" and out["created"]["status"] == "Draft"
    assert [p["packId"] for p in out["packs"]] == ["MY-PAYROLL-2026", "MY-PAYROLL-2027"]
    audit = db.query(TaxConfigurationAudit).filter_by(jurisdiction_pack_id=out["created"]["id"], actor_id=7).one()
    assert "Start 2027" in audit.reason


def test_rollover_routes_are_super_admin_only():
    from app.modules.super_admin import router as sa

    routes = [r for r in sa.router.routes if getattr(r, "path", "").endswith("/compliance/malaysia/packs/{pack_row_id}/rollover")]
    assert {m for r in routes for m in r.methods} == {"GET", "POST"}
    for route in routes:
        assert "get_current_super_admin" in {d.call.__name__ for d in route.dependant.dependencies}


# ── operator script ─────────────────────────────────────────────────────────
@pytest.fixture()
def run(db, monkeypatch, capsys):
    import app.database as database

    factory = sessionmaker(bind=db.get_bind(), autoflush=False, autocommit=False)
    monkeypatch.setattr(database, "SessionLocal", factory)
    monkeypatch.setattr(database, "initialize_database", lambda: None)
    monkeypatch.delenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", raising=False)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("PAYROLL_DATABASE_URL", LOCAL)

    def go(*argv):
        try:
            code = script.main(list(argv))
        except SystemExit as exc:
            code = exc.code
        db.expire_all()
        return code, capsys.readouterr()

    return go


def _2027(db):
    return db.query(JurisdictionPack).filter_by(pack_id="MY-PAYROLL-2027").all()


def test_script_dry_run_then_apply_then_refuses(db, source, run):
    code, out = run("--from", "MY-PAYROLL-2026")
    assert code == 0 and "dry run — nothing written" in out.out and "MY-PAYROLL-2027" in out.out and _2027(db) == []
    code, out = run("--from", "MY-PAYROLL-2026", "--apply")
    assert code == 0 and "created MY-PAYROLL-2027" in out.out and _2027(db)[0].status == "Draft"
    code, out = run("--from", "MY-PAYROLL-2026", "--apply")
    assert code == 2 and "already exists" in out.out and len(_2027(db)) == 1
    assert run("--from", "MY-PAYROLL-1999")[0] == 2


def test_script_apply_refuses_a_remote_database(db, source, run, monkeypatch):
    monkeypatch.setenv("PAYROLL_DATABASE_URL", "postgresql://u:pw@db.example-remote.net:5432/prod")
    code, out = run("--from", "MY-PAYROLL-2026", "--apply")
    assert code == 2 and "REFUSING" in out.err and _2027(db) == []
