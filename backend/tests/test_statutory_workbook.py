"""Statutory workbook (country-neutral) with the Malaysia adapter — ZP-MY-ENG-001
Phase 1. Preview writes nothing; apply is all-or-nothing, writes EXTRACTED
(unsigned) rows through my_super_admin and keeps the workbook as evidence;
signing needs a stored, hashed source reviewed by a second Super Admin."""
import io
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException


@pytest.fixture
def wb(db):
    from app.modules.auth.models import User, UserRole
    from app.modules.payroll import malaysia_service as mys
    from app.modules.payroll import statutory_workbook as wbk
    from app.modules.payroll.models import SourceArtifact
    from app.modules.payroll.my_workbook_adapter import MalaysiaWorkbookAdapter

    users = []
    for i in range(3):
        u = User(email=f"sa{i}.my@example.com", hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="S",
                 last_name=str(i), is_active=True, is_verified=True)
        db.add(u)
        users.append(u)
    db.flush()
    reviewed = SourceArtifact(agency="KWSP", title="EPF Third Schedule", checksum_sha256="a" * 64,
                              file_path="sources/epf-third-schedule.pdf", created_by_id=users[1].id,
                              reviewer_id=users[2].id)
    unreviewed = SourceArtifact(agency="KWSP", title="draft notes", created_by_id=users[1].id)
    db.add_all([reviewed, unreviewed])
    pack = mys.seed_malaysia_pack(db)
    db.commit()
    return SimpleNamespace(db=db, wbk=wbk, adapter=MalaysiaWorkbookAdapter(), pack=pack, editor=users[0].id,
                           signer=users[1].id, source=reviewed.id, draft_source=unreviewed.id)


def _edit(data: bytes, edits: dict) -> bytes:
    """edits: {sheet: [(match_col, match_value, {col: value}) | ("append", [values])]}"""
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data))
    for sheet, changes in edits.items():
        ws = book[sheet]
        headers = [c.value for c in ws[1]]
        for change in changes:
            if change[0] == "append":
                ws.append(change[1])
                continue
            col, value, values = change
            for row in ws.iter_rows(min_row=2):
                if row[headers.index(col)].value == value:
                    for name, new in values.items():
                        row[headers.index(name)].value = new
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _epf_rows(w, top="20000"):
    return [("append", ["MY_PR_BELOW_60", 0, 10, 0, 0, w.source, "p.1"]),
            ("append", ["MY_PR_BELOW_60", 10, 20, "2.20", "2.60", w.source, "p.1"]),
            ("append", ["MY_PR_BELOW_60", 20, top, "11.00", "13.00", w.source, "p.2"])]


def _rates(w):
    from app.modules.payroll.models import ContributionRate

    return {r.component_key: r for r in w.db.query(ContributionRate).filter_by(jurisdiction_pack_id=w.pack.id)}


# ── export ─────────────────────────────────────────────────────────────────
def test_export_holds_every_row_and_the_pack_fingerprint(wb):
    from openpyxl import load_workbook

    from app.modules.payroll.engine.countries import malaysia_content as c

    book = load_workbook(io.BytesIO(wb.wbk.export_workbook(wb.db, wb.pack, wb.adapter)))
    assert book.sheetnames == ["Instructions", "Parameters", *c.SCHEDULE_RULES, "Holidays", "Earning classes"]
    info = {r[0].value: r[1].value for r in book["Instructions"].iter_rows()}
    assert info["fingerprint"] == wb.adapter.fingerprint(wb.pack) and info["pack_id"] == "MY-PAYROLL-2026"
    params = list(book["Parameters"].iter_rows(min_row=2, values_only=True))
    assert len(params) == len(c.MALAYSIA_SCALAR_CONTENT)
    status = {row[0]: row[6] for row in params}
    assert status["my_min_wage_monthly"] == "EXTRACTED" and status["my_rounding_pcb"] == "MISSING"
    assert len(list(book["Earning classes"].iter_rows(min_row=2))) == 96


def test_an_untouched_template_changes_nothing(wb):
    data = wb.wbk.export_workbook(wb.db, wb.pack, wb.adapter)
    out = wb.wbk.import_workbook(wb.db, wb.pack, data, wb.adapter, wb.editor)
    assert out["fatal"] == [] and out["summary"]["CHANGED"] == 0 and out["summary"]["INVALID"] == 0
    assert out["summary"]["MISSING"] >= 5                                  # empty schedules + holidays + pending


# ── preview and apply ──────────────────────────────────────────────────────
def test_preview_writes_nothing_and_apply_writes_extracted_rows(wb):
    from app.modules.payroll.models import SourceArtifact, TaxConfigurationAudit, TaxSlab

    data = _edit(wb.wbk.export_workbook(wb.db, wb.pack, wb.adapter), {
        "Parameters": [("key", "my_rounding_pcb", {"value": "five_sen_up", "source_document_id": wb.source,
                                                   "page": "s.4"}),
                       ("key", "my_ot_multiplier_workday__SBH", {"value": "1.5", "source_document_id": wb.source})],
        "MY_EPF_SCHEDULE": _epf_rows(wb),
        "Holidays": [("append", ["2026-08-31", "Hari Kebangsaan", None, wb.source, "p.1"]),
                     ("append", ["2026-03-07", "Hari Keputeraan Sultan Johor", "JHR", wb.source, "p.1"])],
        "Earning classes": [("component", "BENEFIT_IN_KIND", {"treatment": "INCLUDED", "source_document_id": wb.source})],
    })
    preview = wb.wbk.import_workbook(wb.db, wb.pack, data, wb.adapter, wb.editor)
    changed = {r["ref"] for r in preview["rows"] if r["status"] == "CHANGED"}
    assert {"my_rounding_pcb", "my_ot_multiplier_workday__SBH", "MY_EPF_SCHEDULE", "Holidays"} <= changed
    assert preview["summary"]["INVALID"] == 0 and preview["applied"] is False
    assert _rates(wb)["my_rounding_pcb"].text_value == "PENDING_G1"        # nothing written by a preview
    with pytest.raises(BadRequestException, match="reason"):
        wb.wbk.import_workbook(wb.db, wb.pack, data, wb.adapter, wb.editor, apply=True)
    out = wb.wbk.import_workbook(wb.db, wb.pack, data, wb.adapter, wb.editor, reason="2026 documents", apply=True)
    wb.db.commit()
    assert out["applied"] is True and out["written"]["tables"] == 8         # 3 bands x 2 sides + 2 holidays
    rate = _rates(wb)["my_rounding_pcb"]
    assert (rate.text_value, rate.source_document_id) == ("FIVE_SEN_UP", wb.source)
    assert rate.label.endswith("[PENDING G1]")                              # extracted, not verified
    epf = wb.db.query(TaxSlab).filter_by(jurisdiction_pack_id=wb.pack.id, rule_type="MY_EPF_SCHEDULE").all()
    assert len(epf) == 6 and {s.tax_regime for s in epf} == {"EMPLOYEE", "EMPLOYER"}
    assert all("[PENDING G1]" in s.rate_label and "p." in s.tax_formula for s in epf)
    top = next(s for s in epf if s.tax_regime == "EMPLOYER" and s.min_amount == Decimal("20"))
    assert top.flat_amount == Decimal("13.00") and top.filing_status == "MY_PR_BELOW_60"
    holiday = wb.db.query(TaxSlab).filter_by(jurisdiction_pack_id=wb.pack.id, rule_type="MY_PUBLIC_HOLIDAY",
                                             jurisdiction_state="JHR").one()
    assert holiday.tax_formula.startswith("2026-03-07") and "[PENDING G1]" in holiday.rate_label
    evidence = wb.db.get(SourceArtifact, out["workbookArtifactId"])
    assert evidence.form_number == "MY-WORKBOOK" and len(evidence.checksum_sha256) == 64
    assert wb.db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type.like("my_statutory_%")).count() >= 4
    again = wb.wbk.import_workbook(wb.db, wb.pack, wb.wbk.export_workbook(wb.db, wb.pack, wb.adapter), wb.adapter,
                                   wb.editor)
    assert again["summary"]["CHANGED"] == 0                                 # a re-export round-trips


@pytest.mark.parametrize("edits, ref, message", [
    ({"Parameters": [("key", "my_rounding_pcb", {"value": "NEAREST", "source_document_id": 1})]},
     "my_rounding_pcb", "must be one of"),
    ({"Parameters": [("key", "my_min_wage_monthly", {"value": "abc", "source_document_id": 1})]},
     "my_min_wage_monthly", "must be a number"),
    ({"Parameters": [("key", "my_epf_rate_non_malaysian", {"employee_rate_pct": "120", "source_document_id": 1})]},
     "my_epf_rate_non_malaysian", "percentage"),
    ({"Parameters": [("key", "my_hrd_base_rule", {"value": "ANY_TEXT", "source_document_id": 1})]},
     "my_hrd_base_rule", "NOT_SUPPORTED"),
    ({"Parameters": [("append", ["my_invented_key", "NATIONAL", "", "amount", "", "", "", "1"])]},
     "my_invented_key", "unknown parameter"),
    ({"Parameters": [("key", "my_min_wage_monthly", {"value": "1800"})]}, "my_min_wage_monthly", "source document"),
    ({"MY_EPF_SCHEDULE": [("append", ["MY_PR_BELOW_60", 0, 10, 0, 0, 1, ""]),
                          ("append", ["MY_PR_BELOW_60", 11, 20, 1, 1, 1, ""])]}, "MY_EPF_SCHEDULE", "contiguous"),
    ({"MY_EPF_SCHEDULE": [("append", ["SOMEONE", 0, 10, 0, 0, 1, ""])]}, "MY_EPF_SCHEDULE", "member class"),
    ({"Holidays": [("append", ["2025-12-25", "Christmas", None, 1, ""])]}, "Holidays", "outside the pack window"),
    ({"Holidays": [("append", ["2026-12-25", "Christmas", "XYZ", 1, ""])]}, "Holidays", "state"),
    ({"Earning classes": [("component", "BONUS", {"treatment": "MAYBE", "source_document_id": 1})]},
     "PCB_NORMAL x BONUS", "treatment must be"),
])
def test_invalid_rows_block_the_whole_workbook(wb, edits, ref, message):
    for changes in edits.values():                                          # use the fixture's real source id
        for i, change in enumerate(changes):
            if change[0] == "append":
                change[1][:] = [wb.source if v == 1 and n >= 5 else v for n, v in enumerate(change[1])] \
                    if len(change[1]) in (5, 7) else change[1]
            elif "source_document_id" in change[2]:
                change[2]["source_document_id"] = wb.source
    data = _edit(wb.wbk.export_workbook(wb.db, wb.pack, wb.adapter), edits)
    preview = wb.wbk.import_workbook(wb.db, wb.pack, data, wb.adapter, wb.editor)
    row = next(r for r in preview["rows"] if r["ref"] == ref)
    assert row["status"] == "INVALID" and message in row["detail"], row
    with pytest.raises(BadRequestException, match="nothing was written"):
        wb.wbk.import_workbook(wb.db, wb.pack, data, wb.adapter, wb.editor, reason="x", apply=True)
    assert _rates(wb)["my_min_wage_monthly"].flat_amount == Decimal("1700")


def test_a_workbook_for_another_pack_or_a_tampered_layout_is_refused(wb):
    from app.modules.payroll.models import JurisdictionPack

    data = wb.wbk.export_workbook(wb.db, wb.pack, wb.adapter)
    other = JurisdictionPack(pack_id="MY-PAYROLL-2026", version="1.1", jurisdiction_country="MY", pack_type="tax",
                             status="Draft", effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    wb.db.add(other)
    wb.db.commit()
    out = wb.wbk.import_workbook(wb.db, other, data, wb.adapter, wb.editor)
    assert any("different pack or version" in f for f in out["fatal"])
    with pytest.raises(BadRequestException):
        wb.wbk.import_workbook(wb.db, other, data, wb.adapter, wb.editor, reason="x", apply=True)
    from openpyxl import load_workbook

    book = load_workbook(io.BytesIO(data))
    book["Parameters"].cell(row=1, column=8, value="amount")
    buf = io.BytesIO()
    book.save(buf)
    assert any("columns changed" in f for f in wb.wbk.import_workbook(wb.db, wb.pack, buf.getvalue(), wb.adapter,
                                                                      wb.editor)["fatal"])
    assert wb.wbk.import_workbook(wb.db, wb.pack, b"not a workbook", wb.adapter, wb.editor)["fatal"]


def test_only_a_draft_pack_takes_a_workbook(wb):
    data = wb.wbk.export_workbook(wb.db, wb.pack, wb.adapter)
    wb.pack.status = "Approved"
    wb.db.commit()
    with pytest.raises(BadRequestException, match="only a Draft pack"):
        wb.wbk.import_workbook(wb.db, wb.pack, data, wb.adapter, wb.editor, reason="x", apply=True)


# ── signing (second person, reviewed source) ───────────────────────────────
def test_signing_needs_a_reviewed_source_and_is_all_or_nothing(wb):
    from app.modules.payroll import my_super_admin as msa

    rates = _rates(wb)
    wage, missing = rates["my_min_wage_monthly"], rates["my_hospitalisation_days__PEN"]
    with pytest.raises(BadRequestException, match="reviewed by a Super Admin"):
        msa.sign_rows(wb.db, [{"kind": "rate", "id": wage.id}], wb.signer, "G1", source_document_id=wb.draft_source)
    wb.db.rollback()
    with pytest.raises(BadRequestException, match="has no value"):
        msa.sign_rows(wb.db, [{"kind": "rate", "id": wage.id}, {"kind": "rate", "id": missing.id}], wb.signer, "G1",
                      source_document_id=wb.source)
    wb.db.rollback()                                                        # the API commits only on success
    assert _rates(wb)["my_min_wage_monthly"].label.endswith("[PENDING G1]")
    out = msa.sign_rows(wb.db, [{"kind": "rate", "id": wage.id}], wb.signer, "G1 signature",
                        source_document_id=wb.source)
    wb.db.commit()
    assert out["signed"] == 1 and not _rates(wb)["my_min_wage_monthly"].label.endswith("[PENDING G1]")
    msa.update_row(wb.db, "rate", wage.id, {"flatAmount": "1800", "reason": "typo", "sourceDocumentId": wb.source},
                   wb.editor)
    assert _rates(wb)["my_min_wage_monthly"].label.endswith("[PENDING G1]")  # an unsigned change re-marks it


def test_text_without_vocabulary_can_only_be_not_supported(wb):
    from app.modules.payroll import my_super_admin as msa

    row = _rates(wb)["my_hrd_base_rule"]
    with pytest.raises(BadRequestException, match="NOT_SUPPORTED"):
        msa.update_row(wb.db, "rate", row.id, {"textValue": "BASIC_PLUS_FIXED", "reason": "x",
                                                "sourceDocumentId": wb.source}, wb.editor)
    view = msa.update_row(wb.db, "rate", row.id, {"textValue": "NOT_SUPPORTED", "reason": "not in documents",
                                                   "sourceDocumentId": wb.source, "specialistVerified": True},
                          wb.signer)
    assert view["signed"] is True and view["textValue"] == "NOT_SUPPORTED"
