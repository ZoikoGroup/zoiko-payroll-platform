"""scripts/backfill_pack_metadata.py: fills empty descriptive fields on packs (Active included) from the
checked-in value table, applies only the listed corrections, and never touches anything else.
SYNTHETIC packs only; the real value table is checked for shape and column lengths."""
import csv
import datetime as dt

import pytest

from scripts import backfill_pack_metadata as bf


def _pack(db, pack_id="XX-PAYROLL-2026", version="1.0", status="Active", country="XX", **fields):
    from app.modules.payroll.models import JurisdictionPack

    pack = JurisdictionPack(pack_id=pack_id, version=version, status=status, jurisdiction_country=country,
                            pack_type="tax", effective_from=dt.date(2026, 1, 1), effective_to=dt.date(2026, 12, 31),
                            tax_regime="new", tax_year="2026", **fields)
    db.add(pack)
    db.commit()
    return pack


def _row(field, value, mode="fill", expected_old="", pack_id="XX-PAYROLL-2026", version="1.0", country="XX"):
    return {"pack_id": pack_id, "version": version, "country": country, "state": "", "field": field,
            "mode": mode, "expected_old": expected_old, "value": value, "basis": "test"}


def _write(tmp_path, rows):
    path = tmp_path / "values.csv"
    with open(path, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return path


def _audits(db, pack):
    from app.modules.payroll.models import TaxConfigurationAudit

    return db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "jurisdiction_pack",
                                                  TaxConfigurationAudit.entity_id == pack.id).all()


def test_checked_in_value_table_is_valid():
    """Allowed fields only, fits every column (Postgres enforces String(n), SQLite does not), no duplicates."""
    rows = bf.load_rows()
    assert len(rows) > 600
    assert {r["field"] for r in rows} <= set(bf.ALLOWED_FIELDS)
    assert {r["mode"] for r in rows} == {"fill", "correct"}
    assert all(isinstance(r["value"], dt.date) for r in rows if r["field"] == "next_review_date")
    corrections = [r for r in rows if r["mode"] == "correct"]
    assert corrections and all(r["expected_old"] for r in corrections)
    assert not any(r["value"].startswith("ZP-TAX-") for r in rows if r["field"] == "regulatory_authority")


def test_dry_run_writes_nothing(db, tmp_path):
    pack = _pack(db)
    rows = bf.load_rows(_write(tmp_path, [_row("regulatory_authority", "Test Revenue Authority")]))
    report = bf.plan_and_apply(db, rows, actor_id=None, apply=False)
    db.rollback()
    assert report["packs"][0]["changed"] == ["regulatory_authority"]
    db.refresh(pack)
    assert pack.regulatory_authority is None and _audits(db, pack) == []


def test_fills_empty_fields_on_an_active_pack_and_audits_once(db, tmp_path):
    pack = _pack(db, compliance_owner="")                                   # blank counts as empty
    rows = bf.load_rows(_write(tmp_path, [
        _row("regulatory_authority", "Test Revenue Authority"),
        _row("compliance_owner", "Zoiko Groups"),
        _row("next_review_date", "2026-12-01"),
    ]))
    bf.plan_and_apply(db, rows, actor_id=None, apply=True)
    db.commit()
    db.refresh(pack)
    assert pack.regulatory_authority == "Test Revenue Authority"
    assert pack.compliance_owner == "Zoiko Groups"
    assert pack.next_review_date == dt.date(2026, 12, 1)
    assert pack.status == "Active"                                           # lifecycle untouched
    audits = _audits(db, pack)
    assert len(audits) == 1
    assert audits[0].old_value == {"regulatory_authority": None, "compliance_owner": "", "next_review_date": None}
    assert audits[0].new_value["next_review_date"] == "2026-12-01"
    assert "owner-approved" in audits[0].reason


def test_fill_never_overwrites_an_existing_value(db, tmp_path):
    pack = _pack(db, regulatory_authority="Set By An Admin")
    rows = bf.load_rows(_write(tmp_path, [_row("regulatory_authority", "Test Revenue Authority")]))
    report = bf.plan_and_apply(db, rows, actor_id=None, apply=True)
    db.commit()
    db.refresh(pack)
    assert pack.regulatory_authority == "Set By An Admin"
    assert report["packs"][0]["kept"] == ["regulatory_authority"] and _audits(db, pack) == []


def test_correction_only_when_the_old_value_still_matches(db, tmp_path):
    a = _pack(db, regulatory_authority="HMRS")
    b = _pack(db, pack_id="YY-PAYROLL-2026", country="YY", regulatory_authority="Edited since")
    rows = bf.load_rows(_write(tmp_path, [
        _row("regulatory_authority", "HM Revenue & Customs (HMRC)", mode="correct", expected_old="HMRS"),
        _row("regulatory_authority", "HM Revenue & Customs (HMRC)", mode="correct", expected_old="HMRS",
             pack_id="YY-PAYROLL-2026", country="YY"),
    ]))
    report = bf.plan_and_apply(db, rows, actor_id=None, apply=True)
    db.commit()
    db.refresh(a), db.refresh(b)
    assert a.regulatory_authority == "HM Revenue & Customs (HMRC)"
    assert b.regulatory_authority == "Edited since"
    assert [e["mismatch"] for e in report["packs"]] == [[], ["regulatory_authority"]]


def test_date_correction_compares_dates(db, tmp_path):
    pack = _pack(db, next_review_date=dt.date(2026, 1, 15))
    rows = bf.load_rows(_write(tmp_path, [
        _row("next_review_date", "2027-03-06", mode="correct", expected_old="2026-01-15")]))
    report = bf.plan_and_apply(db, rows, actor_id=None, apply=True)
    db.commit()
    db.refresh(pack)
    assert pack.next_review_date == dt.date(2027, 3, 6) and report["packs"][0]["changed"] == ["next_review_date"]
    assert _audits(db, pack)[0].old_value == {"next_review_date": "2026-01-15"}


def test_never_touches_other_columns(db, tmp_path):
    pack = _pack(db)
    before = {c.name: getattr(pack, c.key) for c in pack.__table__.c
              if c.name not in ("regulatory_authority", "updated_at", "updated_by_id")}
    rows = bf.load_rows(_write(tmp_path, [_row("regulatory_authority", "Test Revenue Authority")]))
    bf.plan_and_apply(db, rows, actor_id=None, apply=True)
    db.commit()
    db.refresh(pack)
    assert {c.name: getattr(pack, c.key) for c in pack.__table__.c if c.name in before} == before


@pytest.mark.parametrize("field,value,message", [
    ("effective_from", "2026-01-01", "not an allowed descriptive field"),
    ("tax_regime", "old", "not an allowed descriptive field"),
    ("status", "Draft", "not an allowed descriptive field"),
    ("regulatory_authority", "x" * 201, "column allows 200"),
    ("next_review_date", "soon", "not an ISO date"),
])
def test_value_table_rejects_unsafe_rows(tmp_path, field, value, message):
    with pytest.raises(bf.ValueTableError, match=message):
        bf.load_rows(_write(tmp_path, [_row(field, value)]))


def test_country_filter_and_idempotent_rerun(db, tmp_path):
    a = _pack(db)
    b = _pack(db, pack_id="YY-PAYROLL-2026", country="YY")
    rows = bf.load_rows(_write(tmp_path, [
        _row("currency", "EUR"),
        _row("currency", "SAR", pack_id="YY-PAYROLL-2026", country="YY"),
    ]))
    bf.plan_and_apply(db, rows, countries=["yy"], actor_id=None, apply=True)
    db.commit()
    db.refresh(a), db.refresh(b)
    assert (a.currency, b.currency) == (None, "SAR")
    again = bf.plan_and_apply(db, rows, countries=["YY"], actor_id=None, apply=True)
    assert again["packs"][0]["changed"] == [] and again["packs"][0]["already"] == ["currency"]


def test_apply_is_one_transaction(db, tmp_path):
    pack = _pack(db)
    rows = bf.load_rows(_write(tmp_path, [_row("regulatory_authority", "Test Revenue Authority")]))
    bf.plan_and_apply(db, rows, actor_id=None, apply=True)
    db.rollback()                                                      # what main() does on an error
    db.refresh(pack)
    assert pack.regulatory_authority is None and _audits(db, pack) == []


def test_missing_pack_is_reported(db, tmp_path):
    rows = bf.load_rows(_write(tmp_path, [_row("currency", "EUR", pack_id="NOPE")]))
    assert bf.plan_and_apply(db, rows, actor_id=None, apply=False)["missing"] == ["NOPE v1.0"]


def test_apply_refuses_a_remote_database(monkeypatch):
    monkeypatch.setenv("PAYROLL_DATABASE_URL", "postgresql://u:p@db.example-remote.net/zoiko")
    monkeypatch.delenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", raising=False)
    with pytest.raises(SystemExit):
        bf.main(["--apply", "--actor-id", "17"])
