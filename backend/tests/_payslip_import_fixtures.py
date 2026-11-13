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
