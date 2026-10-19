"""Brazil (ZP-BR-ENG-001) Phase 1 — statutory content transcribed from saved
official sources, the year guard, the full-content hash, and the Draft
canonical-pack seeder (in-memory SQLite only).

`app.*` is imported inside each test (never at module level) so collecting
this file cannot bind the app to the .env database before conftest's
in-memory SQLite fixture is in place."""

import csv
import hashlib
import shutil
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

SOURCES_DIR = Path(__file__).resolve().parents[2] / "docs" / "brazil" / "sources"
MANIFEST = SOURCES_DIR / "SOURCES_MANIFEST.csv"


def _manifest_rows():
    with open(MANIFEST, encoding="utf-8", newline="") as fh:
        return {row["code"]: row for row in csv.DictReader(fh)}


# ── evidence ────────────────────────────────────────────────────────────────

def test_every_cited_source_is_saved_verified_and_unchanged():
    from app.modules.payroll.engine.countries import brazil_content as c

    rows = _manifest_rows()
    for code in sorted(c.cited_sources()):
        assert code in rows, f"{code} cited but not in the manifest"
        row = rows[code]
        assert row["status"] == "VERIFIED", f"{code} is {row['status']}"
        data = (SOURCES_DIR / row["file"]).read_bytes()
        assert hashlib.sha256(data).hexdigest() == row["sha256"], f"{code} file changed since it was verified"
        assert int(row["bytes"]) == len(data)
        assert row["url"].startswith("https://www.gov.br/") or row["url"].startswith("https://www.planalto.gov.br/")


def test_manifest_codes_are_registered_sources():
    from app.modules.payroll.engine.countries import brazil_content as c

    assert set(_manifest_rows()) <= set(c.ALL_SOURCE_CODES)


# ── content rows ────────────────────────────────────────────────────────────

def test_rows_are_dated_sourced_and_percent_not_fraction():
    from app.modules.payroll.engine.countries import brazil_content as c

    assert c.BR_CONTENT_ROWS
    for row in c.BR_CONTENT_ROWS:
        assert row.rule_type in c.BR_SLAB_RULES and row.rule_type.startswith("BR_")
        assert row.source in c.ALL_SOURCE_CODES
        assert row.effective_from == date(2026, 1, 1) and row.effective_to == date(2026, 12, 31)
        if row.rate_pct is not None:
            assert row.rate_pct == 0 or row.rate_pct >= 1, f"{row.key}: {row.rate_pct} looks like a fraction"


def test_values_match_the_saved_sources():
    from app.modules.payroll.engine.countries import brazil_content as c

    on = date(2026, 6, 15)
    bands = [(r.min_amount, r.max_amount, r.rate_pct) for r in c.rows_in_force(c.BR_INSS_BAND_RULE, on)]
    assert bands == [(Decimal("0.00"), Decimal("1621.00"), Decimal("7.5")),
                     (Decimal("1621.00"), Decimal("2902.84"), Decimal("9")),
                     (Decimal("2902.84"), Decimal("4354.27"), Decimal("12")),
                     (Decimal("4354.27"), Decimal("8475.55"), Decimal("14"))]                       # S1
    assert [t[3] for t in c.IRRF_2026_TABLE] == [Decimal(x) for x in ("0.00", "182.16", "394.16", "675.49", "908.73")]
    assert (c.IRRF_DEPENDENT_DEDUCTION, c.IRRF_SIMPLIFIED_MONTHLY_DEDUCTION) == (Decimal("189.59"), Decimal("607.20"))
    assert (c.IRRF_2026_REDUCTION_A, c.IRRF_2026_REDUCTION_B) == (Decimal("978.62"), Decimal("0.133145"))  # A1
    assert (c.MINIMUM_WAGE_MONTHLY, c.MINIMUM_WAGE_DAILY, c.MINIMUM_WAGE_HOURLY) == (
        Decimal("1621.00"), Decimal("54.04"), Decimal("7.37"))                                          # S4
    assert (c.SALARIO_FAMILIA_CEILING, c.SALARIO_FAMILIA_QUOTA) == (Decimal("1980.38"), Decimal("67.54"))  # S5
    assert (c.FGTS_ORDINARY_RATE, c.FGTS_APPRENTICE_RATE) == (Decimal("0.08"), Decimal("0.02"))            # A3
    assert (c.STANDARD_CPP_RATE, c.FINANCIAL_SECTOR_CPP_ADDON) == (Decimal("0.2"), Decimal("0.025"))      # A2
    assert (c.CPRB_2026_CPP_RATE, c.CPRB_2026_REVENUE_FACTOR) == (Decimal("0.1"), Decimal("0.6"))         # S8


def test_inss_maximum_is_derived_not_stored():
    from app.modules.payroll.engine.countries import brazil_content as c

    assert c.MAX_INSS_CONTRIBUTION == c.inss_maximum() == c.PUBLISHED_INSS_MAXIMUM_2026 == Decimal("988.09")
    assert sum(b[3] for b in c.INSS_2026_BRACKETS) == Decimal("988.0914")       # exact, rounded once


@pytest.mark.parametrize("outside", [date(2025, 12, 31), date(2027, 1, 1)])
def test_a_date_outside_the_content_blocks(outside):
    from app.modules.payroll.engine.countries import brazil_content as c

    with pytest.raises(c.BrazilContentMissing, match="BR_CONTENT_YEAR_UNAVAILABLE"):
        c.rows_in_force(c.BR_INSS_BAND_RULE, outside)
    with pytest.raises(c.BrazilContentMissing):
        c.row_in_force(c.BR_MIN_WAGE_RULE, "MONTHLY", outside)
    assert c.row_in_force(c.BR_MIN_WAGE_RULE, "MONTHLY", date(2026, 12, 31)).flat_amount == Decimal("1621.00")


def test_content_hash_covers_every_row_and_rubric():
    from app.modules.payroll.engine.countries import brazil_content as c

    payload = c.content_payload()
    assert c.calculate_content_hash(payload) == c.CONTENT_HASH == c.calculate_content_hash()
    assert len(payload["rows"]) == len(c.BR_CONTENT_ROWS) and len(payload["rubrics"]) == 14
    changed_row = c.content_payload()
    changed_row["rows"][0]["rate_pct"] = "7.6"
    changed_rubric = c.content_payload()
    changed_rubric["rubrics"][0]["cod_inc_irrf"] = "00"
    assert c.calculate_content_hash(changed_row) != c.CONTENT_HASH
    assert c.calculate_content_hash(changed_rubric) != c.CONTENT_HASH


# ── seeder (in-memory SQLite) ────────────────────────────────────────────────

def _seed(db, **kwargs):
    from scripts.seed_brazil_canonical_packs import seed_brazil

    out = seed_brazil(db, **kwargs)
    db.commit()
    return out


def test_seed_creates_a_draft_pack_with_every_row_sourced(db):
    from app.modules.billing.models import JurisdictionServiceRegistry
    from app.modules.payroll.engine.countries import brazil_content as c
    from app.modules.payroll.models import JurisdictionPack, SourceArtifact, TaxSlab

    out = _seed(db)
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == "BR-PAYROLL-2026").one()
    assert (pack.status, pack.jurisdiction_country, pack.pack_type, pack.currency) == ("Draft", "BR", "tax", "BRL")
    assert (pack.effective_from, pack.effective_to) == (date(2026, 1, 1), date(2026, 12, 31))
    assert c.CONTENT_HASH in pack.change_summary and pack.source_document_id is not None
    slabs = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id).all()
    assert out["tax_slabs"] == len(slabs) == len(c.BR_CONTENT_ROWS)
    assert all(s.organization_id is None and s.source_document_id and c.PENDING_G1 in s.rate_label for s in slabs)
    assert {s.rule_type for s in slabs} == set(c.BR_SLAB_RULES)
    assert db.query(SourceArtifact).count() == len(c.cited_sources())
    registry = db.query(JurisdictionServiceRegistry).filter(JurisdictionServiceRegistry.country == "BR").one()
    assert registry.availability == "PLANNED"


def test_seed_is_rerunnable_without_duplicates(db):
    from app.modules.payroll.models import JurisdictionPack, SourceArtifact, TaxSlab

    _seed(db)
    first = (db.query(TaxSlab).count(), db.query(SourceArtifact).count())
    _seed(db)
    assert (db.query(TaxSlab).count(), db.query(SourceArtifact).count()) == first
    assert db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "BR").count() == 1


def test_seed_refuses_a_pack_that_left_draft(db):
    from app.modules.payroll.models import JurisdictionPack

    _seed(db)
    pack = db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == "BR-PAYROLL-2026").one()
    pack.status = "Approved"
    db.commit()
    with pytest.raises(SystemExit, match="not Draft"):
        _seed(db)


def test_seed_refuses_an_unverified_source(db):
    from scripts.seed_brazil_canonical_packs import load_manifest

    manifest = load_manifest()
    manifest.pop("S2")
    with pytest.raises(SystemExit, match="S2"):
        _seed(db, manifest=manifest)


def test_seed_refuses_a_source_file_that_changed(db, tmp_path):
    for f in SOURCES_DIR.iterdir():
        shutil.copyfile(f, tmp_path / f.name)
    s4 = next(r for r in _manifest_rows().values() if r["code"] == "S4")
    (tmp_path / s4["file"]).write_bytes((tmp_path / s4["file"]).read_bytes() + b"<!-- tampered -->")
    with pytest.raises(SystemExit, match="no longer matches"):
        _seed(db, sources_dir=tmp_path)


def test_seeded_draft_pack_is_not_served_as_active(db):
    """The Super Admin pack-rows view only ever shows an ACTIVE pack."""
    from tests.test_hong_kong_governance import _http
    from types import SimpleNamespace

    _seed(db)
    sa = SimpleNamespace(id=981, organization_id=None, role="super_admin", is_active=True)
    with _http(db, sa) as client:
        body = client.get("/api/super-admin/compliance/brazil/pack-rows",
                          params={"rule_type": "BR_INSS_BAND", "on": "2026-07-31"}).json()
    assert body["packId"] is None and body["rows"] == []


def test_seed_script_refuses_without_the_override(monkeypatch):
    from scripts import seed_brazil_canonical_packs as seed

    monkeypatch.delenv("ZOIKO_ALLOW_NONLOCAL_DB_WRITES", raising=False)
    with pytest.raises(SystemExit) as exc:
        seed._require_confirmed_target()
    assert exc.value.code == 2
