"""Generated sample files for the payslip-template import tests (no real data)."""
import io
import zipfile

_CT = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rIdLink" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" Target="https://acme.example.com" TargetMode="External"/>
</Relationships>"""
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" ' \
     'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'


def _p(*runs):
    return "<w:p>" + "".join(runs) + "</w:p>"


def _r(text, bold=False):
    rpr = "<w:rPr><w:b/></w:rPr>" if bold else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def _cell(text):
    return f"<w:tc>{_p(_r(text))}</w:tc>"


def make_docx(body_xml: str = None) -> bytes:
    if body_xml is None:
        body_xml = (
            _p(_r("ACME PAYSLIP", bold=True))
            # A placeholder Word split over two runs (bold half) and smart quotes elsewhere.
            + _p(_r("Employee: {{ employee."), _r("name }}", bold=True))
            + _p(_r("Net pay: {{ totals.net_pay_formatted }}"))
            + _p(_r("Visit "), '<w:hyperlink r:id="rIdLink">' + _r("our website") + "</w:hyperlink>")
            + "<w:tbl>"
            + "<w:tr>" + _cell("Earning") + _cell("Amount") + "</w:tr>"
            + "<w:tr>" + _cell("{{ earning.label }}") + _cell("{{ earning.amount_formatted }}") + "</w:tr>"
            + "</w:tbl>"
            + "<w:tbl>"
            + "<w:tr>" + _cell("{{ deduction.label }}") + _cell("{{ deduction.amount_formatted }}") + "</w:tr>"
            + "</w:tbl>"
        )
    document = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document {_W}><w:body>{body_xml}</w:body></w:document>'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", _CT)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", document)
    return buf.getvalue()


def make_payslip_pdf(with_text: bool = True) -> bytes:
    """A one-page payslip-like PDF: teal header band, logo, labelled fields,
    side-by-side earnings / deductions, totals, net pay and a footer."""
    from PIL import Image
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    w, h = A4
    c.setFillColorRGB(0.06, 0.46, 0.43)                    # #0F766E-ish band
    c.rect(0, h - 90, w, 90, fill=1, stroke=0)
    logo = Image.new("RGB", (120, 60), (250, 200, 30))
    c.drawImage(ImageReader(logo), 40, h - 80, width=80, height=40)
    if not with_text:
        c.save()
        return buf.getvalue()
    c.setFillColorRGB(1, 1, 1)
    c.setFont("Helvetica-Bold", 20)
    c.drawString(140, h - 50, "Acme Widgets Pvt Ltd")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(w - 160, h - 50, "SALARY SLIP")
    c.setFillColorRGB(0, 0, 0)
    c.setFont("Helvetica", 10)
    y = h - 130
    for left, right in [(("Employee Name:", "Asha Rao"), ("Emp Code:", "E-1001")),
                        (("Department:", "Engineering"), ("Designation:", "Engineer")),
                        (("PAN:", "ABCDE1234F"), ("Pay Period:", "June 2026")),
                        (("Bank Name:", "HDFC Bank"), ("Account No:", "XXXX1234"))]:
        c.drawString(40, y, left[0]); c.drawString(140, y, left[1])
        c.drawString(320, y, right[0]); c.drawString(420, y, right[1])
        y -= 18
    y -= 14
    c.setFont("Helvetica-Bold", 11)
    c.drawString(40, y, "Earnings"); c.drawString(320, y, "Deductions")
    c.setFont("Helvetica", 10)
    y -= 18
    for (el, ev), (dl, dv) in [(("Basic", "50,000.00"), ("Income Tax", "5,000.00")),
                               (("HRA", "20,000.00"), ("Provident Fund", "1,800.00"))]:
        c.drawString(40, y, el); c.drawRightString(270, y, ev)
        c.drawString(320, y, dl); c.drawRightString(550, y, dv)
        y -= 16
    c.setFont("Helvetica-Bold", 10)
    c.drawString(40, y, "Gross Earnings"); c.drawRightString(270, y, "70,000.00")
    c.drawString(320, y, "Total Deductions"); c.drawRightString(550, y, "6,800.00")
    y -= 30
    c.drawString(40, y, "Net Salary"); c.drawRightString(550, y, "63,200.00")
    y -= 16
    c.setFont("Helvetica", 9)
    c.drawString(40, y, "Amount in words: Sixty Three Thousand Two Hundred Only")
    c.drawString(40, 60, "This is a system generated salary slip and does not need any signature.")
    c.save()
    return buf.getvalue()


# ── Grid payslip: a reportlab copy of Payslip_Blank_Template.pdf ─────────────
# Same structure as the owner's blank Zoiko Industry payslip (A4 portrait):
# centred logo, serif bold company name, one ruled 5-column grid (34/13/13/
# 20/20 %), 17 rows with a light-blue title bar, merged cells (title and
# full-width rows colspan 5, info values colspan 2, Designation rowspan 2),
# bold-italic Arial-style labels. Used until / alongside the real fixture
# (tests/fixtures/payslip_import/Payslip_Blank_Template.pdf).

GRID_TITLE_FILL = (0xC6 / 255, 0xD9 / 255, 0xF1 / 255)
GRID_COL_PCT = (34, 13, 13, 20, 20)
GRID_ROW_PT = 18.1
GRID_WORDS_ROW_PT = 35.6
# (row, col, rowspan, colspan, text)
GRID_CELLS = [
    (0, 0, 1, 5, "Pay Slip for the month of ____________"),
    (1, 0, 1, 1, "Employee ID"), (1, 1, 1, 2, ""), (1, 3, 1, 1, "DOJ"), (1, 4, 1, 1, ""),
    (2, 0, 1, 1, "Name"), (2, 1, 1, 2, ""), (2, 3, 2, 1, "Designation"), (2, 4, 2, 1, ""),
    (3, 0, 1, 1, "Pan No."), (3, 1, 1, 2, ""),
    (4, 0, 1, 1, "Paid Days"), (4, 1, 1, 2, ""), (4, 3, 1, 1, "Department"), (4, 4, 1, 1, ""),
    (5, 0, 1, 1, "Bank Account No."), (5, 1, 1, 2, ""), (5, 3, 1, 1, "Month Days"), (5, 4, 1, 1, ""),
    (6, 0, 1, 1, "IFSC"), (6, 1, 1, 2, ""), (6, 3, 1, 1, "Mode of Payment"), (6, 4, 1, 1, ""),
    (7, 0, 1, 1, "Particular's"), (7, 1, 1, 1, "Entitled"), (7, 2, 1, 1, "Earnings"),
    (7, 3, 1, 1, "Particular's"), (7, 4, 1, 1, "Deductions"),
]
for _r_, (_e, _d) in enumerate([("Basic Salary", "TDS"), ("HRA", "EPF Deduction"),
                                ("Conv. Allowance", "Advance Deduction"), ("Special Allowance", "Any other----"),
                                ("Bonus", "Total Deductions"), ("Employer Share of EPF", ""),
                                ("Total CTC", "Net Paid")], start=8):
    GRID_CELLS += [(_r_, 0, 1, 1, _e), (_r_, 1, 1, 1, ""), (_r_, 2, 1, 1, ""), (_r_, 3, 1, 1, _d), (_r_, 4, 1, 1, "")]
GRID_CELLS += [(15, 0, 1, 5, "Paid amount in words :"),
               (16, 0, 1, 5, "Note:- This is a computer generated statement, hence does not require signature")]
GRID_LABELS = [c[4] for c in GRID_CELLS if c[4]]


def make_grid_payslip_pdf() -> bytes:
    from PIL import Image, ImageDraw
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas

    width, height = A4
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=A4)
    # Logo: a generated two-colour mark (no real artwork).
    logo = Image.new("RGB", (240, 72), "white")
    draw = ImageDraw.Draw(logo)
    draw.rectangle([0, 0, 70, 50], fill=(214, 110, 40))
    draw.rectangle([80, 0, 240, 50], fill=(18, 72, 120))
    draw.rectangle([60, 56, 200, 70], fill=(214, 110, 40))
    lw, lh = 240, 72
    c.drawImage(ImageReader(logo), (width - lw) / 2, height - 40 - lh, lw, lh)
    c.setFont("Times-Bold", 15)
    c.drawCentredString(width / 2, height - 135, "Zoiko Industry Pvt. Ltd.")

    x0, total = 40.0, 518.0
    xs = [x0]
    for pct in GRID_COL_PCT:
        xs.append(xs[-1] + total * pct / 100)
    heights = [GRID_ROW_PT] * 15 + [GRID_WORDS_ROW_PT, GRID_ROW_PT]
    tops = [height - 160]
    for h in heights:
        tops.append(tops[-1] - h)
    c.setLineWidth(0.75)
    for r, col, rs, cs, text in GRID_CELLS:
        left, right = xs[col], xs[col + cs]
        top, bottom = tops[r], tops[r + rs]
        if r == 0:
            c.setFillColorRGB(*GRID_TITLE_FILL)
            c.rect(left, bottom, right - left, top - bottom, stroke=1, fill=1)
        else:
            c.rect(left, bottom, right - left, top - bottom, stroke=1, fill=0)
        if not text:
            continue
        c.setFillColorRGB(0, 0, 0)
        if r == 16:
            c.setFont("Helvetica-Bold", 8.5)
            c.drawCentredString((left + right) / 2, top - 12.5, text)
        elif r == 0:
            c.setFont("Helvetica-BoldOblique", 9)
            c.drawCentredString((left + right) / 2, top - 12.5, text)
        else:
            c.setFont("Helvetica-BoldOblique", 9)
            text_top = top - 12.5 if rs == 1 and r != 15 else (top + bottom) / 2 - 3 if rs > 1 else top - 12.5
            c.drawString(left + 4, text_top, text)
    c.showPage()
    c.save()
    return buf.getvalue()
