"""Tax year vs. effective dates (tax_year_rules) and its use in
upsert_jurisdiction_pack: checked on create, and on an edit only when the tax
year or a date changes — an existing record is never refused for a value it
already holds, and nothing is altered. The case table is shared with the
frontend form (frontend/src/components/jurisdiction/taxYear.js).
SYNTHETIC data only."""
import json
from datetime import date
from pathlib import Path

import pytest

CASES = json.loads((Path(__file__).parent / "data" / "tax_year_cases.json").read_text(encoding="utf-8"))["cases"]
_d = lambda s: date.fromisoformat(s) if s else None


@pytest.mark.parametrize("case", CASES, ids=[f"{c['taxYear']}|{c['from']}|{c['to']}" for c in CASES])
def test_shared_case_table(case):
    from app.modules.payroll.tax_year_rules import tax_year_date_refusal

    refusal = tax_year_date_refusal(case["taxYear"], _d(case["from"]), _d(case["to"]))
    assert (refusal is None) == case["ok"], (case["why"], refusal)


def test_parse_forms():
    from app.modules.payroll.tax_year_rules import parse_tax_year

    assert parse_tax_year("2026") == (2026,)
    assert parse_tax_year("2026-27") == parse_tax_year("2026-2027") == parse_tax_year("2026/27") == (2026, 2027)
    assert parse_tax_year("2099-00") == (2099, 2100)
    assert parse_tax_year("FY2026") is None and parse_tax_year("") is None and parse_tax_year(None) is None
    assert parse_tax_year("2026-07") is None and parse_tax_year("2026-2028") is None   # not next-year splits


def test_message_names_the_fix():
    from app.modules.payroll.tax_year_rules import tax_year_date_refusal

    msg = tax_year_date_refusal("2027-2028", date(2027, 1, 1), date(2027, 12, 31))
    assert msg == ('Tax year "2027-2028" spans two years, but this pack\'s dates (2027-01-01 → 2027-12-31) '
                   "fall within 2027. Use the single year 2027.")


# ── upsert_jurisdiction_pack ─────────────────────────────────────────────────
def _payload(**over):
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    base = dict(packId="TY-TEST", version="1.0", jurisdictionCountry="DE", packType="tax", status="Draft",
                effectiveFrom=date(2027, 1, 1), effectiveTo=date(2027, 12, 31), taxYear="2027")
    base.update(over)
    return JurisdictionPackUpsert(**base)


def test_create_refuses_a_split_year_on_a_calendar_year_pack(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    with pytest.raises(BadRequestException) as exc:
        service.upsert_jurisdiction_pack(db, _payload(taxYear="2027-2028"))
    assert "Use the single year 2027" in exc.value.message
    assert service.upsert_jurisdiction_pack(db, _payload()).tax_year == "2027"


def test_create_checks_open_ended_packs(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service

    with pytest.raises(BadRequestException):
        service.upsert_jurisdiction_pack(db, _payload(packId="TY-OPEN-1", effectiveTo=None, taxYear="2026"))
    ok = service.upsert_jurisdiction_pack(db, _payload(packId="TY-OPEN-2", effectiveTo=None, taxYear="2027-28"))
    assert ok.tax_year == "2027-28"


def _legacy_bad_pack(db):
    """A record stored before the rule existed (BE-PAYROLL-2027's shape)."""
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id="TY-LEGACY", version="1.0", jurisdiction_country="DE", pack_type="tax",
                            status="Draft", effective_from=date(2027, 1, 1), effective_to=date(2027, 12, 31),
                            tax_year="2027-2028")
    db.add(pack)
    db.commit()
    return pack


def test_editing_other_fields_never_refuses_an_existing_record(db):
    from app.modules.payroll import service
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    pack = _legacy_bad_pack(db)
    edited = service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(
        id=pack.id, packId="TY-LEGACY", version="1.0", jurisdictionCountry="DE", packType="tax", status="Draft",
        changeSummary="unrelated edit"))
    assert edited.change_summary == "unrelated edit" and edited.tax_year == "2027-2028"   # untouched, not altered


def test_an_edit_that_changes_the_tax_year_or_dates_is_checked(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import service
    from app.modules.payroll.schemas import JurisdictionPackUpsert

    pack = _legacy_bad_pack(db)
    common = dict(id=pack.id, packId="TY-LEGACY", version="1.0", jurisdictionCountry="DE", packType="tax",
                  status="Draft")
    with pytest.raises(BadRequestException):          # moving the dates keeps the bad tax year: refused
        service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(**common, effectiveTo=date(2027, 11, 30)))
    db.rollback()
    with pytest.raises(BadRequestException):          # another wrong value: refused
        service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(**common, taxYear="2026"))
    db.rollback()
    fixed = service.upsert_jurisdiction_pack(db, JurisdictionPackUpsert(**common, taxYear="2027"))
    assert fixed.tax_year == "2027"                   # the correction itself is accepted
