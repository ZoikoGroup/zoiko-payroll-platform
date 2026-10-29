"""
tests/test_email_templates_render_completely.py
-------------------------------------------------
Every send_*_email() in app.services.email_service renders with no literal
{{placeholder}} left in the HTML — a missing context value used to reach
inboxes as text (e.g. "{{heading}}" as the title of the Payroll Approved
email). Each sender is called with sample arguments and nothing is sent:
SMTP resolves to "not configured" (mock send).

The shared renderer now strips any leftover placeholder as a safety net, so
this test records what was left BEFORE that net — a sender that relies on
it still fails here.
"""

import inspect
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from app.services import email_service as es


def _sample(name, param):
    n = name.lower()
    ann = str(param.annotation)
    if n == "failures":
        return [("Row 2 — Asha Rao", "Email is required.")]
    if "changes" in n:
        return [("Field", "old value", "new value")]
    if n.endswith("_ids") or "list" in ann.lower() or n in ("rows", "items", "failed", "employees"):
        return []
    if "bytes" in n:
        return None
    if n.endswith("_at") or "datetime" in ann:
        return datetime(2026, 9, 30, 10, 0)
    if "date" in n:
        return date(2026, 9, 30)
    if "amount" in n or "Decimal" in ann:
        return Decimal("1234.50")
    if "count" in n or ann in ("<class 'int'>", "int") or n.endswith("_days") or n == "minutes":
        return 3
    if "bool" in ann or n.startswith(("is_", "has_")):
        return True
    if "dict" in ann.lower():
        return {}
    if "email" in n:
        return "person@example.com"
    return f"Sample {name}"


def _senders():
    return [
        (name, fn) for name, fn in sorted(inspect.getmembers(es, inspect.isfunction))
        if name.startswith("send_") and name.endswith("_email") and name != "send_approval_email"
        and fn.__module__ == es.__name__
    ]


@pytest.fixture(scope="module")
def rendered():
    """{sender name: (html, placeholders left before the safety net)}."""
    results, current = {}, {"name": None}
    real_compose, real_strip = es._compose_email_html, es._strip_unresolved

    def recording_strip(html):
        results.setdefault(current["name"], {})["leftovers"] = sorted(set(es._UNRESOLVED_RE.findall(html)))
        return real_strip(html)

    def recording_compose(template, context):
        html = real_compose(template, context)
        results.setdefault(current["name"], {})["html"] = html
        return html

    smtp_off = {"host": "", "from_email": "noreply@example.com", "port": 587}
    with patch.object(es, "_strip_unresolved", recording_strip), \
         patch.object(es, "_compose_email_html", recording_compose), \
         patch.object(es, "_get_smtp_settings", lambda db=None: smtp_off), \
         patch.object(es, "_resolve_payroll_send_identity", lambda organization_id=None, db=None: ("noreply@example.com", "Org")):
        for name, fn in _senders():
            current["name"] = name
            kwargs = {
                pname: _sample(pname, p)
                for pname, p in inspect.signature(fn).parameters.items()
                if p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD) and p.default is p.empty
            }
            fn(**kwargs)
    return results


def test_every_sender_renders(rendered):
    assert len(_senders()) >= 50
    missing = [name for name, _fn in _senders() if "html" not in rendered.get(name, {})]
    assert not missing, f"senders that never rendered a template: {missing}"


def test_no_email_leaves_a_placeholder_unfilled(rendered):
    unfilled = {name: r["leftovers"] for name, r in rendered.items() if r.get("leftovers")}
    assert not unfilled, f"placeholders the sender never fills: {unfilled}"
    assert not [name for name, r in rendered.items() if "{{" in r.get("html", "")]


def test_payroll_approved_has_no_heading_placeholder(rendered):
    html = rendered["send_payroll_run_approved_email"]["html"]
    assert "{{heading}}" not in html
    assert "<h1" not in html.split("<!-- Body -->")[-1], "the body opens with the greeting, no empty/raw heading"
    assert "Sample pay_period" in html


def test_employee_onboarded_email_says_welcome_to_zoiko_payroll(rendered):
    assert "Welcome to Zoiko Payroll" in rendered["send_employee_created_email"]["html"]


def test_unresolved_placeholder_never_reaches_the_html():
    html = es._compose_email_html("<p>{{greeting}} {{name}}</p>", {"name": "Lennox"})
    assert html.count("{{") == 0 and "Lennox" in html
