"""
tests/test_email_mobile_layout.py
---------------------------------
Mobile-safe structure for every email, rendered through the real
send_approval_email path (smtplib faked, so the HTML checked is the HTML sent).

Two layers, both asserted:
  1. Fluid base — works even where a client strips <style> (e.g. Gmail app
     with a non-Google account): card capped at max-width:600px / width:100%,
     never a bare fixed width; long unbroken tokens (emails, IBANs, transfer
     tickets) allowed to wrap; label columns never break mid-word; nothing
     readable under 12px.
  2. Media-query enhancement — the single-source MOBILE_STYLES_HTML block in
     every <head>, plus the class hooks it targets (zk-px gutters, stacked
     header badge, full-width CTA).

The pixel-level check (no horizontal overflow at 375px and 320px, per
template) was done in a real browser engine while building this; these tests
guard the structure that produced it.
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
LONG_EMAIL = "maximilian.schneider-hoffmann@northwind-precision-engineering.example"


class _WireSMTP:
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
def sent_html(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(email_service, "_get_smtp_settings", lambda db=None: {
        "host": "smtp.test.invalid", "port": 587, "username": "", "password": "",
        "from_email": "noreply@test.invalid", "use_tls": "true",
    })
    monkeypatch.setattr(email_service.smtplib, "SMTP", _WireSMTP)
    monkeypatch.setattr(settings, "EMAIL_LOGO_URL", "")
    _WireSMTP.messages = []

    def send(template_name, **context):
        email_service.send_approval_email("r@x.test", template_name, {"subject": "S", **context})
        msg = _WireSMTP.messages[-1]
        for part in msg.walk():
            if part.get_content_type() == "text/html":
                return part.get_payload(decode=True).decode("utf-8")
        raise AssertionError("no text/html part")

    return send


def _visible_font_sizes(html):
    """Font sizes of everything except the hidden preheader (1px, display:none)
    and the logo cell's font-size:0 whitespace collapse."""
    body = re.sub(r'<div style="display:none;[^"]*">.*?</div>', "", html, flags=re.S)
    return [int(v) for v in re.findall(r"font-size:\s*(\d+)px", body) if int(v) != 0]


@pytest.mark.parametrize("template_name", TEMPLATES)
def test_template_is_mobile_safe(template_name, sent_html):
    html = sent_html(template_name, requester_email=LONG_EMAIL, admin_email=LONG_EMAIL)

    assert '<meta name="viewport" content="width=device-width, initial-scale=1">' in html
    assert email_service.MOBILE_STYLES_HTML in html
    assert "{{mobile_styles}}" not in html

    # Fluid card: capped width, never a bare fixed 600px table.
    card = re.search(r'<table width="600"[^>]*>', html).group(0)
    assert "max-width:600px" in card and "width:100%" in card
    assert "overflow-wrap:anywhere" in card  # long tokens wrap inside the card
    assert 'cellpadding="20"' not in html

    # Phone gutters: the page gutter and every wide-padded card cell are hooked.
    assert 'class="zk-outer"' in html
    assert "zk-px" in html
    assert 'class="zk-h1"' in html

    # Readable minimum size everywhere visible.
    sizes = _visible_font_sizes(html)
    assert sizes and min(sizes) >= 12, (template_name, sorted(set(sizes)))


@pytest.mark.parametrize("template_name", [
    t for t in TEMPLATES
    if "border-radius:9999px" in open(os.path.join(TEMPLATE_DIR, t), encoding="utf-8").read()
] + [email_service._BASE_WRAPPER_NAME])
def test_header_badge_stacks_under_logo_on_phones(template_name):
    raw = email_service._load_template(template_name)
    assert 'class="zk-brand"' in raw and 'class="zk-badge"' in raw
    assert ".zk-badge{display:inline-block" in email_service.MOBILE_STYLES_HTML


@pytest.mark.parametrize("template_name", [
    t for t in TEMPLATES + [email_service._BASE_WRAPPER_NAME]
    if re.search(r'<a[^>]*href="\{\{(action_url|cta_url|login_url)\}\}"',
                 open(os.path.join(TEMPLATE_DIR, t), encoding="utf-8").read())
])
def test_primary_cta_goes_full_width_on_phones(template_name):
    raw = email_service._load_template(template_name)
    tags = re.findall(r'<a[^>]*href="\{\{(?:action_url|cta_url|login_url)\}\}"[^>]*>', raw)
    assert tags
    for tag in tags:
        assert "zk-btn" in tag and "display:inline-block" in tag.replace(" ", "")


def test_label_cells_never_break_mid_word():
    for name in TEMPLATES:
        raw = email_service._load_template(name)
        for label_td in re.findall(r'<td[^>]*>[^<]*</td>\s*<td align="right"', raw):
            if "zk-brand" in label_td:
                continue  # the header logo cell, not a label
            assert "word-break:normal" in label_td and 'width="38%"' in label_td, (name, label_td[:80])


def test_details_rows_wrap_values_and_labels():
    html = email_service._details_rows([("Contact", LONG_EMAIL), ("Transfer ticket", "et2026092500123456789abcdef")])
    assert "white-space:nowrap" not in html  # labels used to be nowrap, starving values on phones
    assert html.count("overflow-wrap:anywhere") == 2
    assert html.count('width="38%"') == 2


def test_change_cells_put_label_on_its_own_row():
    html = email_service._change_cells([
        ("Bank account number", "DE89 3704 0044 0532 0130 00", "DE12 5001 0517 5407 3249 31"),
        ("Employment status", "Active", "Inactive"),
    ])
    rows = re.findall(r"<tr>.*?</tr>", html, re.S)
    assert len(rows) == 4  # label row + old→new row, per change
    assert 'colspan="3"' in rows[0] and "Bank account number" in rows[0]
    assert "DE89" in rows[1] and "&rarr;" in rows[1] and "DE12" in rows[1]
    assert rows[1].count("overflow-wrap:anywhere") == 2
    assert "border-top" in rows[2] and "border-top" not in rows[0]  # divider between changes only


def test_mobile_stylesheet_targets_phone_widths_only():
    css = email_service.MOBILE_STYLES_HTML
    assert "@media only screen and (max-width:600px)" in css
    for rule in (".zk-outer{", ".zk-px{", ".zk-brand{", ".zk-badge{", ".zk-btn{", ".zk-h1{"):
        assert rule in css
    assert "-webkit-text-size-adjust:100%" in css  # stop iOS auto-inflating text and breaking layout
