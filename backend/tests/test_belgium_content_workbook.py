"""Belgium (ZP-BE-ENG-001) Block D3: the content intake workbook and bulk signing.

Round trip, cell-referenced validation, import never signs / never touches a
non-Draft pack, the importer cannot bulk-sign, no personal data. SYNTHETIC
values only (never Belgian statutory content)."""
import io
import re

import pytest

from app.core.exceptions import BadRequestException
from tests.test_belgium_super_admin import SIGNER, _c, _verified_source, seeded  # noqa: F401  (pytest fixture)

IMPORTER = 601


def _wb():
    from app.modules.payroll import be_content_workbook

    return be_content_workbook


def _export(db, pack):
    from openpyxl import load_workbook

    _name, data = _wb().be_content_workbook_export(db, pack.id)
    return load_workbook(io.BytesIO(data))


def _bytes(book):
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _find(sheet, column, value):
    header = [c.value for c in sheet[1]]
    col = header.index(column) + 1
    for row in range(2, sheet.max_row + 1):
        if sheet.cell(row=row, column=col).value == value:
            return row, header
    raise AssertionError(f"{value} not found in {sheet.title}")


def _set(sheet, row, header, **values):
    for column, value in values.items():
        sheet.cell(row=row, column=header.index(column) + 1, value=value)
    return {c: f"{sheet.title}!{chr(64 + header.index(c) + 1)}{row}" for c in values}


def _import(db, pack, book, dry_run=True, actor=IMPORTER):
    return _wb().be_content_workbook_import(db, pack.id, _bytes(book), actor, reason="TEST ONLY intake",
                                            dry_run=dry_run)


def test_the_export_has_every_sheet_and_every_catalogue_row(db, seeded):
    c = _c()
    sheets = _wb().be_content_workbook_sheets(db, seeded.id)
    assert list(sheets) == ["Instructions", "Scalar keys", "Parallel tolerances", "Slab keys",
                            "Filing schema versions", "Earning classification", "Calendar rows", "Owner decisions",
                            "Sources"]
    tolerance = [k for k, v in c.KEYS.items() if v[0] == "parallel"]
    assert len(sheets["Scalar keys"]) - 1 == len(c.KEYS) - len(tolerance)
    assert len(sheets["Parallel tolerances"]) - 1 == len(tolerance) == 6
    assert len(sheets["Earning classification"]) - 1 == len(c.OBLIGATIONS) * len(c.COMPONENTS)
    assert len(sheets["Sources"]) - 1 == 24 and {r[5] for r in sheets["Sources"][1:]} == {"no"}   # none archived
    assert {r[2] for r in sheets["Filing schema versions"][1:]} == set(k for k, v in c.KEYS.items()
                                                                      if v[1] == c.KIND_VERSION)
    assert {r[0] for r in sheets["Owner decisions"][1:]} >= {"G-11", "G-16", "G-21"}
    proposed = [r for r in sheets["Scalar keys"][1:] if r[1] == "be_onss_employee_rate"][0]
    assert proposed[5] == c.SPEC_PROPOSED["be_onss_employee_rate"] and proposed[8] == ""   # label only, no value
    assert all(r[7] in ("PENDING", "EMPTY") for r in sheets["Scalar keys"][1:])


def test_the_workbook_carries_no_personal_data(db, seeded):
    from app.modules.payroll.models import PayrollEmployee
    from tests._mx_employer_helpers import make_org

    org = make_org(db, name="Workbook BV", code="BEWB", admins=1, country="BE").org.id
    db.add(PayrollEmployee(organization_id=org, employee_code="WB1", name="Zelda Testperson", country_code="BE"))
    db.commit()
    _name, data = _wb().be_content_workbook_export(db, seeded.id)
    text = " ".join(str(v) for rows in _wb().be_content_workbook_sheets(db, seeded.id).values()
                    for row in rows for v in row)
    assert "Zelda" not in text and "WB1" not in text and "@" not in text
    assert not re.search(r"(?<!\d)\d{11}(?!\d)", text)                     # nothing NISS-shaped
    assert data[:2] == b"PK"                                                # a real XLSX


def test_export_then_dry_run_import_changes_nothing(db, seeded):
    out = _import(db, seeded, _export(db, seeded))
    assert (out["dryRun"], out["written"], out["changes"], out["errors"]) == (True, False, 0, 0)


def test_invalid_cells_are_reported_with_their_reference_and_nothing_is_written(db, seeded):
    src = _verified_source(db)
    book = _export(db, seeded)
    scalar = book["Scalar keys"]
    row, header = _find(scalar, "key", "be_rounding_onss")
    good = _set(scalar, row, header, textValue="CENT_HALF_UP", sourceDocumentId=str(src.id))
    row, header = _find(scalar, "key", "be_rounding_holiday")
    bad_vocab = _set(scalar, row, header, textValue="ROUND_UP", sourceDocumentId=str(src.id))
    row, header = _find(scalar, "key", "be_rounding_withholding")
    _set(scalar, row, header, textValue="CENT_DOWN")                               # no source reference
    no_source_cell = f"Scalar keys!{chr(64 + header.index('sourceDocumentId') + 1)}{row}"
    slab = book["Slab keys"]
    header = [c.value for c in slab[1]]
    row = next(r for r in range(2, slab.max_row + 1)
               if slab.cell(r, 2).value == "be_onss_employer_base_rate" and slab.cell(r, 17).value == "TEMPLATE")
    bad_dim = _set(slab, row, header, minAmount="0", ratePct="1", dimension="XX=1", sourceDocumentId=str(src.id))
    cal = book["Calendar rows"]
    header = [c.value for c in cal[1]]
    r = cal.max_row + 1
    bad_date = _set(cal, r, header, reportType="BE_DMFA", reportingYear="2026", periodKey="2026Q3",
                    dueDate="2026-13-40", sourceDocumentId=str(src.id))
    out = _import(db, seeded, book)
    by_cell = {i["cell"]: i for i in out["items"]}
    assert by_cell[good["textValue"]]["status"] == "OK"
    assert by_cell[bad_vocab["textValue"]]["status"] == "ERROR"
    assert "one of" in by_cell[bad_vocab["textValue"]]["reason"]
    assert by_cell[no_source_cell]["status"] == "ERROR" and "source" in by_cell[no_source_cell]["reason"]
    assert any(i["status"] == "ERROR" and i["sheet"] == "Slab keys" and "dimension" in i["reason"].lower()
               for i in out["items"]), out["items"]
    assert by_cell[bad_date["dueDate"]]["status"] == "ERROR"
    # a real import with any ERROR writes nothing
    out = _import(db, seeded, book, dry_run=False)
    assert out["written"] is False and out["errors"] >= 4
    from tests.test_belgium_super_admin import _rate

    assert _rate(db, seeded, "be_rounding_onss").text_value is None


def test_a_valid_import_writes_unsigned_rows_and_draft_calendar_rows(db, seeded):
    from app.modules.payroll.models import StatutoryFilingCalendar, TaxConfigurationAudit
    from tests.test_belgium_super_admin import _rate

    c = _c()
    src = _verified_source(db)
    book = _export(db, seeded)
    scalar = book["Scalar keys"]
    row, header = _find(scalar, "key", "be_rounding_onss")
    _set(scalar, row, header, textValue="CENT_HALF_UP", sourceDocumentId=str(src.id))
    cal = book["Calendar rows"]
    header = [cell.value for cell in cal[1]]
    _set(cal, cal.max_row + 1, header, reportType="BE_DMFA", reportingYear="2026", periodKey="2026Q3",
         dueDate="2026-10-30", sourceDocumentId=str(src.id))
    out = _import(db, seeded, book, dry_run=False)
    db.commit()
    assert out["written"] and out["errors"] == 0 and out["changes"] == 2
    rate = _rate(db, seeded, "be_rounding_onss")
    assert rate.text_value == "CENT_HALF_UP" and c.PENDING_MARK in rate.label           # never signed
    audit = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "be_statutory_rate",
                                                    TaxConfigurationAudit.entity_id == rate.id).one())
    assert audit.actor_id == IMPORTER and audit.old_value["textValue"] is None          # before-image kept
    cal_row = db.query(StatutoryFilingCalendar).filter_by(jurisdiction_country="BE", period_key="2026Q3").one()
    assert cal_row.status == "Draft" and cal_row.source_document_id == src.id         # inactive until activated
    assert seeded.status == "Draft"                                                     # never activated


def test_import_refuses_a_pack_that_is_not_draft(db, seeded):
    book = _export(db, seeded)
    seeded.status = "Approved"
    db.commit()
    with pytest.raises(BadRequestException, match="Draft pack only"):
        _import(db, seeded, book)


def test_the_importer_cannot_bulk_sign_but_another_super_admin_can(db, seeded):
    from app.modules.payroll.models import TaxConfigurationAudit
    from tests.test_belgium_super_admin import _rate

    c = _c()
    src = _verified_source(db)
    book = _export(db, seeded)
    scalar = book["Scalar keys"]
    for key, value in (("be_rounding_onss", "CENT_HALF_UP"), ("be_rounding_holiday", "CENT_DOWN")):
        row, header = _find(scalar, "key", key)
        _set(scalar, row, header, textValue=value, sourceDocumentId=str(src.id))
    assert _import(db, seeded, book, dry_run=False)["written"]
    db.commit()
    rows = [{"kind": "rate", "id": _rate(db, seeded, k).id} for k in ("be_rounding_onss", "be_rounding_holiday")]
    with pytest.raises(BadRequestException, match="Four-eyes"):
        _wb().be_bulk_sign_rows(db, seeded.id, {"rows": rows, "reason": "sign"}, IMPORTER)
    out = _wb().be_bulk_sign_rows(db, seeded.id, {"rows": rows, "reason": "TEST ONLY reviewed"}, SIGNER)
    db.commit()
    assert len(out["signed"]) == 2
    for k in ("be_rounding_onss", "be_rounding_holiday"):
        rate = _rate(db, seeded, k)
        assert c.PENDING_MARK not in rate.label
        signs = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "be_statutory_rate",
                                                        TaxConfigurationAudit.entity_id == rate.id,
                                                        TaxConfigurationAudit.actor_id == SIGNER).all())
        assert len(signs) == 1 and signs[0].new_value["signed"] is True                 # one audit row per row


# ── Block E: source references, draft sources, the committed AI draft ──────
def test_a_source_reference_works_like_an_id_and_draft_sources_are_created_unverified(db, seeded):
    from app.modules.payroll.models import SourceArtifact
    from tests.test_belgium_super_admin import _rate

    c = _c()
    book = _export(db, seeded)
    ds = book.create_sheet("Draft sources")
    ds.append(["reference", "agency", "title", "url"])
    ds.append(["ZP-BE-TEST D01", "TEST ONLY", "TEST ONLY source", "https://example.invalid/source"])
    scalar = book["Scalar keys"]
    row, header = _find(scalar, "key", "be_rounding_onss")
    _set(scalar, row, header, textValue="CENT_HALF_UP", sourceDocumentId="ZP-BE-TEST D01")
    out = _import(db, seeded, book, dry_run=False)
    db.commit()
    assert out["written"] and out["errors"] == 0
    source = db.query(SourceArtifact).filter_by(form_number="ZP-BE-TEST D01").one()
    assert "[UNVERIFIED" in source.title and source.checksum_sha256 is None                 # can never sign
    rate = _rate(db, seeded, "be_rounding_onss")
    assert rate.source_document_id == source.id and c.PENDING_MARK in rate.label
    again = _import(db, seeded, book)                                                    # reference exists now
    assert again["errors"] == 0 and db.query(SourceArtifact).filter_by(form_number="ZP-BE-TEST D01").count() == 1


def test_the_committed_ai_draft_imports_without_error_and_signs_nothing(db, seeded):
    from pathlib import Path

    from app.modules.payroll.models import ContributionRate, TaxSlab

    c = _c()
    path = Path(__file__).resolve().parents[2] / "docs" / "belgium" / "content" / "BE_2026_AI_DRAFT.xlsx"
    data = path.read_bytes()
    dry = _wb().be_content_workbook_import(db, seeded.id, data, IMPORTER, reason="TEST ONLY", dry_run=True)
    assert dry["errors"] == 0 and dry["changes"] > 200
    done = _wb().be_content_workbook_import(db, seeded.id, data, IMPORTER, reason="TEST ONLY", dry_run=False)
    db.commit()
    assert done["written"]
    rates = db.query(ContributionRate).filter_by(jurisdiction_pack_id=seeded.id).all()
    slabs = db.query(TaxSlab).filter_by(jurisdiction_pack_id=seeded.id).all()
    assert all(c.PENDING_MARK in r.label for r in rates)                                   # nothing signed
    assert all(c.PENDING_MARK in s.rate_label for s in slabs)
    assert seeded.status == "Draft"
    by_key = {r.component_key: r for r in rates}
    assert by_key["be_supported_pay_frequencies"].text_value == "MONTHLY"                    # G-11
    assert str(by_key["be_onss_employee_rate"].employee_rate_pct).rstrip("0").rstrip(".") == "13.07"
