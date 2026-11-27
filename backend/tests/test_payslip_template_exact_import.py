"""
tests/test_payslip_template_exact_import.py
-------------------------------------------
"Exact layout" PDF import (P4) against the owner's blank payslip layout
(Payslip_Blank_Template.pdf): a reportlab copy of it always, and the real
file too when it is in tests/fixtures/payslip_import/.

  * analysis: 5 columns at 34/13/13/20/20 %, 17 rows, merged cells (title and
    full-width rows, info values, Designation rowspan 2), the light-blue title
    fill, bold-italic labels, the serif company name and the logo;
  * mapping: every label maps to its field or column heading — none is lost;
  * the built template validates without warnings, publishes, and its sample
    PDF has the same grid: same cell count, column / row proportions within
    2 %, labels in the same order, and ruling lines overlapping >= 90 % at
    150 dpi (tolerance documented in test_raster_grid_lines_match);
  * fields can be excluded / relabelled; whole rows go when all their fields do;
  * amounts tie out: every line is on the payslip ('any other' rows).
"""
import io
import os

import pytest
from fastapi import HTTPException

from app.modules.payroll import payslip_template_exact as exact
from app.modules.payroll import payslip_template_service as tpl
from tests._payslip_import_fixtures import GRID_LABELS, make_grid_payslip_pdf

_REAL = os.path.join(os.path.dirname(__file__), "fixtures", "payslip_import", "Payslip_Blank_Template.pdf")
_SOURCES = ["copy"] + (["real"] if os.path.isfile(_REAL) else [])


def _source(name: str) -> bytes:
    if name == "real":
        with open(_REAL, "rb") as fh:
            return fh.read()
    return make_grid_payslip_pdf()


@pytest.fixture(scope="module", params=_SOURCES)
def analysed(request):
    pdf = _source(request.param)
    return request.param, pdf, exact.analyze_exact(pdf)


def _built(analysis, **changes):
    return exact.build_exact({**analysis, **changes})


def _sample_pdf(built, country="IN"):
    return tpl.preview_pdf(built["htmlContent"], built["cssContent"], built["configurationJson"], country)


def _grid(pdf: bytes):
    import pdfplumber
    with pdfplumber.open(io.BytesIO(pdf)) as doc:
        page = doc.pages[0]
        tables = page.find_tables({"vertical_strategy": "lines", "horizontal_strategy": "lines",
                                   "snap_tolerance": 3, "join_tolerance": 3, "intersection_tolerance": 3})
        table = max(tables, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
        return [tuple(c) for c in table.cells], tuple(table.bbox)


def _proportions(cells, bbox):
    x0, top, x1, bottom = bbox
    w, h = x1 - x0, bottom - top
    return sorted((round((c[0] - x0) / w, 3), round((c[1] - top) / h, 3),
                   round((c[2] - x0) / w, 3), round((c[3] - top) / h, 3)) for c in cells)


# ── analysis ─────────────────────────────────────────────────────────────────

def test_grid_columns_rows_and_spans(analysed):
    _name, _pdf, a = analysed
    t = a["table"]
    assert len(t["colWidths"]) == 5 and len(t["rowHeights"]) == 17
    for got, want in zip(t["colWidths"], (34, 13, 13, 20, 20)):
        assert abs(got - want) <= 1.0, t["colWidths"]
    cells = {(c["r"], c["c"]): c for c in t["cells"]}
    assert cells[(0, 0)]["colspan"] == 5 and cells[(15, 0)]["colspan"] == 5 and cells[(16, 0)]["colspan"] == 5
    assert cells[(1, 1)]["colspan"] == 2
    assert cells[(2, 3)]["rowspan"] == 2 and cells[(2, 4)]["rowspan"] == 2
    assert t["rowHeights"][15] > 1.5 * t["rowHeights"][1]          # the tall 'in words' row
    assert cells[(0, 0)]["fill"] == "#C6D9F1" and a["primaryColor"] == "#C6D9F1"
    assert all(c["borders"][s] for c in t["cells"] for s in ("top", "right", "bottom", "left"))


def test_fonts_logo_and_company_name(analysed):
    _name, _pdf, a = analysed
    cells = {(c["r"], c["c"]): c for c in a["table"]["cells"]}
    assert cells[(1, 0)]["bold"] and cells[(1, 0)]["italic"] and not cells[(1, 0)]["serif"]
    assert cells[(0, 0)]["align"] == "center"
    company = a["blocksAbove"][-1]
    assert company["text"] == "Zoiko Industry Pvt. Ltd." and company["serif"] and company["bold"]
    assert company["align"] == "center"
    assert a["logoDataUri"].startswith("data:image/png;base64,") and a["logo"]["align"] == "center"


def test_every_label_is_mapped(analysed):
    _name, _pdf, a = analysed
    by_label = {}
    for f in a["fields"]:
        by_label.setdefault(f["pdfLabel"], set()).add(f["key"])
    expected = {
        "Pay Slip for the month of ____________": "title", "Employee ID": "employee_id", "DOJ": "date_of_joining",
        "Name": "name", "Designation": "designation", "Pan No.": "pan", "Paid Days": "paid_days",
        "Department": "department", "Bank Account No.": "bank_account", "Month Days": "month_days",
        "IFSC": "ifsc", "Mode of Payment": "payment_mode", "Particular's": "col_particulars",
        "Entitled": "col_entitled", "Earnings": "col_earnings", "Deductions": "col_deductions",
        "Basic Salary": "basic", "TDS": "tds", "HRA": "hra", "EPF Deduction": "epf",
        "Conv. Allowance": "conveyance", "Advance Deduction": "advance", "Special Allowance": "special",
        "Any other----": "other_deductions", "Bonus": "bonus", "Total Deductions": "total_deductions",
        "Employer Share of EPF": "employer_epf", "Total CTC": "total_ctc", "Net Paid": "net_paid",
        "Paid amount in words :": "net_in_words",
        "Note:- This is a computer generated statement, hence does not require signature": "note",
        "Zoiko Industry Pvt. Ltd.": "company_name",
    }
    for label, key in expected.items():
        assert by_label.get(label) == {key}, (label, by_label.get(label))
    assert a["unmapped"] == []
    assert set(GRID_LABELS) <= set(by_label)


def test_match_label_aliases_and_fuzzy():
    assert exact.match_label("Pan No.")[0] == "pan"
    assert exact.match_label("Any other----")[0] == "other_deductions"
    assert exact.match_label("Particular's")[0] == "col_particulars"
    assert exact.match_label("Basic Salry") == ("basic", "fuzzy")
    assert exact.match_label("Favourite colour") == (None, "")


# ── build ────────────────────────────────────────────────────────────────────

def test_built_template_validates_publishes_and_previews(analysed, db):
    from app.modules.organizations.models import Organization
    _name, _pdf, a = analysed
    built = _built(a)
    _frag, _css, warnings = tpl.validate_template(built["htmlContent"], built["cssContent"])
    assert warnings == []
    cfg = tpl.normalize_config(built["configurationJson"])
    assert cfg["pdfFonts"] == "full" and cfg["primaryColor"] == "#C6D9F1"
    assert cfg["fields"]["pan"]["label"] == "Pan No." and cfg["fields"]["other_deductions"]["label"] == "Any other----"
    assert cfg["fields"]["note"]["label"].startswith("Note:- This is a computer generated statement")
    assert cfg["fields"]["company_address"]["include"] is False

    org = Organization(organization_name="Org EX", organization_code="EXACT1", country="IN")
    db.add(org)
    db.commit()
    t = tpl.create_template(db, org.id, None, {"name": "Zoiko grid", **built})
    assert tpl.publish_template(db, org.id, t["id"], None)["activeVersion"]

    html = tpl.preview(built["htmlContent"], built["cssContent"], built["configurationJson"], "IN")["renderedHtml"]
    for text in ("Pay Slip for the month of June 2026", "Pan No.", "XXXXX1234X", "Particular&#x27;s",
                 "₹ 50,000.00", "₹ 1,600.00", "₹ 2,000.00", "₹ 6,200.00", "₹ 69,600.00", "NEFT", "EXMP0001234",
                 "Example Company Ltd", "Any other----", "₹ 200.00", "Employer Share of EPF", "₹ 1,800.00",
                 "Rupees Sixty Nine Thousand Six Hundred Only"):
        assert text in html, text
    # Advance has no data source -> '-'; Other Earnings row hidden (nothing in it).
    assert "Other Earnings" not in html


def test_rendered_pdf_has_the_same_grid(analysed):
    _name, pdf, a = analysed
    out = _sample_pdf(_built(a))
    src_cells, src_box = _grid(pdf)
    out_cells, out_box = _grid(out)
    assert len(out_cells) == len(src_cells)
    for s, o in zip(_proportions(src_cells, src_box), _proportions(out_cells, out_box)):
        assert all(abs(x - y) <= 0.02 for x, y in zip(s, o)), (s, o)


def test_labels_in_the_same_order(analysed):
    import pdfplumber
    _name, pdf, a = analysed
    out = _sample_pdf(_built(a))

    def order(doc_bytes, labels):
        with pdfplumber.open(io.BytesIO(doc_bytes)) as doc:
            text = doc.pages[0].extract_text() or ""
        positions = [text.find(lbl) for lbl in labels]
        assert all(p >= 0 for p in positions), [lbl for lbl, p in zip(labels, positions) if p < 0]
        return positions

    labels = ["Employee ID", "DOJ", "Pan No.", "Paid Days", "Bank Account No.", "IFSC", "Mode of Payment",
              "Basic Salary", "TDS", "HRA", "EPF Deduction", "Bonus", "Total Deductions", "Total CTC", "Net Paid",
              "Paid amount in words"]
    src, got = order(pdf, labels), order(out, labels)
    assert sorted(range(len(labels)), key=lambda i: src[i]) == sorted(range(len(labels)), key=lambda i: got[i])


def test_raster_grid_lines_match(analysed):
    """Ruling lines only (text differs: the source is blank, ours has sample
    values). Both pages are rendered at 150 dpi, cropped to their grid and
    scaled to the same size; line pixels are dark pixels in horizontal runs
    >= 25 % of the grid width or vertical runs >= 50 % of a body row. With a
    2 px dilation, >= 90 % of each image's line pixels must lie on the
    other's lines (allows anti-aliasing and sub-point rounding)."""
    import pdfplumber
    from PIL import Image, ImageFilter

    _name, pdf, a = analysed
    out = _sample_pdf(_built(a))
    W, H = 1000, 700

    def line_mask(doc_bytes) -> Image.Image:
        _cells, box = _grid(doc_bytes)
        with pdfplumber.open(io.BytesIO(doc_bytes)) as doc:
            page = doc.pages[0]
            img = page.crop((box[0] - 2, box[1] - 2, box[2] + 2, box[3] + 2)).to_image(resolution=150).original
        px = img.convert("L").resize((W, H)).tobytes()
        dark = [v < 140 for v in px]
        mask = [False] * (W * H)
        for y in range(H):                      # horizontal rules: runs >= 25 % of the width
            run = 0
            for x in range(W + 1):
                if x < W and dark[y * W + x]:
                    run += 1
                    continue
                if run >= W // 4:
                    for k in range(x - run, x):
                        mask[y * W + k] = True
                run = 0
        for x in range(W):                      # vertical rules: runs >= half a body row
            run = 0
            for y in range(H + 1):
                if y < H and dark[y * W + x]:
                    run += 1
                    continue
                if run >= 12:
                    for k in range(y - run, y):
                        mask[k * W + x] = True
                run = 0
        return Image.frombytes("L", (W, H), bytes(255 if m else 0 for m in mask))

    def overlap(a_img, b_img) -> float:
        a_px = a_img.tobytes()
        b_px = b_img.filter(ImageFilter.MaxFilter(5)).tobytes()      # 2 px dilation
        total = sum(1 for v in a_px if v)
        return sum(1 for va, vb in zip(a_px, b_px) if va and vb) / total

    src, got = line_mask(pdf), line_mask(out)
    assert sum(1 for v in src.tobytes() if v) > 1000 and sum(1 for v in got.tobytes() if v) > 1000
    forward, backward = overlap(src, got), overlap(got, src)
    print(f"grid line overlap: source->ours {forward:.3f}, ours->source {backward:.3f}")
    assert forward >= 0.90 and backward >= 0.90, (forward, backward)


# ── fields: exclude / relabel / rows ─────────────────────────────────────────

def _fields_with(a, **changes):
    out = []
    for f in a["fields"]:
        f = dict(f)
        if f["key"] in changes:
            f.update(changes[f["key"]])
        out.append(f)
    return out


def test_excluded_field_blanks_cells_and_row_goes_when_all_excluded(analysed):
    _name, _pdf, a = analysed
    built = _built(a, fields=_fields_with(a, pan={"include": False}))
    html = tpl.preview(built["htmlContent"], built["cssContent"], built["configurationJson"], "IN")["renderedHtml"]
    assert "Pan No." not in html and "XXXXX1234X" not in html and "Designation" in html
    built = _built(a, fields=_fields_with(a, paid_days={"include": False}, department={"include": False}))
    html = tpl.preview(built["htmlContent"], built["cssContent"], built["configurationJson"], "IN")["renderedHtml"]
    # 1 width-setting row + 17 grid rows, minus the removed Paid Days / Department row.
    assert "Paid Days" not in html and "Department" not in html and html.count("<tr") == 1 + 17 - 1


def test_relabel_and_required_fields_stay(analysed):
    _name, _pdf, a = analysed
    built = _built(a, fields=_fields_with(a, pan={"label": "PAN"}, name={"include": False},
                                          net_paid={"include": False}))
    cfg = tpl.normalize_config(built["configurationJson"])
    assert cfg["fields"]["pan"]["label"] == "PAN"
    assert cfg["fields"]["name"]["include"] and cfg["fields"]["net_paid"]["include"]


def test_unmapped_line_lands_in_any_other_and_totals_tie_out(analysed):
    _name, _pdf, a = analysed
    built = _built(a, fields=_fields_with(a, bonus={"include": False}))
    ctx = tpl.sample_context("IN", built["configurationJson"])
    placed = sum(ctx["earnings_by_code"][f["code"]]["amount"]
                 for k, f in tpl.normalize_config(built["configurationJson"])["fields"].items()
                 if f.get("side") == "earnings" and f["include"] and f["code"] in ctx["earnings_by_code"])
    assert placed + ctx["other_earnings"]["amount"] == ctx["totals"]["gross_pay"]
    html = tpl.preview(built["htmlContent"], built["cssContent"], built["configurationJson"], "IN")["renderedHtml"]
    assert "Other Earnings" in html and "₹ 2,000.00" in html          # the bonus, now in Other Earnings


# ── safety ───────────────────────────────────────────────────────────────────

def test_hostile_analysis_is_refused_or_neutralised(analysed):
    _name, _pdf, a = analysed
    evil = dict(a)
    evil["table"] = {**a["table"], "cells": [dict(c) for c in a["table"]["cells"]]}
    evil["table"]["cells"][0]["text"] = "<script>alert(1)</script>{{ 7*7 }}{% for %}"
    evil["blocksAbove"] = [{"text": '" onmouseover="x', "bold": True}]
    evil["fields"] = [f for f in a["fields"] if f["ref"] != "cell:0:0"]
    built = exact.build_exact(evil)
    tpl.validate_template(built["htmlContent"], built["cssContent"])      # still passes save-time checks
    assert "<script" not in built["htmlContent"] and "{{ 7*7 }}" not in built["htmlContent"]
    with pytest.raises(HTTPException):
        exact.build_exact({**a, "fields": [{"ref": "cell:1:0", "key": "__class__"}]})
    overlap = {**a["table"], "cells": a["table"]["cells"] + [{"r": 1, "c": 1, "rowspan": 1, "colspan": 1}]}
    with pytest.raises(HTTPException):
        exact.build_exact({**a, "table": overlap})
    with pytest.raises(HTTPException):
        exact.build_exact({**a, "table": {**a["table"], "cells": [{"r": 99, "c": 0}]}})


def test_pdf_without_a_ruled_table_is_refused():
    from tests._payslip_import_fixtures import make_payslip_pdf
    with pytest.raises(HTTPException) as exc:
        exact.analyze_exact(make_payslip_pdf())
    assert "Same style" in exc.value.detail


def test_mapping_can_choose_the_line_code(analysed):
    _name, _pdf, a = analysed
    built = _built(a, fields=_fields_with(a, conveyance={"code": "allowance_transport"}))
    assert tpl.normalize_config(built["configurationJson"])["fields"]["conveyance"]["code"] == "allowance_transport"
    with pytest.raises(HTTPException):
        _built(a, fields=_fields_with(a, conveyance={"code": "Allowance.Transport"}))
