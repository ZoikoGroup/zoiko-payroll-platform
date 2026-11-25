"""Belgian content import from CSV / JSON (same governed path as the XLSX
workbook): preview (dry run), all-or-nothing, a source per changed row, rows
stay UNSIGNED; plus the checks added for every format — required columns,
known sheets, a rate never above 100 % (except the catalogue's multiplier
keys), no overlapping brackets. And the template: every column, fake values.
SYNTHETIC values only (never Belgian statutory content)."""
import csv
import io
import json
from decimal import Decimal
from pathlib import Path

from tests.test_belgium_super_admin import _c, _rate, _verified_source, seeded  # noqa: F401  (pytest fixture)

IMPORTER = 611
TEMPLATES = Path(__file__).resolve().parents[1] / "scripts" / "templates"


def _wb():
    from app.modules.payroll import be_content_workbook

    return be_content_workbook


def _csv(rows):
    columns = ["sheet"] + sorted({k for r in rows for k in r} - {"sheet"})
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\n")
    writer.writeheader()
    for r in rows:
        writer.writerow(r)
    return out.getvalue().encode("utf-8")


def _json(rows):
    return json.dumps({"rows": rows}).encode("utf-8")


def _run(db, pack, data, filename, dry_run=True):
    return _wb().be_content_workbook_import(db, pack.id, data, IMPORTER, reason="TEST ONLY intake",
                                            dry_run=dry_run, filename=filename)


def _errors(out):
    return [i["reason"] for i in out["items"] if i["status"] == "ERROR"]


def _scalar(db, pack, key, src, **values):
    return {"sheet": "Scalar keys", "rowId": str(_rate(db, pack, key).id), "key": key,
            "sourceDocumentId": str(src.id), **values}


# ── template ─────────────────────────────────────────────────────────────────
def test_committed_templates_match_the_generator():
    for fmt in ("csv", "json"):
        name, data, _media = _wb().be_content_import_template(fmt)
        assert (TEMPLATES / f"be_content_import_template.{fmt}").read_bytes().replace(b"\r\n", b"\n") == data, name


def test_template_has_every_required_column_and_only_fake_values():
    wb = _wb()
    _name, data, _media = wb.be_content_import_template("csv")
    rows = list(csv.DictReader(io.StringIO(data.decode("utf-8"))))
    header = set(rows[0])
    for sheet in ("Scalar keys", "Slab keys"):
        assert set(wb.REQUIRED_COLUMNS[sheet]) <= header, sheet
    assert {"employeeRatePct", "employerRatePct", "minAmount", "maxAmount", "ratePct", "flatAmount"} <= header
    numbers = [v for r in rows for k, v in r.items() if k not in ("sheet", "key", "sourceDocumentId") and v]
    assert numbers and all(Decimal(v) == 0 for v in numbers)              # obviously fake: zero only
    assert {r["sourceDocumentId"] for r in rows} == {wb.TEMPLATE_PLACEHOLDER_SOURCE}
    assert all(r["key"].startswith("REPLACE") for r in rows)
    doc = json.loads(wb.be_content_import_template("json")[1])
    assert doc["_instructions"] and len(doc["rows"]) == 2 and set(doc["columns"]) == header


# ── CSV / JSON through the governed path ─────────────────────────────────────
def test_csv_dry_run_then_import_writes_unsigned_rows(db, seeded):
    c = _c()
    src = _verified_source(db)
    data = _csv([_scalar(db, seeded, "be_rounding_onss", src, textValue="CENT_HALF_UP")])
    preview = _run(db, seeded, data, "content.csv")
    assert preview["errors"] == 0 and preview["changes"] == 1 and not preview["written"]
    assert _rate(db, seeded, "be_rounding_onss").text_value is None           # the preview wrote nothing
    out = _run(db, seeded, data, "content.csv", dry_run=False)
    db.commit()
    rate = _rate(db, seeded, "be_rounding_onss")
    assert out["written"] and rate.text_value == "CENT_HALF_UP" and c.PENDING_MARK in rate.label   # never signed


def test_json_import_is_the_same_path(db, seeded):
    c = _c()
    src = _verified_source(db)
    out = _run(db, seeded, _json([_scalar(db, seeded, "be_rounding_onss", src, textValue="CENT_HALF_UP")]),
               "content.json", dry_run=False)
    db.commit()
    assert out["written"] and out["errors"] == 0
    assert c.PENDING_MARK in _rate(db, seeded, "be_rounding_onss").label


def test_a_changed_row_without_a_source_is_refused_and_nothing_is_written(db, seeded):
    src = _verified_source(db)
    good = _scalar(db, seeded, "be_rounding_onss", src, textValue="CENT_HALF_UP")
    bad = _scalar(db, seeded, "be_rounding_withholding", src, textValue="CENT_HALF_UP", sourceDocumentId="NO-SUCH-SOURCE")
    out = _run(db, seeded, _csv([good, bad]), "content.csv", dry_run=False)
    assert not out["written"] and any("source document" in e for e in _errors(out))
    assert _rate(db, seeded, "be_rounding_onss").text_value is None           # all-or-nothing


def test_missing_required_columns_and_unknown_sheets_are_refused(db, seeded):
    src = _verified_source(db)
    no_source = {"sheet": "Scalar keys", "rowId": str(_rate(db, seeded, "be_rounding_onss").id),
                 "key": "be_rounding_onss", "textValue": "CENT_HALF_UP"}
    out = _run(db, seeded, _csv([no_source]), "content.csv")
    assert any("missing required column(s): sourceDocumentId" in e for e in _errors(out))
    out = _run(db, seeded, _csv([{**_scalar(db, seeded, "be_rounding_onss", src, textValue="x"), "sheet": "Rates"}]),
               "content.csv")
    assert any(e.startswith("sheet must be one of") for e in _errors(out))


def test_a_rate_above_100_is_refused(db, seeded):
    src = _verified_source(db)
    out = _run(db, seeded, _csv([_scalar(db, seeded, "be_onss_employee_rate", src, employeeRatePct="150")]),
               "content.csv")
    assert any("cannot exceed 100" in e for e in _errors(out))


def test_the_manual_worker_uplift_is_capped_like_every_rate(db, seeded):
    """be_onss_manual_base_uplift stores the percentage ADDED to the base (the
    engine uses (100 + uplift) / 100): "gross + 8 %" is 8, never 108."""
    src = _verified_source(db)
    key = "be_onss_manual_base_uplift"

    def rate_errors(value):
        out = _run(db, seeded, _csv([_scalar(db, seeded, key, src, employeeRatePct=value)]), "content.csv")
        return [e for e in _errors(out) if "exceed" in e]

    assert rate_errors("8") == []                                             # the uplift itself: accepted
    for value in ("108", "1080"):                                             # a multiplier typed by mistake
        assert rate_errors(value) == ["a rate is the percentage number itself and cannot exceed 100"]
    assert not hasattr(_c(), "RATE_CAP_EXEMPT_KEYS")                          # no exemption list any more


def test_the_ai_draft_workbook_still_imports_in_dry_run(db, seeded):
    path = Path(__file__).resolve().parents[2] / "docs" / "belgium" / "content" / "BE_2026_AI_DRAFT.xlsx"
    out = _wb().be_content_workbook_import(db, seeded.id, path.read_bytes(), IMPORTER, reason="TEST ONLY",
                                           dry_run=True)
    assert out["errors"] == 0 and out["changes"] > 0 and not out["written"]


def _band_key():
    c = _c()
    return next(k for k, spec in c.SLAB_SPECS.items() if spec["kind"] == c.KIND_BAND and not spec["dimensions"])


def _band(src, low, high, rate="0", key=None):
    return {"sheet": "Slab keys", "key": key or _band_key(), "minAmount": low, "maxAmount": high, "ratePct": rate,
            "sourceDocumentId": str(src.id)}


def test_overlapping_brackets_are_refused(db, seeded):
    src = _verified_source(db)
    ok = _run(db, seeded, _csv([_band(src, "0", "1000"), _band(src, "1000", "")]), "content.csv")
    assert not any("overlap" in e for e in _errors(ok))                       # touching bands are fine
    bad = _run(db, seeded, _csv([_band(src, "0", "1000"), _band(src, "500", "2000")]), "content.csv")
    assert any("overlaps the file's row" in e for e in _errors(bad))
    open_ended = _run(db, seeded, _csv([_band(src, "0", ""), _band(src, "5000", "6000")]), "content.csv")
    assert any("overlap" in e for e in _errors(open_ended))                   # an open top band covers the rest


def test_a_new_bracket_overlapping_a_pack_row_is_refused(db, seeded):
    src = _verified_source(db)
    first = _run(db, seeded, _csv([_band(src, "0", "1000")]), "content.csv", dry_run=False)
    db.commit()
    assert first["written"], _errors(first)
    out = _run(db, seeded, _csv([_band(src, "900", "1200")]), "content.csv")
    assert any("overlaps pack row #" in e for e in _errors(out))


def test_a_bracket_rate_above_100_is_refused(db, seeded):
    src = _verified_source(db)
    out = _run(db, seeded, _csv([_band(src, "0", "1000", rate="101")]), "content.csv")
    assert any("cannot exceed 100" in e for e in _errors(out))


def test_bad_files_are_refused_plainly(db, seeded):
    import pytest

    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match='"sheet" column'):
        _run(db, seeded, b"key,rowId\nx,1\n", "content.csv")
    with pytest.raises(BadRequestException, match="not valid UTF-8 JSON"):
        _run(db, seeded, b"{not json", "content.json")
    with pytest.raises(BadRequestException, match="plain text or numbers"):
        _run(db, seeded, json.dumps([{"sheet": "Scalar keys", "rowId": {"x": 1}}]).encode(), "content.json")
