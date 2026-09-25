"""
tests/test_email_logo_header.py
-------------------------------
Every email carries the real Zoiko Payroll logo image in its header, from one
single-source partial (email_service.LOGO_HEADER_HTML), and the Super Admin
new-organization alert is branded "Zoiko Payroll Platform", not
"[Platform Alert]".

Pass/fail per template, not a percentage: every file in app/email_templates
(except the wrapper itself, which fragments are composed into) is sent through
the real send_approval_email → smtplib path (smtplib faked), and the actual
MIME message on the wire must:
  - contain exactly one header <img> referencing the logo, old wordmark gone;
  - by default, EMBED that logo as an inline CID part in multipart/related,
    so it renders without any publicly reachable server (FRONTEND_URL is a
    localhost address outside production);
  - carry explicit width/height attributes (Outlook ignores CSS width:auto).
Plus: the EMAIL_LOGO_URL hosted override, custom org logos, PDF attachments
coexisting with the inline logo, the optimized asset itself, and the Outlook
solid-colour fallbacks for the legacy gradient headers.
"""

import email
import os
import re

import pytest

from app.services import email_service

TEMPLATE_DIR = email_service.TEMPLATE_DIR
TEMPLATES = sorted(
    f for f in os.listdir(TEMPLATE_DIR)
    if f.endswith(".html") and f != email_service._BASE_WRAPPER_NAME
)
_IMG_RE = re.compile(r"<img\b[^>]*>", re.IGNORECASE)
CID_SRC = f"cid:{email_service.LOGO_CID}"


class _WireSMTP:
    """smtplib.SMTP stand-in that keeps every message sent."""

    messages = []

    def __init__(self, host, port, timeout=None):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self, context=None):
        pass

    def login(self, username, password):
        pass

    def sendmail(self, from_addr, to_addr, message):
        _WireSMTP.messages.append(email.message_from_string(message))


@pytest.fixture()
def wire(monkeypatch):
    monkeypatch.setattr(email_service, "_get_smtp_settings", lambda db=None: {
        "host": "smtp.test.invalid", "port": 587, "username": "", "password": "",
        "from_email": "noreply@test.invalid", "use_tls": "true",
    })
    monkeypatch.setattr(email_service.smtplib, "SMTP", _WireSMTP)
    monkeypatch.setenv("FRONTEND_BASE_URL", "https://app.zoikopayroll.test")
    from app.config import settings

    monkeypatch.setattr(settings, "EMAIL_LOGO_URL", "")  # default: embed inline
    _WireSMTP.messages = []
    return _WireSMTP.messages


def _html_part(msg):
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            return part.get_payload(decode=True).decode("utf-8")
    raise AssertionError("no text/html part")


def _inline_logo_parts(msg):
    return [p for p in msg.walk() if p.get("Content-ID") == f"<{email_service.LOGO_CID}>"]


def _header_logo(html):
    tags = [t for t in _IMG_RE.findall(html) if 'alt="Zoiko Payroll"' in t]
    assert len(tags) == 1, f"expected exactly one header logo, found {len(tags)}"
    return tags[0]


def test_every_template_is_accounted_for():
    # 1 wrapper + 13 standalone documents + 39 body fragments at time of writing.
    assert len(TEMPLATES) >= 52


@pytest.mark.parametrize("template_name", TEMPLATES)
def test_template_header_embeds_real_logo_image(template_name, wire):
    assert email_service.send_approval_email("r@x.test", template_name, {"subject": "S"}) is True
    (msg,) = wire
    html = _html_part(msg)

    tag = _header_logo(html)
    assert f'src="{CID_SRC}"' in tag
    assert f'width="{email_service.LOGO_WIDTH_PX}"' in tag and f'height="{email_service.LOGO_HEIGHT_PX}"' in tag
    assert 'href="https://app.zoikopayroll.test"' in html  # logo links home

    # The referenced image is actually in the message, as an inline related part.
    (logo_part,) = _inline_logo_parts(msg)
    assert logo_part.get_content_type() == "image/png"
    assert logo_part.get_payload(decode=True) == email_service._email_logo_bytes()
    assert msg.get_content_type() == "multipart/related"

    # The old text wordmarks must not be stacked alongside the image.
    assert '<span style="color:#ffffff;">Zoiko</span>' not in html
    assert "letter-spacing:0.2px; color:#ffffff;\">Zoiko Payroll</p>" not in html  # old legacy header line
    assert "{{logo_header_block}}" not in html and "{{logo_url}}" not in html
    assert "{{logo_dimension_attrs}}" not in html


def test_hosted_logo_url_override_sends_remote_image_without_attachment(wire, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "EMAIL_LOGO_URL", "https://cdn.zoikopayroll.test/email-logo.png")
    email_service.send_approval_email("r@x.test", "password_changed.html", {"subject": "S"})
    (msg,) = wire
    tag = _header_logo(_html_part(msg))
    assert 'src="https://cdn.zoikopayroll.test/email-logo.png"' in tag
    assert f'width="{email_service.LOGO_WIDTH_PX}"' in tag
    assert _inline_logo_parts(msg) == []
    assert msg.get_content_type() == "multipart/alternative"


def test_org_custom_logo_is_used_and_header_link_still_set(wire, monkeypatch):
    monkeypatch.setattr(
        email_service, "_get_org_branding",
        lambda organization_id=None, db=None: dict(email_service._BRANDING_DEFAULTS, logo_url="https://cdn.acme.test/logo.png"),
    )
    email_service.send_approval_email("r@x.test", "password_changed.html", {"subject": "S"}, organization_id=1)
    (msg,) = wire
    html = _html_part(msg)
    tag = _header_logo(html)
    assert 'src="https://cdn.acme.test/logo.png"' in tag
    assert 'width=' not in tag  # unknown aspect ratio: height pinned only
    assert _inline_logo_parts(msg) == []
    # frontend_url was previously only set on the fallback branch — an org
    # with its own logo got an empty header link.
    assert 'href="https://app.zoikopayroll.test"' in html


def test_pdf_attachment_and_inline_logo_nest_correctly(wire):
    email_service.send_payslip_ready_email(
        "e@x.test", "Asha", "Sep 2026", pdf_bytes=b"%PDF-1.4 test", pdf_filename="PS-1.pdf",
    )
    (msg,) = wire
    assert msg.get_content_type() == "multipart/mixed"
    related, pdf = msg.get_payload()
    assert related.get_content_type() == "multipart/related"
    assert related.get_payload()[0].get_content_type() == "multipart/alternative"
    assert len(_inline_logo_parts(related)) == 1
    assert pdf.get_content_type() == "application/pdf"
    assert pdf.get_filename() == "PS-1.pdf" and pdf.get_content_disposition() == "attachment"


def test_missing_asset_falls_back_to_hosted_url_not_a_dangling_cid(wire, monkeypatch):
    monkeypatch.setattr(email_service, "_LOGO_BYTES", b"")
    email_service.send_approval_email("r@x.test", "password_changed.html", {"subject": "S"})
    (msg,) = wire
    tag = _header_logo(_html_part(msg))
    assert 'src="https://app.zoikopayroll.test/zoikopayroll-logo-light.png"' in tag
    assert _inline_logo_parts(msg) == []


def test_email_logo_asset_is_optimized():
    from PIL import Image

    size = os.path.getsize(email_service.EMAIL_LOGO_PATH)
    assert size < 20_000, size  # the web original is ~115KB at 3353px wide
    with Image.open(email_service.EMAIL_LOGO_PATH) as im:
        assert im.height == 2 * email_service.LOGO_HEIGHT_PX  # 2x for high-DPI screens
        assert round(im.width * email_service.LOGO_HEIGHT_PX / im.height) in (
            email_service.LOGO_WIDTH_PX, email_service.LOGO_WIDTH_PX + 1,
        )


def test_logo_alt_text_is_visible_when_images_are_blocked():
    tag = email_service.LOGO_HEADER_HTML
    assert 'alt="Zoiko Payroll"' in tag
    assert "color:#ffffff" in tag and "font-weight:bold" in tag  # alt text readable on the dark header
    assert "display:none" not in tag and 'height="1"' not in tag  # never a tracking pixel


@pytest.mark.parametrize("template_name", [
    "payslip_ready.html", "welcome.html", "assist_handoff_support_notification.html", "registration_received.html",
])
def test_legacy_gradient_headers_have_outlook_solid_fallback(template_name):
    raw = email_service._load_template(template_name)
    header = re.search(r"<td[^>]*linear-gradient[^>]*>", raw).group(0)
    solid = re.search(r'bgcolor="(#[0-9A-Fa-f]{6})"', header)
    assert solid, "Outlook desktop ignores gradients: header needs a bgcolor attribute"
    assert f"background-color:{solid.group(1)}" in header
    assert "background: linear-gradient" not in header  # gradient only as background-image, over the fallback
    chip = re.search(r'<td[^>]*>\{\{logo_header_block\}\}', raw).group(0)
    assert 'bgcolor="#0b1f3a"' in chip


def test_every_logo_header_cell_has_a_solid_bgcolor():
    for name in TEMPLATES + [email_service._BASE_WRAPPER_NAME]:
        raw = email_service._load_template(name)
        if "{{logo_header_block}}" not in raw:
            continue  # fragment: header comes from the wrapper
        before = raw[:raw.index("{{logo_header_block}}")]
        cells = re.findall(r"<td\b[^>]*>", before)
        assert any("bgcolor=" in cell for cell in cells), name


def test_super_admin_alert_is_branded_zoiko_payroll_platform(monkeypatch):
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(
        email_service, "send_approval_email",
        lambda email, template_name, context, **kw: calls.append((template_name, context, kw)) or True,
    )
    org = SimpleNamespace(id=7, organization_name="Acme GmbH", organization_code="ACME")
    assert email_service.send_super_admin_org_created_notification_email(org, recipient_email="sa@x.test") is True

    ((template_name, context, kw),) = calls
    assert template_name == "super_admin_org_created.html"
    assert "[Platform Alert]" not in context["subject"]
    assert context["subject"] == "Zoiko Payroll Platform: New Organization Created — Acme GmbH"
    assert kw["from_display_name_override"] == "Zoiko Payroll Platform"

    raw = email_service._load_template("super_admin_org_created.html")
    assert "Platform Alert" not in raw
    assert ">Super Admin Notification</td>" in raw  # audience badge deliberately unchanged
