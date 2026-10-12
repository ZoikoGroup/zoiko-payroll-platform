"""
tests/test_switzerland_qst_ingestion.py
---------------------------------------
CH Step 4 — governed QST tariff ingestion (switzerland_service): SHA-256
dedupe, parser selection by format_version, structural validation, maker-
checker approve/activate, supersession, row immutability, replay of a
superseded file by id, and band-boundary lookup.

Every tariff here is SYNTHETIC (tests/fixtures/ch_qst/synthetic_zh_v1.txt and
variants built by _record) — invented bands and rates in the provisional
ESTV_FIXED_WIDTH_V1 layout, never real ESTV data.
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from tests.test_hong_kong_governance import SA_A, SA_B, _http

FIXTURE = (Path(__file__).parent / "fixtures" / "ch_qst" / "synthetic_zh_v1.txt").read_bytes()
META = {"format_version": "ESTV_FIXED_WIDTH_V1", "effective_from": date(2026, 1, 1),
        "effective_to": date(2026, 12, 31), "tax_year": 2026}
SA_C = type(SA_A)(id=303, organization_id=None, role="super_admin", is_active=True)


def _record(code, children, inc_from, step, min_tax, rate, canton="ZH", valid_from="20260101"):
    return ("06" + "01" + canton + code.ljust(10) + valid_from + f"{int(inc_from * 100):09d}"
            + f"{int(step * 100):09d}" + " " + f"{children:02d}" + f"{int(min_tax * 100):09d}"
            + f"{int(round(rate * 100)):05d}")


def _file(*records) -> bytes:
    return ("\n".join(records) + "\n").encode("latin-1")


def _import(db, data=FIXTURE, canton="CH-ZH", actor=SA_A, **meta):
    from app.modules.payroll import switzerland_service as svc

    return svc.import_qst_tariff_file(db, canton, data, {**META, **meta}, actor.id)


def _active(db, data=FIXTURE, importer=SA_A, approver=SA_B, activator=SA_A, **meta):
    from app.modules.payroll import switzerland_service as svc

    f = _import(db, data, actor=importer, **meta)
    assert svc.validate_qst_tariff_file(db, f["id"], importer.id)["status"] == "VALIDATED"
    svc.approve_qst_tariff_file(db, f["id"], approver.id)
    return svc.activate_qst_tariff_file(db, f["id"], activator.id)


def _audits(db, file_id):
    from app.modules.payroll.models import TaxConfigurationAudit

    return [a.action for a in db.query(TaxConfigurationAudit)
            .filter(TaxConfigurationAudit.entity_type == "ch_qst_tariff_file", TaxConfigurationAudit.entity_id == file_id)
            .order_by(TaxConfigurationAudit.id)]


# ── import / checksum dedupe ────────────────────────────────────────────

def test_import_stores_sha256_rows_as_parsed_and_is_audited(db):
    import hashlib

    from app.modules.payroll.models import ChQstTariffRow

    f = _import(db)
    assert f["status"] == "IMPORTED" and f["canton"] == "CH-ZH" and f["rowCount"] == 9
    assert f["fileSha256"] == hashlib.sha256(FIXTURE).hexdigest() and f["importedById"] == SA_A.id
    assert f["validationReport"]["import"]["validFromDates"] == ["2026-01-01"]
    rows = db.query(ChQstTariffRow).filter(ChQstTariffRow.tariff_file_id == f["id"]).all()
    a0y = sorted((r for r in rows if r.tariff_code == "A" and r.church_tax), key=lambda r: r.income_from)
    assert [(r.income_from, r.income_to, r.rate_pct, r.min_tax) for r in a0y] == [
        (Decimal("0"), Decimal("1000"), Decimal("0"), Decimal("0")),
        (Decimal("1000"), Decimal("2000"), Decimal("1.5"), Decimal("10")),
        (Decimal("2000"), None, Decimal("5.5"), Decimal("25")),
    ]
    assert all(r.raw_record.startswith("0601ZH") for r in rows)
    assert _audits(db, f["id"]) == ["import"]


def test_identical_file_is_refused_even_after_rejection_and_nothing_is_stored(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import switzerland_service as svc
    from app.modules.payroll.models import ChQstTariffFile, ChQstTariffRow

    f = _import(db)
    with pytest.raises(BadRequestException, match=f"already imported for CH-ZH as tariff file {f['id']}"):
        _import(db, actor=SA_B)
    gap = _file(_record("A0N", 0, 0, 1000, 0, 0), _record("A0N", 0, 1500, 0, 0, 2))
    g = _import(db, gap)
    assert svc.validate_qst_tariff_file(db, g["id"], SA_A.id)["status"] == "REJECTED"
    with pytest.raises(BadRequestException, match="already imported"):
        _import(db, gap)
    assert db.query(ChQstTariffFile).count() == 2 and db.query(ChQstTariffRow).count() == 11


def test_parser_is_selected_by_format_version_and_unreadable_files_store_nothing(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import ChQstTariffFile

    with pytest.raises(BadRequestException, match="no parser for format_version 'CSV_V9'"):
        _import(db, format_version="CSV_V9")
    with pytest.raises(BadRequestException, match="canton must be one of"):
        _import(db, canton="ZH")
    with pytest.raises(BadRequestException, match="record canton 'BE' is not 'ZH'"):
        _import(db, _file(_record("A0N", 0, 0, 0, 0, 1, canton="BE")))
    with pytest.raises(BadRequestException, match="disagrees with children field"):
        _import(db, _file(_record("B2N", 1, 0, 0, 0, 1)))
    with pytest.raises(BadRequestException, match="unknown record type"):
        _import(db, b"07garbage\n")
    with pytest.raises(BadRequestException, match="no tariff records"):
        _import(db, b"00header only\n99\n")
    with pytest.raises(BadRequestException, match="effective_to is before"):
        _import(db, effective_to=date(2025, 1, 1))
    assert db.query(ChQstTariffFile).count() == 0


# ── validation ──────────────────────────────────────────────────────────

def test_validation_passes_the_synthetic_fixture_and_stores_the_report(db):
    from app.modules.payroll import switzerland_service as svc

    f = _import(db)
    out = svc.validate_qst_tariff_file(db, f["id"], SA_B.id)
    report = out["validationReport"]["validation"]
    assert out["status"] == "VALIDATED" and report["errors"] == [] and report["groupCount"] == 3
    assert report["validatedById"] == SA_B.id and "no_gaps" in report["checks"]
    assert "import" in out["validationReport"]                           # the import summary is kept
    assert _audits(db, f["id"]) == ["import", "validate"]


@pytest.mark.parametrize("records, expected", [
    ((_record("A0N", 0, 0, 1000, 0, 0), _record("A0N", 0, 1500, 0, 0, 2)), "gap between 1000"),
    ((_record("A0N", 0, 0, 1000, 0, 0), _record("A0N", 0, 500, 0, 0, 2)), "overlap"),
    ((_record("A0N", 0, 0, 1000, 0, 0), _record("A0N", 0, 0, 0, 0, 2)), "duplicate band start"),
    ((_record("A0N", 0, 0, 0, 0, 1), _record("A0N", 0, 1000, 0, 0, 2)), "open-ended band at 0"),
    ((_record("A0N", 0, 100, 0, 0, 1),), "first band starts at 100"),
    ((_record("A0N", 0, 0, 0, 0, 101),), "outside 0..100"),
    ((_record("A0N", 0, 0, 0, 0, 1, valid_from="20250101"),), "disagree with effective_from"),
])
def test_structurally_unsound_files_are_rejected_with_the_reason(db, records, expected):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import switzerland_service as svc

    f = _import(db, _file(*records))
    out = svc.validate_qst_tariff_file(db, f["id"], SA_A.id)
    assert out["status"] == "REJECTED"
    assert any(expected in e for e in out["validationReport"]["validation"]["errors"])
    with pytest.raises(BadRequestException, match="only a VALIDATED tariff file can be approved"):
        svc.approve_qst_tariff_file(db, f["id"], SA_B.id)


def test_bands_are_checked_per_code_children_and_church_and_falling_rates_only_warn(db):
    from app.modules.payroll import switzerland_service as svc

    # A0N and A0Y both start at 0 — not an overlap, they are different groups
    data = _file(_record("A0N", 0, 0, 1000, 0, 3), _record("A0N", 0, 1000, 0, 0, 2),
                 _record("A0Y", 0, 0, 0, 0, 1), _record("B1N", 1, 0, 0, 0, 1))
    out = svc.validate_qst_tariff_file(db, _import(db, data)["id"], SA_A.id)
    report = out["validationReport"]["validation"]
    assert out["status"] == "VALIDATED" and report["groupCount"] == 3
    assert any("rate falls from 3" in w for w in report["warnings"])


def test_validate_only_from_imported(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import switzerland_service as svc

    f = _import(db)
    svc.validate_qst_tariff_file(db, f["id"], SA_A.id)
    with pytest.raises(BadRequestException, match="only an IMPORTED tariff file can be validated"):
        svc.validate_qst_tariff_file(db, f["id"], SA_A.id)


# ── immutability ────────────────────────────────────────────────────────

def test_tariff_rows_cannot_be_updated_or_deleted(db):
    from app.modules.payroll.models import ChQstTariffRow

    f = _import(db)
    row = db.query(ChQstTariffRow).filter(ChQstTariffRow.tariff_file_id == f["id"]).first()
    row.rate_pct = Decimal("99")
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()
    row = db.query(ChQstTariffRow).filter(ChQstTariffRow.tariff_file_id == f["id"]).first()
    db.delete(row)
    with pytest.raises(ValueError, match="immutable"):
        db.flush()
    db.rollback()
    assert db.query(ChQstTariffRow).count() == 9


def test_there_is_no_update_or_delete_path_in_the_service_or_the_api():
    from app.main import app
    from app.modules.payroll import switzerland_service as svc

    public = [n for n in dir(svc) if callable(getattr(svc, n)) and not n.startswith("_")
              and ("qst" in n.lower() or "tariff" in n.lower())]
    assert "lookup_qst_rate" in public                     # the filter really selects the QST surface
    assert not [n for n in public if any(w in n.lower() for w in ("update", "delete", "edit", "remove"))]
    methods = {m for r in app.routes if "/compliance/switzerland/qst-tariffs" in getattr(r, "path", "")
               for m in r.methods}
    assert methods == {"GET", "POST"}


# ── maker-checker ───────────────────────────────────────────────────────

def test_self_approval_and_approver_activation_are_refused(db):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import switzerland_service as svc

    f = _import(db, actor=SA_A)
    with pytest.raises(BadRequestException, match="only a VALIDATED"):
        svc.approve_qst_tariff_file(db, f["id"], SA_B.id)
    svc.validate_qst_tariff_file(db, f["id"], SA_A.id)
    with pytest.raises(BadRequestException, match="other than its importer"):
        svc.approve_qst_tariff_file(db, f["id"], SA_A.id)
    with pytest.raises(BadRequestException, match="other than its importer"):
        svc.approve_qst_tariff_file(db, f["id"], None)
    with pytest.raises(BadRequestException, match="only an APPROVED"):
        svc.activate_qst_tariff_file(db, f["id"], SA_C.id)
    out = svc.approve_qst_tariff_file(db, f["id"], SA_B.id, reason="checked against source")
    assert out["status"] == "APPROVED" and out["approvedById"] == SA_B.id
    with pytest.raises(BadRequestException, match="other than its approver"):
        svc.activate_qst_tariff_file(db, f["id"], SA_B.id)
    out = svc.activate_qst_tariff_file(db, f["id"], SA_A.id)        # the importer may activate (four eyes kept by B)
    assert out["status"] == "ACTIVE" and out["activatedById"] == SA_A.id and out["supersedesId"] is None
    assert _audits(db, f["id"]) == ["import", "validate", "approve", "activate"]


# ── supersession + replay ───────────────────────────────────────────────

def _v2():
    """Same structure as the fixture, different A0N rates — a revised tariff."""
    recs = [l for l in FIXTURE.decode("latin-1").splitlines() if l.startswith("06") and "A0N" not in l]
    return _file(_record("A0N", 0, 0, 1000, 0, 0.5), _record("A0N", 0, 1000, 1000, 10, 2),
                 _record("A0N", 0, 2000, 0, 25, 6), *recs)


def test_activation_supersedes_only_overlapping_active_files_of_the_same_canton(db):
    from app.modules.payroll import switzerland_service as svc

    v1 = _active(db)
    other_year = _active(db, _file(_record("A0N", 0, 0, 0, 0, 1, valid_from="20270101")),
                         effective_from=date(2027, 1, 1), effective_to=date(2027, 12, 31), tax_year=2027)
    be = _active(db, _file(_record("A0N", 0, 0, 0, 0, 1, canton="BE")), canton="CH-BE")
    v2 = _active(db, _v2())
    assert v2["status"] == "ACTIVE" and v2["supersedesId"] == v1["id"]
    assert svc.get_qst_tariff_file(db, v1["id"])["status"] == "SUPERSEDED"
    assert svc.get_qst_tariff_file(db, other_year["id"])["status"] == "ACTIVE"   # 2027 does not overlap 2026
    assert svc.get_qst_tariff_file(db, be["id"])["status"] == "ACTIVE"           # other canton untouched
    assert _audits(db, v1["id"])[-1] == "supersede"
    assert [f["id"] for f in svc.list_qst_tariff_files(db, canton="CH-ZH", status="ACTIVE")] == [
        v2["id"], other_year["id"]]


def test_open_ended_active_file_is_superseded_by_a_later_one(db):
    from app.modules.payroll import switzerland_service as svc

    v1 = _active(db, effective_to=None)
    v2 = _active(db, _v2(), effective_to=None)
    assert svc.get_qst_tariff_file(db, v1["id"])["status"] == "SUPERSEDED" and v2["supersedesId"] == v1["id"]


def test_superseded_file_stays_readable_by_id_and_replays_its_own_rates(db):
    from app.modules.payroll import switzerland_service as svc
    from app.modules.payroll.models import ChQstTariffRow

    v1 = _active(db)
    v2 = _active(db, _v2())
    old = svc.get_qst_tariff_file(db, v1["id"])
    assert old["status"] == "SUPERSEDED" and old["rowCount"] == 9 and old["fileSha256"] == v1["fileSha256"]
    assert db.query(ChQstTariffRow).filter(ChQstTariffRow.tariff_file_id == v1["id"]).count() == 9
    assert svc.lookup_qst_rate(db, v1["id"], "A", 0, False, 1500)[0] == Decimal("1.25")   # replay: old rate
    assert svc.lookup_qst_rate(db, v2["id"], "A", 0, False, 1500)[0] == Decimal("2")      # live: new rate


# ── lookup ──────────────────────────────────────────────────────────────

def test_lookup_band_boundaries(db):
    from app.modules.payroll import switzerland_service as svc

    fid = _active(db)["id"]

    def rate(income, code="A", children=0, church=False):
        return svc.lookup_qst_rate(db, fid, code, children, church, income)

    assert rate(0)[:2] == (Decimal("0"), Decimal("0"))
    assert rate("999.99")[0] == Decimal("0")                  # upper bound is exclusive
    assert rate(1000)[:2] == (Decimal("1.25"), Decimal("10"))  # lower bound is inclusive
    assert rate(Decimal("1999.99"))[0] == Decimal("1.25")
    assert rate(2000)[:2] == (Decimal("5"), Decimal("25"))
    assert rate(10_000_000)[0] == Decimal("5")                 # open-ended top band
    assert rate(1500, church=True)[0] == Decimal("1.5")
    assert rate(1500, code="B", children=1)[0] == Decimal("0.75")
    r1, r2 = rate(1000), rate(1000, church=True)
    assert isinstance(r1[2], int) and r1[2] != r2[2]


def test_lookup_refusals(db):
    from app.core.exceptions import BadRequestException, NotFoundException
    from app.modules.payroll import switzerland_service as svc

    fid = _active(db)["id"]
    with pytest.raises(BadRequestException, match="negative"):
        svc.lookup_qst_rate(db, fid, "A", 0, False, -1)
    with pytest.raises(BadRequestException, match="not a number"):
        svc.lookup_qst_rate(db, fid, "A", 0, False, "abc")
    with pytest.raises(NotFoundException):
        svc.lookup_qst_rate(db, fid, "C", 0, False, 100)                 # no such tariff group
    with pytest.raises(NotFoundException):
        svc.lookup_qst_rate(db, fid, "A", 3, False, 100)                 # no such children count
    with pytest.raises(NotFoundException):
        svc.lookup_qst_rate(db, 999_999, "A", 0, False, 100)
    pending = _import(db, _v2())
    with pytest.raises(BadRequestException, match="IMPORTED; only an ACTIVE or SUPERSEDED"):
        svc.lookup_qst_rate(db, pending["id"], "A", 0, False, 100)       # never-approved data never calculates


# ── HTTP ────────────────────────────────────────────────────────────────

def test_full_lifecycle_over_http_with_audit(db):
    base = "/api/super-admin/compliance/switzerland/qst-tariffs"
    form = {"canton": "CH-ZH", "formatVersion": "ESTV_FIXED_WIDTH_V1", "effectiveFrom": "2026-01-01",
            "effectiveTo": "2026-12-31", "taxYear": "2026"}
    files = {"file": ("synthetic_zh_v1.txt", FIXTURE, "text/plain")}
    with _http(db, SA_A) as c:
        res = c.post(base, data=form, files=files)
        assert res.status_code == 200, res.text
        fid = res.json()["id"]
        assert c.post(base, data=form, files=files).status_code == 400            # duplicate
        assert c.post(f"{base}/{fid}/validate").json()["status"] == "VALIDATED"
        res = c.post(f"{base}/{fid}/approve", json={"reason": "self"})
        assert res.status_code == 400 and "other than its importer" in res.text
    with _http(db, SA_B) as c:
        assert c.post(f"{base}/{fid}/approve", json={"reason": "ok"}).json()["status"] == "APPROVED"
        assert c.post(f"{base}/{fid}/activate", json={}).status_code == 400       # approver cannot activate
    with _http(db, SA_A) as c:
        assert c.post(f"{base}/{fid}/activate", json={"reason": "go live"}).json()["status"] == "ACTIVE"
        assert [f["id"] for f in c.get(base, params={"canton": "CH-ZH"}).json()] == [fid]
        assert c.get(f"{base}/{fid}").json()["status"] == "ACTIVE"
        assert c.get(f"{base}/999999").status_code == 404
        assert c.put(f"{base}/{fid}", json={}).status_code == 405
        assert c.delete(f"{base}/{fid}").status_code == 405
    assert _audits(db, fid) == ["import", "validate", "approve", "activate"]


def test_routes_require_super_admin(db):
    from types import SimpleNamespace

    org_admin = SimpleNamespace(id=404, organization_id=1, role="org_admin", is_active=True)
    with _http(db, org_admin) as c:
        assert c.get("/api/super-admin/compliance/switzerland/qst-tariffs").status_code == 403
