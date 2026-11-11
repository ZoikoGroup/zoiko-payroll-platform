"""
modules/payroll/payslip_template_import.py
------------------------------------------
Turning a company's existing payslip design into a payslip template.

Word (.docx) — docx_to_template()
    mammoth converts the document (headings, paragraphs, tables, bold/italic,
    embedded images) to HTML. Placeholders typed in Word ({{ employee.name }})
    are kept; one Word cannot express — repeating a table row per earnings
    line — is written as a row that uses {{ earning.label }} /
    {{ earning.amount_formatted }} (or deduction.*): that row is repeated for
    every line automatically.

PDF — analyze_pdf() + build_from_analysis()
    A PDF is a picture of ONE payslip, not a template: its values are fixed
    text at fixed positions. So it is not converted 1:1. analyze_pdf() reads
    page 1 (pdfplumber, MIT) and suggests: the main colour, the logo, the
    title, which labelled fields the payslip shows (with the placeholder each
    maps to), the earnings / deductions headings and total labels, the footer
    text and the layout. The user confirms or corrects that in the import
    wizard; build_from_analysis() then generates a flowing, table-based
    template that uses the PDF's own wording and always repeats the earnings
    and deduction lines — similar in look, correct for every employee.

Nothing uploaded is stored. The PDF's values (a real person's pay, if a real
payslip is uploaded) are only returned to the uploader for the wizard; only
labels the user keeps end up in the template. Every result still goes
through payslip_template_service.validate_template() when it is saved.
"""

from __future__ import annotations

import base64
import html as _html
import io
import re
import zipfile
from typing import List, Optional

from fastapi import HTTPException, status

MAX_DOCX_BYTES = 5_000_000
MAX_DOCX_UNZIPPED_BYTES = 40_000_000
MAX_DOCX_ENTRIES = 2_000
MAX_PDF_BYTES = 5_000_000
MAX_PDF_PAGES = 5
MAX_LOGO_DATA_URI = 120_000


def _bad(detail: str) -> HTTPException:
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail)


# ── Word (.docx) ─────────────────────────────────────────────────────────────

WORD_BASE_CSS = """body { font-family: Arial, Helvetica, sans-serif; color: #1e293b; background-color: #ffffff; font-size: 10pt; margin: 0; }
.payslip-doc { max-width: 820px; margin: 0 auto; padding: 24px; }
h1 { font-size: 16pt; color: var(--ps-primary); margin: 0 0 6px 0; }
h2 { font-size: 13pt; color: var(--ps-primary); margin: 10px 0 4px 0; }
h3 { font-size: 11pt; margin: 8px 0 4px 0; }
p { margin: 3px 0; }
table { border-collapse: collapse; width: 100%; margin: 6px 0 12px 0; }
td, th { border: 1px solid #cbd5e1; padding: 5px 8px; vertical-align: top; font-size: 9pt; }
th { background-color: var(--ps-primary); color: #ffffff; }
img { max-width: 100%; }"""

_JINJA_SPAN = re.compile(r"\{\{.*?\}\}|\{%.*?%\}", re.S)
_TAG = re.compile(r"<[^>]+>")
_LINK = re.compile(r"<a\b[^>]*>(.*?)</a>", re.S | re.I)
_ROW = re.compile(r"<tr\b[^>]*>.*?</tr>", re.S | re.I)
_PARA = re.compile(r"<(p|li)\b[^>]*>.*?</\1>", re.S | re.I)
_SMART = {"“": '"', "”": '"', "‘": "'", "’": "'", " ": " "}


def _clean_jinja(match) -> str:
    """Word splits a typed placeholder across formatting runs and curls its
    quotes: take the tags out of it (kept, in order, right after it so the
    HTML stays balanced), unescape it, straighten the quotes."""
    span = match.group(0)
    tags = "".join(_TAG.findall(span))
    inner = _html.unescape(_TAG.sub("", span))
    for smart, plain in _SMART.items():
        inner = inner.replace(smart, plain)
    return inner + tags


_TABLE = re.compile(r"(<table\b.*?</table>)", re.S | re.I)


def _repeat_line_blocks(html_text: str) -> str:
    """A table row that uses earning.* / deduction.* repeats once per
    earnings / deduction line; outside tables, a paragraph does."""
    def wrap(match):
        block = match.group(0)
        if re.search(r"\{\{[^}]*\bearning\.", block):
            return "{% for earning in earnings %}" + block + "{% endfor %}"
        if re.search(r"\{\{[^}]*\bdeduction\.", block):
            return "{% for deduction in deductions %}" + block + "{% endfor %}"
        return block

    parts = _TABLE.split(html_text)          # odd indexes are whole tables
    return "".join(_ROW.sub(wrap, part) if i % 2 else _PARA.sub(wrap, part) for i, part in enumerate(parts))


def _check_docx_zip(data: bytes) -> None:
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_DOCX_ENTRIES:
                raise _bad("This Word file has too many parts to import.")
            if sum(i.file_size for i in infos) > MAX_DOCX_UNZIPPED_BYTES:
                raise _bad("This Word file is too large once unpacked (images?). Reduce the images and try again.")
            if "word/document.xml" not in archive.namelist():
                raise _bad("This is not a Word (.docx) document.")
    except zipfile.BadZipFile:
        raise _bad("This is not a Word (.docx) document (old .doc files: save as .docx first).")


def docx_to_template(data: bytes) -> dict:
    """{'htmlContent', 'cssContent', 'notes'} from a .docx file."""
    import mammoth

    if len(data) > MAX_DOCX_BYTES:
        raise _bad(f"The Word file is larger than {MAX_DOCX_BYTES // 1_000_000} MB.")
    _check_docx_zip(data)
    try:
        result = mammoth.convert_to_html(io.BytesIO(data))
    except Exception:  # noqa: BLE001 — any parser failure is a bad upload
        raise _bad("This Word document could not be read.")
    body = result.value or ""
    body = _LINK.sub(r"\1", body)                     # links become plain text
    body = _JINJA_SPAN.sub(_clean_jinja, body)
    body = _repeat_line_blocks(body)
    notes = []
    if result.messages:
        notes.append(f"{len(result.messages)} Word formatting feature(s) have no HTML equivalent and were simplified.")
    return {"htmlContent": f'<div class="payslip-doc">{body}</div>', "cssContent": WORD_BASE_CSS, "notes": notes}


# ── PDF analysis ─────────────────────────────────────────────────────────────

# Detail fields: placeholder -> label patterns (matched at the start of a
# label segment, case-insensitive).
FIELD_PATTERNS = [
    ("employee.id", r"(employee|emp\.?|staff)\s*(id|code|no\.?|number|#)"),
    ("employee.name", r"(employee|emp\.?|staff)\s*name|name\b"),
    ("employee.department", r"department|dept\.?\b"),
    ("employee.designation", r"designation|position|job\s*title|role\b"),
    ("employee.date_of_joining", r"date\s*of\s*joining|joining\s*date|doj\b|date\s*joined"),
    ("employee.bank_account", r"(bank\s*)?(account|a/c)\s*(no\.?|number|#)?"),
    ("employee.bank_name", r"bank(\s*name)?\b"),
    ("employee.identifiers", r"pan\b|uan\b|tax\s*(id|code|no\.?)|tin\b|ssn\b|ni\s*(no\.?|number)|nino\b|ird\b|nric\b"),
    ("payroll.pay_date", r"pay(ment)?\s*date|date\s*of\s*payment|paid\s*on"),
    ("payroll.period", r"pay\s*period|salary\s*(month|period|for)|pay\s*month|month\b|period\b"),
    ("payroll.payable_days", r"(paid|payable|worked)\s*days|days\s*(paid|worked|payable)"),
    ("payroll.total_days", r"(working|total)\s*days"),
    ("payroll.payslip_number", r"(payslip|slip)\s*(no\.?|number|#)"),
    ("company.registration_no", r"(registration|reg\.?|cin|employer)\s*(no\.?|number|id)"),
]
DETAIL_PLACEHOLDERS = [key for key, _p in FIELD_PATTERNS]
_TOTALS = [
    ("gross", r"gross\s*(earnings|pay|salary|total)?|total\s*earnings"),
    ("total_deductions", r"total\s*deductions?"),
    ("net", r"net\s*(pay|salary|amount|payable|take\s*home)?|take[\s-]*home"),
    ("words", r"(amount|net\s*pay|rupees)?\s*in\s*words"),
]
_HEADERS = [("earnings", r"earnings?|income|allowances"), ("deductions", r"deductions?")]
_TITLE = re.compile(r"pay\s*slip|payslip|salary\s*slip|pay\s*statement|pay\s*advice|salary\s*statement", re.I)


def _rgb_hex(color) -> Optional[str]:
    """pdfplumber colour (gray / RGB / CMYK, 0..1) -> #RRGGBB, else None."""
    if color is None or isinstance(color, str):
        return None
    try:
        values = [float(v) for v in (color if isinstance(color, (list, tuple)) else [color])]
    except (TypeError, ValueError):
        return None
    if len(values) == 1:
        r = g = b = values[0]
    elif len(values) == 3:
        r, g, b = values
    elif len(values) == 4:
        c, m, y, k = values
        r, g, b = (1 - c) * (1 - k), (1 - m) * (1 - k), (1 - y) * (1 - k)
    else:
        return None
    if not all(0 <= v <= 1.0001 for v in (r, g, b)):
        return None
    return "#{:02X}{:02X}{:02X}".format(*(min(255, round(v * 255)) for v in (r, g, b)))


def _is_neutral(hex_color: str) -> bool:
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (1, 3, 5))
    return max(r, g, b) - min(r, g, b) < 24 or min(r, g, b) > 225   # grey, black, white or near-white


def _lines(words: list) -> list:
    """Words grouped into lines (by vertical position), each split into
    segments wherever the horizontal gap is large (two-column layouts)."""
    rows: list = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if rows and abs(rows[-1]["top"] - w["top"]) <= 3:
            rows[-1]["words"].append(w)
        else:
            rows.append({"top": w["top"], "words": [w]})
    out = []
    for row in rows:
        ws = sorted(row["words"], key=lambda w: w["x0"])
        segments, current = [], [ws[0]]
        for prev, w in zip(ws, ws[1:]):
            if w["x0"] - prev["x1"] > max(18.0, 2.2 * float(prev.get("size") or 10)):
                segments.append(current)
                current = [w]
            else:
                current.append(w)
        segments.append(current)
        out.append({
            "top": row["top"],
            "size": max(float(w.get("size") or 0) for w in ws),
            "text": " ".join(w["text"] for w in ws),
            "segments": [{"text": " ".join(w["text"] for w in s), "x0": s[0]["x0"], "x1": s[-1]["x1"]}
                         for s in segments],
        })
    return out


def _match(patterns, text: str):
    cleaned = text.strip().strip(":").strip()
    for key, pattern in patterns:
        if re.match(rf"^\s*(?:{pattern})\s*(?::|$|\s)", cleaned + " ", re.I):
            return key
    return None


def _split_label_value(segment_text: str):
    """'Employee Name: Asha Rao' -> ('Employee Name', 'Asha Rao')."""
    if ":" in segment_text:
        label, value = segment_text.split(":", 1)
        return label.strip(), value.strip()
    return segment_text.strip(), ""


def _png_data_uri(image, max_width: int) -> str:
    if image.width > max_width:
        image = image.resize((max_width, max(1, round(image.height * max_width / image.width))))
    buf = io.BytesIO()
    image.convert("RGB").save(buf, format="PNG", optimize=True)
    return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")


def analyze_pdf(data: bytes) -> dict:
    """Suggestions for building a template from page 1 of a digital PDF payslip."""
    import pdfplumber

    if len(data) > MAX_PDF_BYTES:
        raise _bad(f"The PDF is larger than {MAX_PDF_BYTES // 1_000_000} MB.")
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
        if page_count > MAX_PDF_PAGES:
            raise _bad(f"This PDF has {page_count} pages; upload a payslip of at most {MAX_PDF_PAGES} pages.")
        page = pdf.pages[0]
        try:
            words = page.extract_words(extra_attrs=["size", "non_stroking_color"], x_tolerance=1.5, y_tolerance=3)
        except Exception:  # noqa: BLE001
            raise _bad("The text of this PDF could not be read.")
        if len(words) < 5:
            raise _bad("This PDF has no readable text — it looks like a scanned image. "
                       "Upload the original PDF exported from your payroll or Word file.")
        width, height = float(page.width), float(page.height)
        lines = _lines(words)

        # Main colour: largest coloured filled areas; else coloured text.
        weights: dict = {}
        for rect in page.rects:
            if not rect.get("fill"):
                continue
            hex_color = _rgb_hex(rect.get("non_stroking_color"))
            if hex_color and not _is_neutral(hex_color):
                weights[hex_color] = weights.get(hex_color, 0) + float(rect["width"]) * float(rect["height"])
        if not weights:
            for w in words:
                hex_color = _rgb_hex(w.get("non_stroking_color"))
                if hex_color and not _is_neutral(hex_color):
                    weights[hex_color] = weights.get(hex_color, 0) + float(w.get("size") or 10)
        colors = [c for c, _w in sorted(weights.items(), key=lambda kv: -kv[1])][:4]

        # Logo: the largest image in the top third of the page.
        logo = None
        top_images = [im for im in page.images if float(im["top"]) < height / 3]
        if top_images:
            im = max(top_images, key=lambda i: (float(i["x1"]) - float(i["x0"])) * (float(i["bottom"]) - float(i["top"])))
            box = (max(0, float(im["x0"])), max(0, float(im["top"])),
                   min(width, float(im["x1"])), min(height, float(im["bottom"])))
            if box[2] - box[0] > 8 and box[3] - box[1] > 8:
                try:
                    logo = _png_data_uri(page.crop(box).to_image(resolution=150).original, 320)
                    if len(logo) > MAX_LOGO_DATA_URI:
                        logo = _png_data_uri(page.crop(box).to_image(resolution=72).original, 200)
                    if len(logo) > MAX_LOGO_DATA_URI:
                        logo = None
                except Exception:  # noqa: BLE001 — a logo is optional
                    logo = None

        page_image = _png_data_uri(page.to_image(resolution=72).original, 700)

    # Title and company name (top quarter).
    top_lines = [ln for ln in lines if ln["top"] < height / 4]
    title_line = next((ln for ln in lines if _TITLE.search(ln["text"])), None)
    title = _TITLE.search(title_line["text"]).group(0).upper() if title_line else "PAYSLIP"
    company_line = max((ln for ln in top_lines if not _TITLE.search(ln["text"])), key=lambda ln: ln["size"], default=None)

    fields, seen = [], set()
    totals: dict = {}
    headers: dict = {}
    for ln in lines:
        segments = ln["segments"]
        for i, seg in enumerate(segments):
            label, value = _split_label_value(seg["text"])
            if not value and i + 1 < len(segments):
                nxt = segments[i + 1]["text"]
                if not _match(FIELD_PATTERNS, nxt) and not _match(_TOTALS, nxt):
                    value = nxt
            total_key = _match(_TOTALS, label)
            if total_key and total_key not in totals and len(label) <= 40:
                totals[total_key] = {"label": label.strip(":"), "value": value}
                continue
            header_key = _match(_HEADERS, label)
            if header_key and header_key not in headers and not value and len(label) <= 30:
                headers[header_key] = {"label": label.strip(":"), "top": ln["top"], "x0": seg["x0"]}
                continue
            field_key = _match(FIELD_PATTERNS, label)
            if field_key and field_key not in seen and len(label) <= 40:
                seen.add(field_key)
                fields.append({"placeholder": field_key, "label": label.strip(":"), "value": value, "include": True})

    # Earnings / deductions headings on the same line -> side by side.
    layout = "side"
    if "earnings" in headers and "deductions" in headers:
        if abs(headers["earnings"]["top"] - headers["deductions"]["top"]) > 6:
            layout = "stacked"

    footer_lines = [ln["text"] for ln in lines if ln["top"] > height * 0.82 and len(ln["text"]) > 30]
    disclaimer = footer_lines[-1] if footer_lines else ""

    return {
        "pageImage": page_image,
        "pageCount": page_count,
        "colors": colors,
        "primaryColor": colors[0] if colors else "#1E3A8A",
        "logoDataUri": logo,
        "title": title,
        "companyNameSample": company_line["text"] if company_line else "",
        "layout": layout,
        "fields": fields,
        "sections": {
            "earningsTitle": headers.get("earnings", {}).get("label") or "Earnings",
            "deductionsTitle": headers.get("deductions", {}).get("label") or "Deductions",
            "grossLabel": totals.get("gross", {}).get("label") or "Gross Earnings",
            "totalDeductionsLabel": totals.get("total_deductions", {}).get("label") or "Total Deductions",
            "netLabel": totals.get("net", {}).get("label") or "Net Pay",
            "showNetInWords": "words" in totals,
        },
        "disclaimer": disclaimer,
        "detailPlaceholders": DETAIL_PLACEHOLDERS,
        "notes": [
            "The template is built in a flowing layout using your PDF's colours, logo and wording. "
            "It will look similar, not identical, and the earnings and deduction lines repeat for every employee.",
            "Nothing from the uploaded PDF is stored; the values shown are only used to help you check the mapping.",
        ],
    }


# ── Template generation from the confirmed analysis ──────────────────────────

_PLACEHOLDER_EXPR = {
    "employee.name": "{{ employee.name }}",
    "employee.id": "{{ employee.id }}",
    "employee.department": "{{ employee.department }}",
    "employee.designation": "{{ employee.designation }}",
    "employee.date_of_joining": "{{ employee.date_of_joining }}",
    "employee.bank_account": "{{ employee.bank_account }}",
    "employee.bank_name": "{{ employee.bank_name }}",
    "payroll.pay_date": "{{ payroll.pay_date }}",
    "payroll.period": "{{ payroll.period }}",
    "payroll.payable_days": "{{ payroll.payable_days }}",
    "payroll.total_days": "{{ payroll.total_days }}",
    "payroll.payslip_number": "{{ payroll.payslip_number }}",
    "company.registration_no": "{{ company.registration_no }}",
}


_UNSAFE_LABEL_CHARS = re.compile(r"[<>{}%=\"'`\\]")


def _text(value, limit: int = 80) -> str:
    """User / PDF text as literal template text. A payslip label never needs
    markup, template or attribute characters, so they are removed outright —
    the text can never become HTML, an attribute or template code."""
    return _html.escape(_UNSAFE_LABEL_CHARS.sub("", str(value or ""))[:limit].strip())


_BUILT_CSS = """body { font-family: Arial, Helvetica, sans-serif; color: #1e293b; background-color: #ffffff; font-size: 10pt; margin: 0; }
.payslip { max-width: 820px; margin: 0 auto; padding: 24px; }
table { border-collapse: collapse; }
p { margin: 0; }
h1 { font-size: 16pt; color: var(--ps-primary); margin: 0 0 2px 0; }
.ps-header p { font-size: 8.5pt; color: #64748b; }
.ps-logo { max-height: 60px; }
.ps-title { background-color: var(--ps-primary); color: #ffffff; font-weight: bold; font-size: 10pt; padding: 3px 10px; }
.ps-rule { border-bottom: 2px solid var(--ps-primary); margin: 10px 0 14px 0; }
.ps-details { border: 1px solid #e2e8f0; margin-bottom: 14px; }
.ps-details td { padding: 5px 8px; font-size: 9pt; border-bottom: 1px solid #f1f5f9; }
.ps-details .ps-k { color: #64748b; width: 18%; }
.ps-details .ps-v { font-weight: bold; width: 32%; }
.ps-split { margin-bottom: 14px; }
.ps-table { border: 1px solid #cbd5e1; margin-bottom: 10px; }
.ps-table th { background-color: var(--ps-primary); color: #ffffff; font-size: 8.5pt; padding: 6px 8px; }
.ps-table td { padding: 5px 8px; font-size: 9pt; border-bottom: 1px solid #f1f5f9; }
.ps-foot td { background-color: #f1f5f9; font-weight: bold; border-top: 1px solid #cbd5e1; }
.ps-net { background-color: var(--ps-primary); color: #ffffff; margin-bottom: 14px; }
.ps-net td { padding: 10px 14px; }
.ps-net-title { font-weight: bold; }
.ps-net-words { font-size: 8.5pt; font-style: italic; }
.ps-net-amount { font-size: 16pt; font-weight: bold; color: var(--ps-accent); }
.ps-footer { border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 8pt; text-align: center; padding-top: 6px; }"""


def _lines_table(title: str, loop: str, var: str, total_label: str, total_expr: str) -> str:
    return (
        '<table class="ps-table" width="100%">'
        f'<tr><th align="left">{_text(title)}</th><th align="right">{{{{ currency.code }}}}</th></tr>'
        f'{{% for {var} in {loop} %}}<tr><td>{{{{ {var}.label }}}}</td>'
        f'<td align="right">{{{{ {var}.amount_formatted }}}}</td></tr>{{% endfor %}}'
        f'<tr class="ps-foot"><td>{_text(total_label)}</td><td align="right">{{{{ {total_expr} }}}}</td></tr>'
        "</table>"
    )


def build_from_analysis(choice: dict) -> dict:
    """{'htmlContent', 'cssContent', 'configurationJson'} from the user's
    confirmed analysis. Labels are literal text; values are always
    placeholders; amounts always come from the earnings / deduction loops."""
    sections = choice.get("sections") or {}
    logo = choice.get("logoDataUri") if choice.get("includeLogo", True) else None
    if logo and (not isinstance(logo, str) or not logo.startswith("data:image/png;base64,")
                 or len(logo) > MAX_LOGO_DATA_URI):
        logo = None
    logo_html = f'<img src="{logo}" alt="" class="ps-logo" height="56"><br>' if logo else ""

    detail_cells = []
    for field in choice.get("fields") or []:
        if not field.get("include", True):
            continue
        key = field.get("placeholder")
        label = _text(field.get("label") or key)
        if key == "employee.identifiers":
            detail_cells.append("{% for i in employee.identifiers %}"
                                '<td class="ps-k">{{ i.label }}</td><td class="ps-v">{{ i.value }}</td>'
                                "{% endfor %}")
        elif key in _PLACEHOLDER_EXPR:
            detail_cells.append(f'<td class="ps-k">{label}</td><td class="ps-v">{_PLACEHOLDER_EXPR[key]}</td>')
    if not any("employee.name" in c for c in detail_cells):
        detail_cells.insert(0, '<td class="ps-k">Employee Name</td><td class="ps-v">{{ employee.name }}</td>')
    detail_rows = "".join(
        "<tr>" + "".join(detail_cells[i:i + 2]) + "</tr>" for i in range(0, len(detail_cells), 2)
    )

    earnings = _lines_table(sections.get("earningsTitle") or "Earnings", "earnings", "earning",
                            sections.get("grossLabel") or "Gross Earnings", "totals.gross_pay_formatted")
    deductions = _lines_table(sections.get("deductionsTitle") or "Deductions", "deductions", "deduction",
                              sections.get("totalDeductionsLabel") or "Total Deductions",
                              "totals.total_deductions_formatted")
    if choice.get("layout") == "stacked":
        lines_html = earnings + deductions
    else:
        lines_html = ('<table class="ps-split" width="100%"><tr>'
                      f'<td width="49%" valign="top">{earnings}</td><td width="2%"></td>'
                      f'<td width="49%" valign="top">{deductions}</td></tr></table>')

    words = ('{% if config.showNetInWords %}<br><span class="ps-net-words">{{ totals.net_pay_in_words }}</span>'
             "{% endif %}")
    html_out = (
        '<div class="payslip">'
        '<table class="ps-header" width="100%"><tr>'
        f'<td width="62%" valign="top">{logo_html}<h1>{{{{ company.name }}}}</h1><p>{{{{ company.address }}}}</p></td>'
        f'<td width="38%" valign="top" align="right"><span class="ps-title">&nbsp;{_text(choice.get("title") or "PAYSLIP", 40)}&nbsp;</span>'
        "<p>{{ payroll.period }}</p></td>"
        "</tr></table>"
        '<div class="ps-rule"></div>'
        f'<table class="ps-details" width="100%">{detail_rows}</table>'
        f"{lines_html}"
        '<table class="ps-net" width="100%"><tr>'
        f'<td><span class="ps-net-title">{_text(sections.get("netLabel") or "Net Pay")}</span>{words}</td>'
        '<td align="right" class="ps-net-amount">{{ totals.net_pay_formatted }}</td>'
        "</tr></table>"
        '<p class="ps-footer">{{ disclaimer }}</p>'
        "</div>"
    )
    config = {
        "primaryColor": choice.get("primaryColor") or "#1E3A8A",
        "accentColor": choice.get("accentColor") or "#FFFFFF",
        "showCompanyLogo": False,
        "showEmployeeBank": True,
        "showNetInWords": bool(sections.get("showNetInWords", True)),
        "disclaimerText": (choice.get("disclaimer") or
                           "This is a computer-generated payslip and does not require a signature.")[:500],
    }
    return {"htmlContent": html_out, "cssContent": _BUILT_CSS, "configurationJson": config}
