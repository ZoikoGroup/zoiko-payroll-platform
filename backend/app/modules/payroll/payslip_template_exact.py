"""
modules/payroll/payslip_template_exact.py
-----------------------------------------
"Exact layout" PDF import: rebuild a company's own ruled payslip grid as a
payslip template, cell for cell.

analyze_exact(pdf bytes) — page 1 only, pdfplumber only (MIT):
    * the ruled table: pdfplumber's line-based table finder gives the cells;
      their edges are clustered into column / row boundaries, which gives
      column width percentages, row heights and colspan / rowspan;
    * per cell: text, bold / italic / serif / size (from the font name),
      alignment, fill colour and which of its four borders are drawn;
    * text and the logo above / below the grid (company name, notes);
    * every label is matched to a field of the payslip field catalogue
      (exact alias, then fuzzy); column headings (Particulars / Entitled /
      Earnings / Deductions) are recognised; anything else is reported as
      unmapped and kept as literal text — never dropped.

build_exact(choice) — from the (user-confirmed) analysis:
    * one <table> with a width-setting first row, the same cells, spans,
      borders, fills, fonts and row heights (tables + plain CSS only: the
      PDF engine is xhtml2pdf);
    * label cells print config.fields.<key>.label; value cells print the
      payslip's own values (line amounts by code, 'any other' totals,
      employer EPF, CTC, net pay ...). Excluding a field blanks its cells; a
      row whose fields are all excluded is removed;
    * 'any other' rows the PDF doesn't have are added as rows that only show
      when there is something in them, so every line is always on the slip.

Nothing uploaded is stored. Every result is validated again by
payslip_template_service.validate_template() when it is saved.
"""

from __future__ import annotations

import difflib
import html as _html
import io
import re
from typing import Dict, List, Optional, Tuple

from fastapi import HTTPException, status

MAX_ROWS = 80
MAX_COLS = 16
MAX_CELLS = 600
MAX_BLOCKS = 12
PRINTABLE_WIDTH_PT = 595.28 - 2 * 28.35      # A4 minus 10 mm margins (html_to_pdf)
_TOL = 2.0                                     # pt: edges this close are one line

COLUMN_ROLES = {"col_particulars", "col_entitled", "col_earnings", "col_deductions"}
_COLUMN_ALIASES = {
    "particulars": "col_particulars", "particular": "col_particulars", "description": "col_particulars",
    "component": "col_particulars", "components": "col_particulars",
    "entitled": "col_entitled", "entitlement": "col_entitled", "full month": "col_entitled", "rate": "col_entitled",
    "earnings": "col_earnings", "earned": "col_earnings", "amount": "col_earnings", "actual": "col_earnings",
    "deductions": "col_deductions", "deduction": "col_deductions",
}
FIELD_ALIASES = {
    "employee id": "employee_id", "emp id": "employee_id", "employee code": "employee_id", "emp code": "employee_id",
    "employee no": "employee_id", "staff id": "employee_id",
    "doj": "date_of_joining", "date of joining": "date_of_joining", "joining date": "date_of_joining",
    "name": "name", "employee name": "name", "emp name": "name",
    "pan no": "pan", "pan": "pan", "pan number": "pan",
    "designation": "designation", "position": "designation", "job title": "designation",
    "paid days": "paid_days", "payable days": "paid_days", "days paid": "paid_days", "days worked": "paid_days",
    "department": "department", "dept": "department",
    "bank account no": "bank_account", "bank account number": "bank_account", "account no": "bank_account",
    "bank a c no": "bank_account", "account number": "bank_account",
    "month days": "month_days", "total days": "month_days", "working days": "month_days", "days in month": "month_days",
    "ifsc": "ifsc", "ifsc code": "ifsc",
    "mode of payment": "payment_mode", "payment mode": "payment_mode",
    "bank name": "bank_name", "bank": "bank_name",
    "basic salary": "basic", "basic": "basic", "basic pay": "basic",
    "hra": "hra", "house rent allowance": "hra",
    "conv allowance": "conveyance", "conveyance allowance": "conveyance", "conveyance": "conveyance",
    "transport allowance": "conveyance",
    "special allowance": "special",
    "bonus": "bonus",
    "employer share of epf": "employer_epf", "employer epf": "employer_epf", "employer pf": "employer_epf",
    "employer share of pf": "employer_epf",
    "total ctc": "total_ctc", "ctc": "total_ctc",
    "gross earnings": "gross", "gross salary": "gross", "gross pay": "gross", "total earnings": "gross",
    "tds": "tds", "income tax": "tds",
    "epf deduction": "epf", "epf": "epf", "pf": "epf", "provident fund": "epf", "pf deduction": "epf",
    "advance deduction": "advance", "advance": "advance", "salary advance": "advance",
    "any other": "other_deductions", "other deductions": "other_deductions", "others": "other_deductions",
    "other earnings": "other_earnings",
    "total deductions": "total_deductions", "total deduction": "total_deductions",
    "net paid": "net_paid", "net pay": "net_paid", "net salary": "net_paid", "net payable": "net_paid",
    "take home": "net_paid",
    "paid amount in words": "net_in_words", "amount in words": "net_in_words", "net pay in words": "net_in_words",
    "in words": "net_in_words",
}
_TITLE = re.compile(r"^(pay\s*slip|payslip|salary\s*slip|pay\s*statement|salary\s*statement)\b", re.I)


def _bad(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail)


# ── label matching ───────────────────────────────────────────────────────────

def _norm(text: str) -> str:
    t = (text or "").lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", " ", t).strip()


def clean_pdf_label(text: str) -> str:
    """The PDF's own wording for a label: trailing fill-in blanks / colons off."""
    return re.sub(r"[\s_:]+$", "", (text or "").strip())


def match_label(text: str) -> Tuple[Optional[str], str]:
    """(field key or column role or None, how: exact / fuzzy / title / note / '')."""
    norm = _norm(text)
    if not norm:
        return None, ""
    if _TITLE.match(norm) and (" for " in f" {norm} " or "month" in norm):
        return "title", "title"
    if norm.startswith("note"):
        return "note", "note"
    if norm in _COLUMN_ALIASES:
        return _COLUMN_ALIASES[norm], "exact"
    if norm in FIELD_ALIASES:
        return FIELD_ALIASES[norm], "exact"
    close = difflib.get_close_matches(norm, list(FIELD_ALIASES), n=1, cutoff=0.85)
    if close:
        return FIELD_ALIASES[close[0]], "fuzzy"
    return None, ""


# ── PDF analysis ─────────────────────────────────────────────────────────────

def _cluster(values: List[float]) -> List[float]:
    out: List[float] = []
    for v in sorted(values):
        if out and v - out[-1] <= _TOL:
            continue
        out.append(v)
    return out


def _index(bounds: List[float], v: float) -> int:
    return min(range(len(bounds)), key=lambda i: abs(bounds[i] - v))


def _font_flags(fontname: str) -> dict:
    name = (fontname or "").split("+")[-1].lower()
    return {
        "bold": any(k in name for k in ("bold", "black", "heavy", "semibold", "demi")),
        "italic": any(k in name for k in ("italic", "oblique")),
        "serif": any(k in name for k in ("times", "serif", "georgia", "garamond", "cambria", "roman", "book"))
                 and "sans" not in name,
    }


def _style_of(words: List[dict], box: Tuple[float, float, float, float]) -> dict:
    """Text, font flags, size and alignment of the words inside one box."""
    if not words:
        return {"text": "", "bold": False, "italic": False, "serif": False, "size": None, "align": "left"}
    words = sorted(words, key=lambda w: (round(w["top"]), w["x0"]))
    text = " ".join(w["text"] for w in words)
    flags = _font_flags(words[0].get("fontname"))
    size = round(max(float(w.get("size") or 0) for w in words) * 2) / 2
    x0, x1 = min(w["x0"] for w in words), max(w["x1"] for w in words)
    left_gap, right_gap = x0 - box[0], box[2] - x1
    width = max(box[2] - box[0], 1)
    if abs(left_gap - right_gap) < max(6.0, 0.08 * width) and left_gap > 8:
        align = "center"
    elif right_gap < left_gap and right_gap < 12:
        align = "right"
    else:
        align = "left"
    return {"text": text, **flags, "size": size, "align": align}


def _hex(color) -> Optional[str]:
    from app.modules.payroll import payslip_template_import as base
    return base._rgb_hex(color)


def _side_covered(edges: List[dict], orient: str, fixed: float, lo: float, hi: float) -> Tuple[bool, list]:
    """Is the cell side from lo..hi (at `fixed`) drawn by edges (>= 60 %)?"""
    covered, found = 0.0, []
    for e in edges:
        if e["orientation"] != orient:
            continue
        if orient == "h":
            if abs(e["top"] - fixed) > _TOL:
                continue
            a, b = max(lo, e["x0"]), min(hi, e["x1"])
        else:
            if abs(e["x0"] - fixed) > _TOL:
                continue
            a, b = max(lo, e["top"]), min(hi, e["bottom"])
        if b > a:
            covered += b - a
            found.append(e)
    return covered >= 0.6 * max(hi - lo, 1), found


def _block_lines(words: List[dict], page_width: float) -> List[dict]:
    from app.modules.payroll import payslip_template_import as base
    out = []
    for line in base._lines(words):
        members = [w for w in words if abs(w["top"] - line["top"]) <= 3]
        style = _style_of(members, (0, 0, page_width, 0))
        x0, x1 = min(w["x0"] for w in members), max(w["x1"] for w in members)
        centre = (x0 + x1) / 2
        style["align"] = "center" if abs(centre - page_width / 2) < 30 else ("right" if x0 > page_width / 2 else "left")
        style["top"] = float(line["top"])
        style["bottom"] = max(float(w["bottom"]) for w in members)
        out.append(style)
    return out


def analyze_exact(data: bytes) -> dict:
    """The grid, its cells and the suggested field mapping of a PDF payslip."""
    import pdfplumber
    from app.modules.payroll import payslip_template_import as base

    if len(data) > base.MAX_PDF_BYTES:
        raise _bad(f"The PDF is larger than {base.MAX_PDF_BYTES // 1_000_000} MB.")
    if not data.lstrip()[:5] == b"%PDF-":
        raise _bad("This is not a PDF file.")
    try:
        pdf = pdfplumber.open(io.BytesIO(data))
    except Exception:  # noqa: BLE001 — encrypted / damaged
        raise _bad("This PDF could not be read (it may be password-protected or damaged).")
    with pdf:
        if not pdf.pages:
            raise _bad("This PDF has no pages.")
        page_count = len(pdf.pages)
        if page_count > base.MAX_PDF_PAGES:
            raise _bad(f"This PDF has {page_count} pages; upload a payslip of at most {base.MAX_PDF_PAGES} pages.")
        page = pdf.pages[0]
        width, height = float(page.width), float(page.height)
        try:
            words = page.extract_words(extra_attrs=["fontname", "size"], x_tolerance=1.5, y_tolerance=3)
            tables = page.find_tables({"vertical_strategy": "lines", "horizontal_strategy": "lines",
                                       "snap_tolerance": 3, "join_tolerance": 3, "intersection_tolerance": 3})
        except Exception:  # noqa: BLE001
            raise _bad("The text of this PDF could not be read.")
        if len(words) < 5:
            raise _bad("This PDF has no readable text — it looks like a scanned image. "
                       "Upload the original PDF exported from your payroll, Excel or Word file.")
        if not tables:
            raise _bad("No ruled table was found on page 1, so the layout can't be copied exactly. "
                       "Use 'Same style' instead.")
        table = max(tables, key=lambda t: (t.bbox[2] - t.bbox[0]) * (t.bbox[3] - t.bbox[1]))
        tx0, ttop, tx1, tbottom = (float(v) for v in table.bbox)
        boxes = [tuple(float(v) for v in c) for c in table.cells]
        xs = _cluster([b[0] for b in boxes] + [b[2] for b in boxes])
        ys = _cluster([b[1] for b in boxes] + [b[3] for b in boxes])
        if len(xs) - 1 > MAX_COLS or len(ys) - 1 > MAX_ROWS or len(boxes) > MAX_CELLS:
            raise _bad("This table is too large to copy exactly. Use 'Same style' instead.")
        edges = [e for e in page.edges if e.get("x0") is not None]
        rects = [r for r in page.rects if r.get("fill")]

        cells, seen = [], set()
        for box in boxes:
            c0, c1 = _index(xs, box[0]), _index(xs, box[2])
            r0, r1 = _index(ys, box[1]), _index(ys, box[3])
            if c1 <= c0 or r1 <= r0 or (r0, c0) in seen:
                continue
            seen.add((r0, c0))
            inside = [w for w in words if box[0] - 1 <= (w["x0"] + w["x1"]) / 2 <= box[2] + 1
                      and box[1] - 1 <= (w["top"] + w["bottom"]) / 2 <= box[3] + 1]
            style = _style_of(inside, box)
            fill = None
            area = (box[2] - box[0]) * (box[3] - box[1])
            for rect in rects:
                ox = min(box[2], float(rect["x1"])) - max(box[0], float(rect["x0"]))
                oy = min(box[3], float(rect["bottom"])) - max(box[1], float(rect["top"]))
                if ox > 0 and oy > 0 and ox * oy >= 0.6 * area:
                    colour = _hex(rect.get("non_stroking_color"))
                    if colour and colour != "#FFFFFF":
                        fill = colour
            borders, widths, colours = {}, [], []
            for side, orient, fixed, lo, hi in (("top", "h", box[1], box[0], box[2]),
                                                ("bottom", "h", box[3], box[0], box[2]),
                                                ("left", "v", box[0], box[1], box[3]),
                                                ("right", "v", box[2], box[1], box[3])):
                drawn, found = _side_covered(edges, orient, fixed, lo, hi)
                borders[side] = drawn
                for e in found:
                    widths.append(float(e.get("linewidth") or 1))
                    colours.append(_hex(e.get("stroking_color")) or "#000000")
            cells.append({"r": r0, "c": c0, "rowspan": r1 - r0, "colspan": c1 - c0, **style,
                          "fill": fill, "borders": borders,
                          "_lw": widths, "_bc": colours})

        # Above / below the grid: the logo and lines of text (company name, notes).
        above = [w for w in words if w["bottom"] <= ttop - 1]
        below = [w for w in words if w["top"] >= tbottom + 1]
        blocks_above = _block_lines(above, width)[:MAX_BLOCKS]
        blocks_below = _block_lines(below, width)[:MAX_BLOCKS]
        logo, logo_box = None, None
        top_images = [im for im in page.images if float(im["bottom"]) <= ttop + 1]
        if top_images:
            im = max(top_images, key=lambda i: (float(i["x1"]) - float(i["x0"])) * (float(i["bottom"]) - float(i["top"])))
            box = (max(0, float(im["x0"])), max(0, float(im["top"])),
                   min(width, float(im["x1"])), min(height, float(im["bottom"])))
            if box[2] - box[0] > 8 and box[3] - box[1] > 8:
                try:
                    logo = base._png_data_uri(page.crop(box).to_image(resolution=150).original, 480)
                    if len(logo) > base.MAX_LOGO_DATA_URI:
                        logo = base._png_data_uri(page.crop(box).to_image(resolution=96).original, 320)
                    if len(logo) > base.MAX_LOGO_DATA_URI:
                        logo = None
                except Exception:  # noqa: BLE001 — a logo is optional
                    logo = None
                if logo:
                    centre = (box[0] + box[2]) / 2
                    logo_box = {"top": box[1], "bottom": box[3], "widthPt": round(box[2] - box[0], 1),
                                "heightPt": round(box[3] - box[1], 1),
                                "align": "center" if abs(centre - width / 2) < 30 else (
                                    "right" if box[0] > width / 2 else "left")}
        page_image = base._png_data_uri(page.to_image(resolution=72).original, 700)

    all_widths = [w for c in cells for w in c.pop("_lw")]
    all_colours = [col for c in cells for col in c.pop("_bc")]
    border_width = round(sorted(all_widths)[len(all_widths) // 2], 2) if all_widths else 0.75
    border_colour = max(set(all_colours), key=all_colours.count) if all_colours else "#000000"
    col_widths = [round((xs[i + 1] - xs[i]) / (xs[-1] - xs[0]) * 100, 2) for i in range(len(xs) - 1)]
    row_heights = [round(ys[i + 1] - ys[i], 2) for i in range(len(ys) - 1)]
    fills = [c["fill"] for c in cells if c["fill"]]
    primary = max(set(fills), key=fills.count) if fills else "#1E3A8A"

    # Vertical layout: what comes before the grid, with the gaps between.
    head = []
    if logo_box:
        head.append({"kind": "logo", "top": logo_box["top"], "bottom": logo_box["bottom"]})
    head += [{"kind": "text", "index": i, "top": b["top"], "bottom": b["bottom"]} for i, b in enumerate(blocks_above)]
    head.sort(key=lambda h: h["top"])
    cursor = 28.35                                   # html_to_pdf's top margin
    for h in head:
        h["gapPt"] = round(max(0.0, h["top"] - cursor), 1)
        cursor = h["bottom"]
    table_gap = round(max(0.0, ttop - cursor), 1)

    fields = _suggest_mapping(cells, blocks_above, blocks_below)
    unmapped = [f["pdfLabel"] for f in fields if not f["key"]]
    return {
        "mode": "exact",
        "pageImage": page_image,
        "pageCount": page_count,
        "pageSize": [round(width, 2), round(height, 2)],
        "primaryColor": primary,
        "colors": sorted(set(fills)),
        "logoDataUri": logo,
        "logo": logo_box,
        "head": [{k: v for k, v in h.items() if k in ("kind", "index", "gapPt")} for h in head],
        "blocksAbove": [{k: v for k, v in b.items() if k not in ("top", "bottom")} for b in blocks_above],
        "blocksBelow": [{k: v for k, v in b.items() if k not in ("top", "bottom")} for b in blocks_below],
        "table": {
            "widthPct": round(min(100.0, (tx1 - tx0) / PRINTABLE_WIDTH_PT * 100), 2),
            "gapPt": table_gap,
            "colWidths": col_widths,
            "rowHeights": row_heights,
            "borderWidth": border_width,
            "borderColor": border_colour,
            "cells": sorted(cells, key=lambda c: (c["r"], c["c"])),
        },
        "fields": fields,
        "unmapped": unmapped,
        "catalogue": _catalogue_keys(),
        "notes": [
            "The table is rebuilt cell for cell: same columns, rows, merged cells, borders, fills and fonts.",
            "Labels come from your PDF; values come from each payslip. Lines without a row of their own are "
            "added to 'Any other' (and an 'Other Earnings' row that only appears when needed).",
            "Nothing from the uploaded PDF is stored.",
        ],
    }


def _catalogue_keys() -> List[str]:
    from app.modules.payroll.payslip_template_service import FIELD_CATALOGUE
    return [f["key"] for f in FIELD_CATALOGUE]


def _suggest_mapping(cells: List[dict], above: List[dict], below: List[dict]) -> List[dict]:
    """One row per piece of text: [ref, PDF label, mapped key, include, label]."""
    out = []
    company_done = False
    for i, b in enumerate(above):
        key, how = match_label(b["text"])
        if key is None and not company_done:
            key, how, company_done = "company_name", "position", True
        out.append(_mapping_row(f"above:{i}", b["text"], key, how))
    for c in cells:
        if c["text"]:
            key, how = match_label(c["text"])
            out.append(_mapping_row(f"cell:{c['r']}:{c['c']}", c["text"], key, how))
    for i, b in enumerate(below):
        key, how = match_label(b["text"])
        out.append(_mapping_row(f"below:{i}", b["text"], key, how))
    return out


def _mapping_row(ref: str, text: str, key: Optional[str], how: str) -> dict:
    label = text if key in ("note", None) or key in COLUMN_ROLES else clean_pdf_label(text)
    return {"ref": ref, "pdfLabel": text, "key": key, "match": how, "include": True,
            "label": label, "role": "column" if key in COLUMN_ROLES else ("field" if key else "text")}


# ── Template generation ──────────────────────────────────────────────────────

_LITERAL_UNSAFE = re.compile(r"[{}%<>\\`=]")
_COLOUR = re.compile(r"^#[0-9A-Fa-f]{6}$")
_ALIGN = {"left", "center", "right"}


def _literal(value, limit: int = 200) -> str:
    """PDF / user text as literal template text: never markup or template
    code (braces, %, <, >, = removed; quotes HTML-escaped)."""
    return _html.escape(_LITERAL_UNSAFE.sub("", str(value or ""))[:limit].strip(), quote=True)


def _num(value, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    return max(lo, min(hi, v))


def _colour(value, default: Optional[str] = None) -> Optional[str]:
    return value.upper() if isinstance(value, str) and _COLOUR.match(value) else default


def _validated_table(table) -> dict:
    """The table from the client, checked: bounded sizes, spans inside the
    grid, no overlapping cells, only known style values."""
    if not isinstance(table, dict):
        raise _bad("The analysed table is missing — analyse the PDF again.")
    cols = [_num(w, 0.5, 100, 0) for w in (table.get("colWidths") or [])][:MAX_COLS]
    rows = [_num(h, 4, 400, 18) for h in (table.get("rowHeights") or [])][:MAX_ROWS]
    if not cols or not rows or any(w <= 0 for w in cols):
        raise _bad("The analysed table has no columns or rows.")
    total = sum(cols)
    cols = [round(w / total * 100, 2) for w in cols]
    raw = table.get("cells") or []
    if not isinstance(raw, list) or len(raw) > MAX_CELLS:
        raise _bad("The analysed table has too many cells.")
    taken = set()
    cells = []
    for c in raw:
        if not isinstance(c, dict):
            raise _bad("A table cell is not valid.")
        try:
            r, col = int(c.get("r")), int(c.get("c"))
            rs, cs = int(c.get("rowspan") or 1), int(c.get("colspan") or 1)
        except (TypeError, ValueError):
            raise _bad("A table cell position is not valid.")
        if r < 0 or col < 0 or rs < 1 or cs < 1 or r + rs > len(rows) or col + cs > len(cols):
            raise _bad("A table cell lies outside the table.")
        for rr in range(r, r + rs):
            for cc in range(col, col + cs):
                if (rr, cc) in taken:
                    raise _bad("Two table cells overlap.")
                taken.add((rr, cc))
        borders = c.get("borders") if isinstance(c.get("borders"), dict) else {}
        cells.append({
            "r": r, "c": col, "rowspan": rs, "colspan": cs,
            "text": str(c.get("text") or "")[:200],
            "bold": bool(c.get("bold")), "italic": bool(c.get("italic")), "serif": bool(c.get("serif")),
            "size": _num(c.get("size"), 5, 40, 0) or None,
            "align": c.get("align") if c.get("align") in _ALIGN else "left",
            "fill": _colour(c.get("fill")),
            "borders": {s: bool(borders.get(s, True)) for s in ("top", "right", "bottom", "left")},
        })
    return {
        "widthPct": _num(table.get("widthPct"), 20, 100, 100),
        "gapPt": _num(table.get("gapPt"), 0, 300, 8),
        "colWidths": cols, "rowHeights": rows,
        "borderWidth": _num(table.get("borderWidth"), 0.25, 4, 0.75),
        "borderColor": _colour(table.get("borderColor"), "#000000"),
        "cells": sorted(cells, key=lambda x: (x["r"], x["c"])),
    }


def _validated_blocks(blocks) -> List[dict]:
    out = []
    for b in (blocks if isinstance(blocks, list) else [])[:MAX_BLOCKS]:
        if not isinstance(b, dict):
            continue
        out.append({"text": str(b.get("text") or "")[:200], "bold": bool(b.get("bold")),
                    "italic": bool(b.get("italic")), "serif": bool(b.get("serif")),
                    "size": _num(b.get("size"), 5, 40, 10),
                    "align": b.get("align") if b.get("align") in _ALIGN else "left"})
    return out


class _Styles:
    """CSS classes for the distinct cell / block styles."""

    def __init__(self, primary: str, border: str):
        self.primary, self.border = primary, border
        self.rules: Dict[tuple, str] = {}

    def cls(self, *, bold, italic, serif, size, align, fill=None, borders=None, height=None) -> str:
        key = (bold, italic, serif, size, align, fill, tuple(sorted((borders or {}).items())), height)
        if key not in self.rules:
            self.rules[key] = f"x{len(self.rules)}"
        return self.rules[key]

    def css(self) -> str:
        out = []
        serif_family = 'font-family: "Times New Roman", Times, serif'
        sans_family = "font-family: Arial, Helvetica, sans-serif"
        for (bold, italic, serif, size, align, fill, borders, height), name in self.rules.items():
            decl = [
                serif_family if serif else sans_family,
                f"font-weight: {'bold' if bold else 'normal'}",
                f"font-style: {'italic' if italic else 'normal'}",
                f"text-align: {align}",
            ]
            if size:
                decl.append(f"font-size: {size:g}pt")
            if fill:
                decl.append("background-color: " + ("var(--ps-primary)" if fill == self.primary else fill))
            for side, drawn in borders:
                decl.append(f"border-{side}: {self.border if drawn else 'none'}")
            if height:
                decl.append(f"height: {height:g}pt")
            out.append(f".{name} {{ {'; '.join(decl)}; }}")
        return "\n".join(out)


def _owners(cells: List[dict], n_rows: int, n_cols: int, keys: Dict[Tuple[int, int], Optional[str]]):
    """For each empty cell: the field label cell it belongs to (the nearest
    labelled cell to its left in the same row), and the column roles from the
    nearest heading row above (Particulars / Entitled / Earnings / Deductions)."""
    grid: Dict[Tuple[int, int], dict] = {}
    for c in cells:
        for rr in range(c["r"], c["r"] + c["rowspan"]):
            for cc in range(c["c"], c["c"] + c["colspan"]):
                grid[(rr, cc)] = c
    roles: Dict[Tuple[int, int], Optional[str]] = {}
    current = {}
    for r in range(n_rows):
        heading = [c for c in cells if c["r"] == r and keys.get((c["r"], c["c"])) in COLUMN_ROLES]
        if len(heading) >= 2:
            current = {}
            for c in heading:
                for cc in range(c["c"], c["c"] + c["colspan"]):
                    current[cc] = keys[(c["r"], c["c"])]
        for cc in range(n_cols):
            roles[(r, cc)] = current.get(cc)
    owner: Dict[Tuple[int, int], Tuple[int, int]] = {}
    for c in cells:
        if c["text"].strip():
            continue
        if roles.get((c["r"], c["c"])) == "col_particulars":
            continue                                   # a blank label slot
        cc = c["c"] - 1
        while cc >= 0:
            left = grid.get((c["r"], cc))
            if left is None:
                break
            ref = (left["r"], left["c"])
            if left["text"].strip():
                k = keys.get(ref)
                if k and k not in COLUMN_ROLES:
                    owner[(c["r"], c["c"])] = ref
                break
            if ref in owner:
                owner[(c["r"], c["c"])] = owner[ref]
                break
            if roles.get((left["r"], left["c"])) == "col_particulars":
                break
            cc = left["c"] - 1
    return grid, roles, owner


def _value_expr(key: str, kind: str) -> Optional[str]:
    """Template expression for a field's value (kind: amount / entitled)."""
    from app.modules.payroll.payslip_template_service import FIELDS_BY_KEY
    f = FIELDS_BY_KEY.get(key)
    if f is None:
        return None
    attr = "entitled_formatted" if kind == "entitled" else "amount_formatted"
    if f["side"] == "earnings":
        return f"earnings_by_code[config.fields.{key}.code].{attr} or '-'"
    if f["side"] == "deductions":
        return f"deductions_by_code[config.fields.{key}.code].{attr} or '-'"
    pair = "entitled_formatted" if kind == "entitled" else "paid_formatted"
    return {
        "other_earnings": "other_earnings.amount_formatted if other_earnings.count else '-'",
        "other_deductions": "other_deductions.amount_formatted if other_deductions.count else '-'",
        "employer_epf": f"employer.epf.{pair} or '-'",
        "total_ctc": f"totals.ctc.{pair} or '-'",
        "gross": "totals.gross_pay_formatted",
        "total_deductions": "totals.total_deductions_formatted",
        "net_paid": "totals.net_pay_formatted",
        "net_in_words": "totals.net_pay_in_words",
        "title": "payroll.period",
        "company_name": "company.name",
        "company_address": "company.address",
        "note": None,
        "logo": None,
    }.get(key, f["value"])


def _guard(key: str, inner: str) -> str:
    return f"{{% if config.fields.{key}.include %}}{inner}{{% endif %}}"


def build_exact(choice: dict) -> dict:
    """{'htmlContent', 'cssContent', 'configurationJson'} reproducing the
    analysed grid. Labels are literal text or config.fields labels; values
    are always placeholders; amounts only from the payslip."""
    from app.modules.payroll.payslip_template_service import (
        DEFAULT_CONFIG, FIELDS_BY_KEY, FIELD_CATALOGUE, clean_label,
    )
    from app.modules.payroll import payslip_template_import as base

    if not isinstance(choice, dict):
        raise _bad("The analysis is missing — analyse the PDF again.")
    table = _validated_table(choice.get("table"))
    above = _validated_blocks(choice.get("blocksAbove"))
    below = _validated_blocks(choice.get("blocksBelow"))
    primary = _colour(choice.get("primaryColor"), "#1E3A8A")
    n_rows, n_cols = len(table["rowHeights"]), len(table["colWidths"])

    # The user's mapping, by reference.
    mapping: Dict[str, dict] = {}
    for f in choice.get("fields") or []:
        if not isinstance(f, dict) or not isinstance(f.get("ref"), str):
            continue
        key = f.get("key")
        if key is not None and key not in FIELDS_BY_KEY and key not in COLUMN_ROLES:
            raise _bad(f"Unknown field '{str(key)[:40]}' in the mapping.")
        code = str(f.get("code") or "").strip().lower() or None
        if code is not None and not re.fullmatch(r"[a-z0-9_]{1,80}", code):
            raise _bad("A line code must be lower-case letters, digits and _ (e.g. allowance_transport).")
        mapping[f["ref"]] = {"key": key, "include": bool(f.get("include", True)),
                             "label": str(f.get("label") or "")[:200], "code": code}

    fields_cfg = {f["key"]: {"include": False} for f in FIELD_CATALOGUE}
    used_keys = set()

    def use(ref: str, pdf_text: str) -> Optional[str]:
        m = mapping.get(ref)
        key = m["key"] if m else match_label(pdf_text)[0]
        if key and key not in COLUMN_ROLES:
            label = clean_label((m or {}).get("label") or clean_pdf_label(pdf_text), 200 if key == "note" else 80)
            prev = fields_cfg.get(key) or {}
            include = (m or {}).get("include", True) or prev.get("include", False)
            fields_cfg[key] = {**prev, "include": include, "label": label or FIELDS_BY_KEY[key]["label"]}
            if (m or {}).get("code") and FIELDS_BY_KEY[key]["side"]:
                fields_cfg[key]["code"] = m["code"]
            used_keys.add(key)
        return key

    keys: Dict[Tuple[int, int], Optional[str]] = {}
    for c in table["cells"]:
        keys[(c["r"], c["c"])] = use(f"cell:{c['r']}:{c['c']}", c["text"]) if c["text"].strip() else None
    above_keys = [use(f"above:{i}", b["text"]) for i, b in enumerate(above)]
    below_keys = [use(f"below:{i}", b["text"]) for i, b in enumerate(below)]

    grid, roles, owner = _owners(table["cells"], n_rows, n_cols, keys)
    owned_by: Dict[Tuple[int, int], List[dict]] = {}
    for ref, label_ref in owner.items():
        owned_by.setdefault(label_ref, []).append(grid[ref])

    border = f"{table['borderWidth']:g}pt solid {table['borderColor']}"
    styles = _Styles(primary, border)

    def cell_kind(c) -> str:
        cols = {roles.get((c["r"], cc)) for cc in range(c["c"], c["c"] + c["colspan"])}
        return "entitled" if cols == {"col_entitled"} else "amount"

    def label_size(c):
        return c["size"] or 9

    def render_cell(c, *, key_override=None, text_override=None, height=None) -> str:
        ref = (c["r"], c["c"])
        key = key_override if key_override is not None else keys.get(ref)
        text = text_override if text_override is not None else c["text"]
        style = dict(bold=c["bold"], italic=c["italic"], serif=c["serif"], size=c["size"], align=c["align"],
                     fill=c["fill"], borders=c["borders"], height=height)
        content = ""
        if text.strip():
            if key and key not in COLUMN_ROLES:
                inner = f"{{{{ config.fields.{key}.label }}}}"
                expr = _value_expr(key, "amount")
                if expr and not owned_by.get(ref) and key not in ("note",):
                    inner += f" {{{{ {expr} }}}}"
                content = _guard(key, inner)
            else:
                content = _literal(text)
        else:
            label_ref = owner.get(ref)
            label_key = keys.get(label_ref) if label_ref else None
            if label_ref is not None and key_override is not None:
                label_key = key_override
            if label_key:
                kind = cell_kind(c)
                expr = _value_expr(label_key, kind)
                if expr:
                    content = _guard(label_key, f"{{{{ {expr} }}}}")
                source = grid[label_ref]
                f = FIELDS_BY_KEY[label_key]
                numeric = bool(f["side"]) or label_key in (
                    "other_earnings", "other_deductions", "employer_epf", "total_ctc", "gross",
                    "total_deductions", "net_paid")
                style.update(bold=False, italic=False, serif=False, size=label_size(source),
                             align="right" if numeric else "left")
        cls = styles.cls(**style)
        span = (f' colspan="{c["colspan"]}"' if c["colspan"] > 1 else "") + (
            f' rowspan="{c["rowspan"]}"' if c["rowspan"] > 1 else "")
        return f'<td class="{cls}"{span}>{content}</td>'

    # Rows covered by a rowspan from an earlier row can't be removed alone.
    spanned = set()
    for c in table["cells"]:
        for rr in range(c["r"] + 1, c["r"] + c["rowspan"]):
            spanned.add(rr)

    rows_html: List[str] = []
    for r in range(n_rows):
        starting = [c for c in table["cells"] if c["r"] == r]
        height = table["rowHeights"][r]
        tds = "".join(render_cell(c, height=height) for c in starting)
        row = f"<tr>{tds}</tr>"
        row_keys = set()
        removable = r not in spanned and all(c["rowspan"] == 1 for c in starting)
        for c in starting:
            k = keys.get((c["r"], c["c"]))
            if c["text"].strip():
                if not k or k in COLUMN_ROLES:
                    removable = False
                else:
                    row_keys.add(k)
            elif owner.get((c["r"], c["c"])):
                row_keys.add(keys[owner[(c["r"], c["c"])]])
        if removable and row_keys and not any(FIELDS_BY_KEY[k]["required"] for k in row_keys):
            cond = " or ".join(f"config.fields.{k}.include" for k in sorted(row_keys))
            row = f"{{% if {cond} %}}{row}{{% endif %}}"
        rows_html.append(row)

    # Rows the PDF doesn't have but every payslip needs.
    def extra_row(key: str, condition: Optional[str] = None) -> str:
        expr = _value_expr(key, "amount")
        lbl = FIELDS_BY_KEY[key]["label"]
        fields_cfg[key] = {**fields_cfg.get(key, {}), "include": True, "label": fields_cfg.get(key, {}).get("label") or lbl}
        cls = styles.cls(bold=True, italic=True, serif=False, size=9, align="left", borders={
            "top": True, "right": True, "bottom": True, "left": True}, height=table["rowHeights"][-1])
        row = (f'<tr><td class="{cls}" colspan="{n_cols}">{{{{ config.fields.{key}.label }}}}: '
               f"{{{{ {expr} }}}}</td></tr>")
        return f"{{% if {condition} %}}{row}{{% endif %}}" if condition else row

    def line_row_like(r: int, key: str, condition: str) -> Optional[str]:
        """A copy of row r's structure with only `key`'s label and values."""
        starting = [c for c in table["cells"] if c["r"] == r]
        if r in spanned or any(c["rowspan"] > 1 for c in starting):
            return None
        label_cell = next((c for c in starting if keys.get((c["r"], c["c"])) and FIELDS_BY_KEY.get(
            keys[(c["r"], c["c"])], {}).get("side") == "earnings"), None)
        if label_cell is None:
            return None
        values = {(v["r"], v["c"]) for v in owned_by.get((label_cell["r"], label_cell["c"]), [])}
        tds = []
        for c in starting:
            ref = (c["r"], c["c"])
            if c is label_cell:
                tds.append(render_cell(c, key_override=key, height=table["rowHeights"][r]))
            elif ref in values:
                kind = cell_kind(c)
                style = dict(bold=False, italic=False, serif=False, size=label_size(label_cell), align="right",
                             fill=c["fill"], borders=c["borders"], height=table["rowHeights"][r])
                span = f' colspan="{c["colspan"]}"' if c["colspan"] > 1 else ""
                tds.append(f'<td class="{styles.cls(**style)}"{span}>'
                           f"{{{{ {_value_expr(key, kind)} }}}}</td>")
            else:
                style = dict(bold=False, italic=False, serif=False, size=c["size"], align="left",
                             fill=c["fill"], borders=c["borders"], height=table["rowHeights"][r])
                span = f' colspan="{c["colspan"]}"' if c["colspan"] > 1 else ""
                tds.append(f'<td class="{styles.cls(**style)}"{span}></td>')
        fields_cfg[key] = {**fields_cfg.get(key, {}), "include": True,
                           "label": fields_cfg.get(key, {}).get("label") or FIELDS_BY_KEY[key]["label"]}
        return f"{{% if {condition} %}}<tr>{''.join(tds)}</tr>{{% endif %}}"

    if "other_earnings" not in used_keys:
        earn_rows = [c["r"] for c in table["cells"]
                     if FIELDS_BY_KEY.get(keys.get((c["r"], c["c"])) or "", {}).get("side") == "earnings"]
        row = line_row_like(max(earn_rows), "other_earnings", "other_earnings.count") if earn_rows else None
        if row:
            rows_html.insert(max(earn_rows) + 1, row)
        else:
            rows_html.append(extra_row("other_earnings", "other_earnings.count"))
    if "other_deductions" not in used_keys:
        rows_html.append(extra_row("other_deductions", "other_deductions.count"))
    for key in ("name", "net_paid"):
        if key not in used_keys:
            rows_html.append(extra_row(key))

    # A first row that sets the column widths (no borders, no height).
    sizer = "".join(f'<td width="{w:g}%" class="px-z"></td>' for w in table["colWidths"])
    table_html = (f'<table class="px-t" width="{table["widthPct"]:g}%" align="center">'
                  f'<tr class="px-z">{sizer}</tr>{"".join(rows_html)}</table>')

    # Header: logo and text lines in the PDF's order and spacing.
    head_html = []
    logo = choice.get("logoDataUri") if choice.get("includeLogo", True) else None
    if logo and (not isinstance(logo, str) or not logo.startswith("data:image/png;base64,")
                 or len(logo) > base.MAX_LOGO_DATA_URI):
        logo = None
    logo_meta = choice.get("logo") if isinstance(choice.get("logo"), dict) else {}
    order = choice.get("head") if isinstance(choice.get("head"), list) else []
    if not order:
        order = ([{"kind": "logo", "gapPt": 0}] if logo else []) + [
            {"kind": "text", "index": i, "gapPt": 4} for i in range(len(above))]
    for h in order[:MAX_BLOCKS + 1]:
        if not isinstance(h, dict):
            continue
        gap = _num(h.get("gapPt"), 0, 200, 0)
        if h.get("kind") == "logo" and logo:
            align = logo_meta.get("align") if logo_meta.get("align") in _ALIGN else "center"
            w = _num(logo_meta.get("widthPt"), 10, 520, 160)
            ht = _num(logo_meta.get("heightPt"), 8, 300, 48)
            fields_cfg["logo"] = {**fields_cfg.get("logo", {}), "include": True}
            cls = styles.cls(bold=False, italic=False, serif=False, size=None, align=align)
            head_html.append(_guard("logo", f'<p class="{cls} px-b" style="margin-top: {gap:g}pt">'
                                            f'<img src="{logo}" alt="" width="{w:g}" height="{ht:g}"></p>'))
        elif h.get("kind") == "text":
            try:
                i = int(h.get("index"))
            except (TypeError, ValueError):
                continue
            if not 0 <= i < len(above):
                continue
            head_html.append(_block_html(above[i], above_keys[i], gap, styles))
    foot_html = [_block_html(b, below_keys[i], 4, styles) for i, b in enumerate(below)]

    html_out = ('<div class="px">' + "".join(head_html) +
                f'<div style="margin-top: {table["gapPt"]:g}pt">{table_html}</div>' +
                "".join(foot_html) + "</div>")
    css = (
        "body { font-family: Arial, Helvetica, sans-serif; color: #000000; background-color: #ffffff; "
        "font-size: 9pt; margin: 0; }\n"
        ".px { max-width: 760px; margin: 0 auto; }\n"
        ".px-b { margin: 0; }\n"
        "table.px-t { border-collapse: collapse; }\n"
        "table.px-t td { padding: 1pt 4pt; vertical-align: middle; }\n"
        ".px-z, .px-z td { border: none; padding: 0; height: 0; font-size: 1pt; line-height: 0; }\n"
        + styles.css()
    )
    note_text = fields_cfg["note"].get("label") if fields_cfg["note"].get("include") else None
    config = {
        "primaryColor": primary,
        "accentColor": "#FFFFFF",
        "showCompanyLogo": True,
        "showEmployeeBank": True,
        "showNetInWords": True,
        "disclaimerText": (note_text or DEFAULT_CONFIG["disclaimerText"])[:500],
        "pdfFonts": "full",
        "fields": fields_cfg,
    }
    return {"htmlContent": html_out, "cssContent": css, "configurationJson": config}


def _block_html(block: dict, key: Optional[str], gap: float, styles: _Styles) -> str:
    cls = styles.cls(bold=block["bold"], italic=block["italic"], serif=block["serif"], size=block["size"],
                     align=block["align"])
    if key and key not in COLUMN_ROLES:
        expr = _value_expr(key, "amount")
        inner = f"{{{{ {expr} }}}}" if key in ("company_name", "company_address") and expr else (
            f"{{{{ config.fields.{key}.label }}}}" + (f" {{{{ {expr} }}}}" if expr and key != "note" else ""))
        content = _guard(key, inner)
    else:
        content = _literal(block["text"])
    return f'<p class="{cls} px-b" style="margin-top: {gap:g}pt">{content}</p>'
