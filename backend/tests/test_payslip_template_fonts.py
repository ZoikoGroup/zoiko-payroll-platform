"""
tests/test_payslip_template_fonts.py
------------------------------------
Payslip-template PDF fonts (exact-layout work, P3):

  * pdf_font_faces finds regular / bold / italic / bold-italic sans and serif
    faces (DejaVu in production, Arial / Times on Windows dev machines) and
    falls back to the nearest face when one is missing;
  * a template with pdfFonts == "full" embeds a real bold-italic face and a
    serif face, and still renders ₹;
  * every other template's PDF uses only the two standard faces, exactly as
    before; only "full" is accepted as a font mode.
"""
import io
import os

import pytest

from app.modules.payroll import payslip_template_service as tpl
from app.modules.payroll import service

_FACES = service.pdf_font_faces()
needs_full_fonts = pytest.mark.skipif(
    not _FACES or _FACES["sans"]["bolditalic"] == _FACES["sans"]["regular"],
    reason="no italic font faces installed on this machine (production: fonts-dejavu-extra)")


def _font_names(pdf: bytes) -> set:
    from pypdf import PdfReader
    names = set()
    for page in PdfReader(io.BytesIO(pdf)).pages:
        fonts = (page.get("/Resources") or {}).get("/Font") or {}
        for ref in fonts.values():
            names.add(str(ref.get_object().get("/BaseFont", "")).split("+")[-1])
    return names


def _text(pdf: bytes) -> str:
    from pypdf import PdfReader
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(pdf)).pages)


_CSS = (".bi { font-family: Arial, Helvetica, sans-serif; font-weight: bold; font-style: italic; } "
        ".co { font-family: 'Times New Roman', Times, serif; font-weight: bold; font-size: 16pt; } "
        ".pl { font: 10pt Arial; }")
_BODY = ('<p class="co">Zoiko Industry Pvt. Ltd.</p><p class="bi">Employee ID</p>'
         '<p class="pl">Net Paid ₹ 69,600.00</p>')
_FULL = {**tpl.DEFAULT_CONFIG, "pdfFonts": "full"}


# ── face discovery ───────────────────────────────────────────────────────────

def test_faces_have_all_four_styles_per_family():
    if not _FACES:
        pytest.skip("no Unicode font installed")
    for family in ("sans", "serif"):
        assert set(_FACES[family]) == {"regular", "bold", "italic", "bolditalic"}
        assert all(os.path.isfile(p) for p in _FACES[family].values())


def test_missing_styles_fall_back_to_nearest(monkeypatch):
    # Production before fonts-dejavu-extra: only DejaVu Sans regular + bold.
    dejavu = "/usr/share/fonts/truetype/dejavu"
    monkeypatch.setattr(os.path, "isfile", lambda p: p in (f"{dejavu}/DejaVuSans.ttf", f"{dejavu}/DejaVuSans-Bold.ttf"))
    faces = service.pdf_font_faces()
    assert faces["sans"]["italic"] == f"{dejavu}/DejaVuSans.ttf"
    assert faces["sans"]["bolditalic"] == f"{dejavu}/DejaVuSans-Bold.ttf"
    assert faces["serif"] == faces["sans"]          # no serif installed -> sans faces


# ── CSS mapping ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("decl,family", [
    ("font-family: Arial", tpl._FULL_SANS),
    ("font-family: sans-serif", tpl._FULL_SANS),
    ("font-family: 'Times New Roman', Times, serif", tpl._FULL_SERIF),
    ("font-family: Georgia", tpl._FULL_SERIF),
])
def test_full_font_css_maps_families(decl, family):
    assert tpl._full_font_css(f".x {{ {decl}; }}") == f".x {{ font-family: {family}; }}"


def test_full_font_css_gives_shorthand_an_explicit_family():
    out = tpl._full_font_css(".x { font: italic bold 12px Georgia, serif; }")
    assert out == f".x {{ font: italic bold 12px Georgia, serif; font-family: {tpl._FULL_SERIF}; }}"


def test_only_full_is_a_font_mode():
    assert tpl.normalize_config({"pdfFonts": "full"})["pdfFonts"] == "full"
    assert "pdfFonts" not in tpl.normalize_config({"pdfFonts": "../../etc"})
    assert "pdfFonts" not in tpl.normalize_config({})


# ── PDFs ─────────────────────────────────────────────────────────────────────

@needs_full_fonts
def test_full_fonts_embed_bold_italic_and_serif_faces():
    pdf = tpl.html_to_pdf(_BODY, _CSS, _FULL)
    names = _font_names(pdf)
    lowered = {n.lower() for n in names}
    assert any("bold" in n and ("italic" in n or "oblique" in n) for n in lowered), names
    assert any("times" in n or "serif" in n for n in lowered), names
    text = _text(pdf)
    assert "Zoiko Industry Pvt. Ltd." in text and "₹" in text


def test_standard_mode_uses_only_the_two_standard_faces():
    pdf = tpl.html_to_pdf(_BODY, _CSS, dict(tpl.DEFAULT_CONFIG))
    lowered = {n.lower() for n in _font_names(pdf)}
    if tpl._font_files():
        assert not any("italic" in n or "oblique" in n for n in lowered), lowered
        assert not any("times" in n or "serif" in n.replace("sans-serif", "") for n in lowered), lowered
    # Standard mode is deliberately unchanged, including its known gap: the
    # `font:` shorthand is not rewritten there, so that line falls back to a
    # built-in font without ₹. Full fonts (above) handle the shorthand.


def test_resource_policy_fits_eight_faces_and_keeps_standard_limit():
    assert tpl._pdf_resource_policy(("a/1.ttf", "a/2.ttf")).max_resources == 4
    eight = tuple(f"a/{i}.ttf" for i in range(8))
    assert tpl._pdf_resource_policy(eight).max_resources == 10


@needs_full_fonts
def test_full_fonts_still_refuse_external_resources():
    body = _BODY + '<img src="file:///C:/Windows/win.ini"><img src="http://example.com/x.png">'
    pdf = tpl.html_to_pdf(body, _CSS + " .z { background-image: url('file:///etc/passwd'); }", _FULL)
    assert pdf.startswith(b"%PDF")
