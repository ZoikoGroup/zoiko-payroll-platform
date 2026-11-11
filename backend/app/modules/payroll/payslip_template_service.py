"""
modules/payroll/payslip_template_service.py
-------------------------------------------
Organisation-owned payslip templates: how a payslip LOOKS, never what it says.

  * Starters — built-in layouts that live in code (STARTERS). An organisation
    copies one into its own template; nothing is shared between tenants.
  * Templates / versions — a Draft is edited in place; publishing makes it
    Active and archives the previous Active. Active/Archived are never edited.
  * Assignments — which Active version the org's payslips use, per country or
    for every country ('ALL'). No assignment = the standard statutory payslip.
  * Freezing — when a run is approved, each payslip keeps the version it was
    issued with (PayslipItem.template_version_id).

Amounts come only from the payslip (service.get_payslip_by_id) and its lines
from service.payslip_line_items — the same lines the PDF prints. A payslip
whose lines don't add up to its stored gross / total deductions (a country
with its own statutory breakdown), or that is FAILED / PARTIAL, is never
rendered through a template: the caller falls back to the statutory payslip.

Safety: templates are Jinja2 rendered in a sandbox with autoescape on and
`|safe` / includes / autoescape-off refused; markup that could run script or
load anything external is refused at save; and the rendered document carries
a Content-Security-Policy that blocks scripts and every external request. The
frontend shows it in an iframe with an empty sandbox (no scripts, no origin).
"""

from __future__ import annotations

import html as _html
import logging
import re
from datetime import datetime, date
from decimal import Decimal
from typing import Optional, List, Tuple

import jinja2
from jinja2 import nodes
from jinja2.sandbox import SandboxedEnvironment, SecurityError
from sqlalchemy.orm import Session
from fastapi import HTTPException, status

from app.modules.payroll.models import (
    PayrollRun,
    PayslipItem,
    PayslipStatus,
    PayslipTemplate,
    PayslipTemplateVersion,
    PayslipTemplateAssignment,
)

logger = logging.getLogger("zoiko_payroll.payslip_templates")

ALL_COUNTRIES = "ALL"
MAX_HTML_BYTES = 200_000
MAX_CSS_BYTES = 100_000
_RECONCILE_TOLERANCE = Decimal("0.01")


# ── Built-in starter layouts ─────────────────────────────────────────────────
# Fragments (no <html>/<head>/<body>): render_document() wraps them. Colours
# come from the --ps-primary / --ps-accent variables the wrapper sets from the
# template's configuration.

_CLASSIC_NAVY_HTML = """<div class="payslip">
  <header class="ps-header">
    <div class="ps-company">
      {% if config.showCompanyLogo and company.logo_data_uri %}<img src="{{ company.logo_data_uri }}" alt="" class="ps-logo">{% endif %}
      <div>
        <h1>{{ company.name }}</h1>
        <p>{{ company.address }}</p>
        {% if company.tax_id %}<p>Tax ID: {{ company.tax_id }}</p>{% endif %}
      </div>
    </div>
    <div class="ps-period">
      <div class="ps-badge">PAYSLIP</div>
      <div class="ps-period-label">{{ payroll.period }}</div>
      <div class="ps-muted">Pay date: {{ payroll.pay_date }}</div>
    </div>
  </header>

  <section class="ps-card ps-grid">
    <div><span>Employee Name</span><strong>{{ employee.name }}</strong></div>
    <div><span>Employee ID</span><strong>{{ employee.id }}</strong></div>
    <div><span>Department</span><strong>{{ employee.department or "-" }}</strong></div>
    <div><span>Designation</span><strong>{{ employee.designation or "-" }}</strong></div>
    <div><span>Date of Joining</span><strong>{{ employee.date_of_joining or "-" }}</strong></div>
    <div><span>Payable / Working Days</span><strong>{{ payroll.payable_days or "-" }} / {{ payroll.total_days or "-" }}</strong></div>
    {% for ident in employee.identifiers %}
    <div><span>{{ ident.label }}</span><strong>{{ ident.value or "-" }}</strong></div>
    {% endfor %}
    {% if config.showEmployeeBank %}
    <div><span>Bank</span><strong>{{ employee.bank_name or "-" }}</strong></div>
    <div><span>Account</span><strong>{{ employee.bank_account or "-" }}</strong></div>
    {% endif %}
  </section>

  <div class="ps-tables">
    <section class="ps-table">
      <div class="ps-table-head"><span>EARNINGS</span><span>{{ currency.code }}</span></div>
      {% for line in earnings %}<div class="ps-row"><span>{{ line.label }}</span><span>{{ line.amount_formatted }}</span></div>{% endfor %}
      <div class="ps-table-foot"><span>Gross Earnings</span><span>{{ totals.gross_pay_formatted }}</span></div>
    </section>
    <section class="ps-table">
      <div class="ps-table-head"><span>DEDUCTIONS</span><span>{{ currency.code }}</span></div>
      {% for line in deductions %}<div class="ps-row"><span>{{ line.label }}</span><span>{{ line.amount_formatted }}</span></div>{% endfor %}
      <div class="ps-table-foot"><span>Total Deductions</span><span>{{ totals.total_deductions_formatted }}</span></div>
    </section>
  </div>

  <section class="ps-net">
    <div>
      <div class="ps-net-title">NET PAY</div>
      {% if config.showNetInWords %}<div class="ps-net-words">{{ totals.net_pay_in_words }}</div>{% endif %}
    </div>
    <div class="ps-net-amount">{{ totals.net_pay_formatted }}</div>
  </section>

  <footer class="ps-footer">
    <p>{{ disclaimer }}</p>
    <div><span>Payslip {{ payroll.payslip_number or "" }}</span><span>Generated {{ generated_on }}</span></div>
  </footer>
</div>"""

_CLASSIC_NAVY_CSS = """* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Arial, Helvetica, sans-serif; color: #1e293b; background: #fff; font-size: 12px; line-height: 1.5; }
.payslip { max-width: 820px; margin: 0 auto; padding: 28px; }
.ps-header { display: flex; justify-content: space-between; align-items: flex-start; padding-bottom: 16px; border-bottom: 2px solid var(--ps-primary); margin-bottom: 18px; }
.ps-company { display: flex; gap: 14px; align-items: center; }
.ps-company h1 { font-size: 18px; color: var(--ps-primary); }
.ps-company p, .ps-muted { font-size: 11px; color: #64748b; }
.ps-logo { max-height: 52px; max-width: 140px; }
.ps-period { text-align: right; }
.ps-badge { display: inline-block; background: var(--ps-primary); color: #fff; font-weight: 700; padding: 3px 12px; border-radius: 4px; letter-spacing: .08em; }
.ps-period-label { font-weight: 700; margin-top: 6px; }
.ps-card { background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 12px 16px; margin-bottom: 18px; }
.ps-grid { display: grid; grid-template-columns: repeat(3, 1fr); gap: 8px 18px; }
.ps-grid span { display: block; font-size: 10px; color: #64748b; }
.ps-grid strong { font-size: 11px; }
.ps-tables { display: flex; gap: 18px; margin-bottom: 18px; }
.ps-table { flex: 1; border: 1px solid #cbd5e1; border-radius: 6px; overflow: hidden; }
.ps-table-head, .ps-table-foot, .ps-row { display: flex; justify-content: space-between; padding: 6px 12px; }
.ps-table-head { background: var(--ps-primary); color: #fff; font-weight: 700; font-size: 11px; }
.ps-table-foot { background: #f1f5f9; border-top: 1px solid #cbd5e1; font-weight: 700; }
.ps-row:nth-child(even) { background: #f8fafc; }
.ps-net { display: flex; justify-content: space-between; align-items: center; background: var(--ps-primary); color: #fff; border-radius: 6px; padding: 14px 18px; margin-bottom: 18px; }
.ps-net-title { font-weight: 700; letter-spacing: .05em; }
.ps-net-words { font-size: 11px; opacity: .85; font-style: italic; }
.ps-net-amount { font-size: 22px; font-weight: 800; color: var(--ps-accent); }
.ps-footer { border-top: 1px solid #e2e8f0; padding-top: 12px; color: #94a3b8; font-size: 10px; text-align: center; }
.ps-footer div { display: flex; justify-content: space-between; margin-top: 6px; }
@media print { .payslip { padding: 0; } }"""

_MODERN_EMERALD_HTML = """<div class="payslip">
  <div class="ps-bar"></div>
  <header class="ps-header">
    <div class="ps-company">
      {% if config.showCompanyLogo and company.logo_data_uri %}<img src="{{ company.logo_data_uri }}" alt="" class="ps-logo">{% endif %}
      <div>
        <h1>{{ company.name }}</h1>
        <p>{{ company.address }}{% if company.tax_id %} &middot; Tax ID: {{ company.tax_id }}{% endif %}</p>
      </div>
    </div>
    <div class="ps-period">
      <span class="ps-tag">PAYSLIP</span>
      <h2>{{ payroll.period }}</h2>
      <p>Payment date: {{ payroll.pay_date }}</p>
    </div>
  </header>

  <div class="ps-employee">
    <div><span>EMPLOYEE</span><strong>{{ employee.name }}</strong></div>
    <div><span>EMPLOYEE ID</span><strong>{{ employee.id }}</strong></div>
    <div><span>DEPARTMENT</span><strong>{{ employee.department or "-" }}</strong></div>
    <div><span>DESIGNATION</span><strong>{{ employee.designation or "-" }}</strong></div>
    {% for ident in employee.identifiers %}
    <div><span>{{ ident.label | upper }}</span><strong>{{ ident.value or "-" }}</strong></div>
    {% endfor %}
    {% if config.showEmployeeBank %}
    <div><span>BANK ACCOUNT</span><strong>{{ employee.bank_name }} {{ employee.bank_account }}</strong></div>
    {% endif %}
  </div>

  <div class="ps-cards">
    <div class="ps-card">
      <div class="ps-card-head ps-earn">EARNINGS</div>
      {% for line in earnings %}<div class="ps-line"><span>{{ line.label }}</span><strong>{{ line.amount_formatted }}</strong></div>{% endfor %}
      <div class="ps-card-foot"><span>Gross Pay</span><strong>{{ totals.gross_pay_formatted }}</strong></div>
    </div>
    <div class="ps-card">
      <div class="ps-card-head ps-ded">DEDUCTIONS</div>
      {% for line in deductions %}<div class="ps-line"><span>{{ line.label }}</span><strong>{{ line.amount_formatted }}</strong></div>{% endfor %}
      <div class="ps-card-foot"><span>Total Deductions</span><strong>{{ totals.total_deductions_formatted }}</strong></div>
    </div>
  </div>

  <div class="ps-net">
    <div>
      <div class="ps-net-title">NET PAYABLE</div>
      {% if config.showNetInWords %}<div class="ps-net-words">{{ totals.net_pay_in_words }}</div>{% endif %}
    </div>
    <div class="ps-net-amount">{{ totals.net_pay_formatted }}</div>
  </div>

  <footer class="ps-footer">{{ disclaimer }}</footer>
</div>"""

_MODERN_EMERALD_CSS = """* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: Arial, Helvetica, sans-serif; color: #0f172a; background: #fff; font-size: 12px; }
.payslip { max-width: 820px; margin: 0 auto; padding: 30px; position: relative; }
.ps-bar { position: absolute; top: 0; left: 0; right: 0; height: 6px; background: linear-gradient(90deg, var(--ps-primary), var(--ps-accent)); }
.ps-header { display: flex; justify-content: space-between; align-items: flex-start; margin: 8px 0 22px; }
.ps-company { display: flex; gap: 14px; align-items: center; }
.ps-company h1 { font-size: 20px; color: var(--ps-primary); }
.ps-company p, .ps-period p { font-size: 11px; color: #64748b; }
.ps-logo { max-height: 48px; max-width: 140px; }
.ps-period { text-align: right; }
.ps-period h2 { font-size: 15px; margin-top: 4px; }
.ps-tag { background: #ccfbf1; color: var(--ps-primary); font-size: 10px; font-weight: 800; padding: 3px 10px; border-radius: 999px; }
.ps-employee { display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; background: #f8fafc; border: 1px solid #e2e8f0; border-radius: 8px; padding: 14px 18px; margin-bottom: 22px; }
.ps-employee span { display: block; font-size: 9px; font-weight: 700; color: #94a3b8; letter-spacing: .05em; }
.ps-employee strong { font-size: 11px; }
.ps-cards { display: flex; gap: 18px; margin-bottom: 22px; }
.ps-card { flex: 1; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; }
.ps-card-head { padding: 9px 14px; font-size: 11px; font-weight: 800; letter-spacing: .05em; }
.ps-earn { background: #f0fdf4; color: #166534; border-bottom: 2px solid #22c55e; }
.ps-ded { background: #fef2f2; color: #991b1b; border-bottom: 2px solid #ef4444; }
.ps-line, .ps-card-foot { display: flex; justify-content: space-between; padding: 6px 14px; }
.ps-card-foot { background: #f8fafc; border-top: 1px solid #e2e8f0; font-weight: 700; }
.ps-net { display: flex; justify-content: space-between; align-items: center; background: linear-gradient(135deg, var(--ps-primary), var(--ps-accent)); color: #fff; border-radius: 8px; padding: 16px 22px; margin-bottom: 22px; }
.ps-net-title { font-size: 11px; font-weight: 700; letter-spacing: .08em; }
.ps-net-words { font-size: 11px; opacity: .85; font-style: italic; margin-top: 4px; }
.ps-net-amount { font-size: 24px; font-weight: 900; }
.ps-footer { text-align: center; color: #94a3b8; font-size: 10px; border-top: 1px solid #f1f5f9; padding-top: 12px; }"""

DEFAULT_CONFIG = {
    "primaryColor": "#1E3A8A",
    "accentColor": "#FFFFFF",
    "showCompanyLogo": True,
    "showEmployeeBank": True,
    "showNetInWords": True,
    "disclaimerText": "This is a computer-generated payslip and does not require a signature.",
}

STARTERS = {
    "CLASSIC_NAVY": {
        "name": "Classic Navy",
        "description": "Corporate layout: navy header, side-by-side earnings and deductions, net pay banner.",
        "html": _CLASSIC_NAVY_HTML,
        "css": _CLASSIC_NAVY_CSS,
        "configuration": {**DEFAULT_CONFIG},
    },
    "MODERN_EMERALD": {
        "name": "Modern Emerald",
        "description": "Card-based layout with an emerald accent bar and gradient net pay panel.",
        "html": _MODERN_EMERALD_HTML,
        "css": _MODERN_EMERALD_CSS,
        "configuration": {**DEFAULT_CONFIG, "primaryColor": "#0F766E", "accentColor": "#10B981"},
    },
}


def list_starters() -> List[dict]:
    return [
        {"key": key, "name": s["name"], "description": s["description"],
         "htmlContent": s["html"], "cssContent": s["css"], "configurationJson": s["configuration"]}
        for key, s in STARTERS.items()
    ]


# ── Validation ───────────────────────────────────────────────────────────────

def _bad_request(detail: str):
    return HTTPException(status.HTTP_400_BAD_REQUEST, detail=detail)


_FORBIDDEN_TAGS = re.compile(
    r"<\s*/?\s*(script|iframe|frame|frameset|object|embed|applet|meta|link|base|form|input|button|"
    r"textarea|select|svg|math|template|portal|noscript|style)\b",
    re.IGNORECASE,
)
_EVENT_HANDLER = re.compile(r"[\s/\"'`]on[a-z]+\s*=", re.IGNORECASE)
_BAD_SCHEME = re.compile(r"(javascript|vbscript|livescript)\s*:|data\s*:\s*text/", re.IGNORECASE)
_URL_ATTR = re.compile(
    r"\b(?:src|href|srcset|action|formaction|background|poster|xlink:href)\s*=\s*"
    r"(?:\"([^\"]*)\"|'([^']*)'|([^\s>]*))",
    re.IGNORECASE,
)
_LOGO_EXPR = re.compile(r"\{\{\s*company\.logo_data_uri\s*\}\}")
_STYLE_ATTR = re.compile(r"\bstyle\s*=\s*(?:\"([^\"]*)\"|'([^']*)')", re.IGNORECASE)
_CSS_EXTERNAL = re.compile(r"@import|expression\s*\(|behavior\s*:|-moz-binding", re.IGNORECASE)
_CSS_URL = re.compile(r"url\s*\(\s*[\"']?\s*([^\"')\s]*)", re.IGNORECASE)
_COLOR = re.compile(r"^#[0-9a-fA-F]{3,8}$")
_BODY = re.compile(r"<body\b[^>]*>([\s\S]*?)(</body\s*>|$)", re.IGNORECASE)
_STYLE_BLOCK = re.compile(r"<style\b[^>]*>([\s\S]*?)</style\s*>", re.IGNORECASE)
_DOC_SHELL = re.compile(r"<!doctype[^>]*>|</?html\b[^>]*>|<head\b[^>]*>[\s\S]*?</head\s*>|</?body\b[^>]*>",
                        re.IGNORECASE)


def _check_markup(text: str, where: str) -> None:
    """Refuse anything that could execute or load something; checked on the raw
    text and on its entity-decoded form (so &#106;avascript: is caught too)."""
    for candidate in (text, _html.unescape(text)):
        if _FORBIDDEN_TAGS.search(candidate):
            raise _bad_request(f"{where}: <script>, <style>, <svg>, frames, forms and embedded objects are not allowed "
                               "(put styles in the CSS field).")
        if _EVENT_HANDLER.search(candidate):
            raise _bad_request(f"{where}: inline event handlers (onclick, onload, ...) are not allowed.")
        if _BAD_SCHEME.search(candidate):
            raise _bad_request(f"{where}: javascript:/vbscript:/data:text URLs are not allowed.")
        for groups in _URL_ATTR.findall(candidate):
            v = next((g for g in groups if g), "").strip().lower()
            if not v or v.startswith("#") or v.startswith("data:image/") or v.startswith("mailto:"):
                continue
            if _LOGO_EXPR.fullmatch(v):
                continue
            raise _bad_request(f"{where}: links and images may only use data:image/ URIs or "
                               "{{ company.logo_data_uri }} — external addresses are not allowed.")
        for groups in _STYLE_ATTR.findall(candidate):
            style = next((g for g in groups if g), "")
            if _CSS_EXTERNAL.search(style):
                raise _bad_request(f"{where}: style attributes may not use @import, expression() or behavior.")
            for value in _CSS_URL.findall(style):
                if not value.strip().lower().startswith("data:"):
                    raise _bad_request(f"{where}: style attributes may only use data: URIs in url() — "
                                       "external addresses are not allowed.")


def _check_css(css: str) -> None:
    for candidate in (css, _html.unescape(css)):
        if _CSS_EXTERNAL.search(candidate):
            raise _bad_request("CSS: @import, expression(), behavior and -moz-binding are not allowed.")
        for value in _CSS_URL.findall(candidate):
            if not value.strip().lower().startswith("data:"):
                raise _bad_request("CSS: url() may only reference data: URIs — external addresses are not allowed.")
        if "</" in candidate or "<!" in candidate:
            raise _bad_request("CSS: markup is not allowed in the stylesheet.")


# Every placeholder a template may use — must match build_payslip_context /
# sample_context. `None` = a plain value (no attributes of its own).
_LINE = {"label": None, "amount": None, "amount_formatted": None}
_IDENTIFIER = {"label": None, "value": None}
PLACEHOLDER_SCHEMA = {
    "company": {"name": None, "address": None, "tax_id": None, "registration_no": None, "logo_data_uri": None},
    "employee": {"name": None, "id": None, "department": None, "designation": None, "date_of_joining": None,
                 "bank_name": None, "bank_account": None, "identifiers": [_IDENTIFIER]},
    "payroll": {"period": None, "pay_date": None, "payslip_number": None, "total_days": None,
                "payable_days": None, "unpaid_days": None, "country": None},
    "currency": {"code": None, "symbol": None},
    "earnings": [_LINE],
    "deductions": [_LINE],
    "totals": {"gross_pay": None, "gross_pay_formatted": None, "total_deductions": None,
               "total_deductions_formatted": None, "net_pay": None, "net_pay_formatted": None,
               "net_pay_in_words": None},
    "config": {key: None for key in DEFAULT_CONFIG},
    "disclaimer": None,
    "generated_on": None,
}
_ANY = object()          # a template's own variable ({% set %}, macro args, loops over other things)
_BUILTINS = {"range": _ANY, "loop": _ANY, "caller": _ANY, "varargs": _ANY, "kwargs": _ANY}
# What a payslip must show before its template can be published.
REQUIRED_PLACEHOLDERS = {
    "employee.name": "the employee's name",
    "totals.net_pay_formatted": "net pay",
    "earnings": "the earnings lines",
    "deductions": "the deduction lines",
}


def _resolve(node, scope):
    """Schema for a Name/Getattr/Getitem chain, or _ANY, or raises KeyError(path)."""
    if isinstance(node, nodes.Name):
        if node.name in scope:
            return scope[node.name], node.name
        raise KeyError(node.name)
    if isinstance(node, (nodes.Getattr, nodes.Getitem)):
        if isinstance(node, nodes.Getattr):
            attr = node.attr
        elif isinstance(node.arg, nodes.Const) and isinstance(node.arg.value, str):
            attr = node.arg.value
        else:   # numeric / computed index: element of a list, or anything
            parent, path = _resolve(node.node, scope)
            if isinstance(parent, list):
                return parent[0], f"{path}[]"
            return _ANY, f"{path}[]"
        parent, path = _resolve(node.node, scope)
        full = f"{path}.{attr}"
        if parent is _ANY or parent is None:   # None: a plain value; its str methods are fine
            return _ANY, full
        if isinstance(parent, dict) and attr in parent:
            return parent[attr], full
        raise KeyError(full)
    return _ANY, "?"


def _check_placeholders(tree) -> set:
    """Refuse unknown placeholders (a misspelt name would otherwise render
    blank). Returns the set of placeholder paths the template uses."""
    scope = {**PLACEHOLDER_SCHEMA, **_BUILTINS}
    # Names the template declares itself.
    for node in tree.find_all((nodes.Assign, nodes.AssignBlock)):
        for name in node.target.find_all(nodes.Name) if not isinstance(node.target, nodes.Name) else [node.target]:
            scope[name.name] = _ANY
    for node in tree.find_all((nodes.Macro, nodes.CallBlock)):
        for arg in getattr(node, "args", []):
            scope[arg.name] = _ANY
    # Loop variables take the shape of one item of what they loop over.
    for node in tree.find_all(nodes.For):
        try:
            item, _path = _resolve(node.iter, scope)
        except KeyError:
            item = _ANY
        element = item[0] if isinstance(item, list) else _ANY
        if isinstance(node.target, nodes.Name):
            scope[node.target.name] = element
        else:
            for name in node.target.find_all(nodes.Name):
                scope[name.name] = _ANY

    used, unknown = set(), []
    outer = set()
    for node in tree.find_all((nodes.Getattr, nodes.Getitem)):
        outer.add(id(node.node))
    for node in tree.find_all((nodes.Name, nodes.Getattr, nodes.Getitem)):
        if id(node) in outer or (isinstance(node, nodes.Name) and node.ctx != "load"):
            continue
        try:
            _schema, path = _resolve(node, scope)
            used.add(path)
            parts = path.replace("[]", "").split(".")
            for i in range(1, len(parts)):
                used.add(".".join(parts[:i]))
        except KeyError as exc:
            unknown.append(exc.args[0])
    if unknown:
        names = ", ".join(sorted(set(unknown)))
        raise _bad_request(f"Unknown placeholder(s): {names}. Use the names in the placeholder list "
                           "(for example employee.name, totals.net_pay_formatted, earnings).")
    return used


def missing_required(fragment: str) -> List[str]:
    """Descriptions of the required placeholders a template does not use."""
    used = _check_jinja(fragment)
    return [label for path, label in REQUIRED_PLACEHOLDERS.items() if path not in used]


def _check_jinja(source: str) -> set:
    env = _sandbox()
    try:
        tree = env.parse(source)
    except jinja2.TemplateSyntaxError as exc:
        raise _bad_request(f"Template syntax error at line {exc.lineno}: {exc.message}")
    for node in tree.find_all((nodes.Include, nodes.Import, nodes.FromImport, nodes.Extends)):
        raise _bad_request("Template: include / import / extends are not allowed.")
    for node in tree.find_all((nodes.EvalContextModifier, nodes.ScopedEvalContextModifier)):
        raise _bad_request("Template: turning autoescape off is not allowed.")
    for node in tree.find_all(nodes.Filter):
        if node.name in ("safe", "attr"):
            raise _bad_request(f"Template: the '{node.name}' filter is not allowed.")
    for node in tree.find_all(nodes.MarkSafe):
        raise _bad_request("Template: marking output as safe is not allowed.")
    return _check_placeholders(tree)


def normalize_html(html_content: str) -> Tuple[str, str]:
    """Reduce an uploaded document to a body fragment. Returns (fragment,
    css pulled out of any <style> blocks)."""
    text = html_content or ""
    css = "\n".join(m.strip() for m in _STYLE_BLOCK.findall(text))
    text = _STYLE_BLOCK.sub("", text)
    body = _BODY.search(text)
    if body:
        text = body.group(1)
    text = _DOC_SHELL.sub("", text)
    return text.strip(), css


def normalize_config(config: Optional[dict]) -> dict:
    out = {**DEFAULT_CONFIG}
    for key, value in (config or {}).items():
        if key not in DEFAULT_CONFIG:
            continue
        if key in ("primaryColor", "accentColor"):
            if not isinstance(value, str) or not _COLOR.match(value.strip()):
                raise _bad_request(f"{key} must be a hex colour such as #1E3A8A.")
            out[key] = value.strip()
        elif key == "disclaimerText":
            out[key] = str(value or "")[:500]
        else:
            out[key] = bool(value)
    return out


def validate_template(html_content: str, css_content: Optional[str]) -> Tuple[str, str, List[str]]:
    """Validate a template for saving. Returns (html_fragment, css, warnings).
    Raises 400 on anything unsafe or unparseable."""
    if not html_content or not html_content.strip():
        raise _bad_request("Template HTML cannot be empty.")
    if len(html_content.encode("utf-8")) > MAX_HTML_BYTES:
        raise _bad_request(f"Template HTML is larger than {MAX_HTML_BYTES // 1000} KB.")
    css = css_content or ""
    if len(css.encode("utf-8")) > MAX_CSS_BYTES:
        raise _bad_request(f"Template CSS is larger than {MAX_CSS_BYTES // 1000} KB.")
    fragment, inline_css = normalize_html(html_content)
    if inline_css:
        css = (css + "\n" + inline_css).strip()
    _check_markup(fragment, "HTML")
    used = _check_jinja(fragment)
    if css:
        _check_css(css)
    warnings = [f"'{path}' ({label}) is not used — it must be before the template can be published."
                for path, label in REQUIRED_PLACEHOLDERS.items() if path not in used]
    return fragment, css, warnings


# ── Rendering ────────────────────────────────────────────────────────────────

class _PayslipSandbox(SandboxedEnvironment):
    """Sandbox with autoescape and limits on range() and on string/list
    multiplication and powers, so a template cannot exhaust the server."""
    intercepted_binops = frozenset(["*", "**"])

    def call_binop(self, context, operator, left, right):
        if operator == "**":
            if isinstance(right, (int, float)) and abs(right) > 64:
                raise SecurityError("exponent too large")
            return left ** right
        if operator == "*":
            for seq, n in ((left, right), (right, left)):
                if isinstance(seq, (str, list, tuple)) and isinstance(n, int) and n * max(len(seq), 1) > 10_000:
                    raise SecurityError("result too large")
            return left * right
        return super().call_binop(context, operator, left, right)


def _limited_range(*args):
    r = range(*args)
    if len(r) > 1000:
        raise SecurityError("range() is limited to 1000 items")
    return r


def _sandbox() -> SandboxedEnvironment:
    env = _PayslipSandbox(autoescape=True, undefined=jinja2.ChainableUndefined,
                          finalize=lambda value: "" if value is None else value)
    env.globals = {"range": _limited_range}
    return env


_CSP = ("default-src 'none'; style-src 'unsafe-inline'; img-src data:; font-src data:; "
        "form-action 'none'; base-uri 'none'")


def render_document(fragment: str, css: Optional[str], context: dict, watermark: bool = False) -> str:
    """Render a template fragment into a complete, self-contained HTML document."""
    try:
        body = _sandbox().from_string(fragment).render(**context)
    except SecurityError as exc:
        raise _bad_request(f"Template refused by the sandbox: {exc}")
    except jinja2.TemplateError as exc:
        raise _bad_request(f"Template could not be rendered: {exc}")
    except (TypeError, ValueError, ArithmeticError, AttributeError, KeyError) as exc:
        raise _bad_request(f"Template could not be rendered: {exc}")
    cfg = context.get("config") or DEFAULT_CONFIG
    variables = f":root {{ --ps-primary: {cfg['primaryColor']}; --ps-accent: {cfg['accentColor']}; }}"
    mark = ""
    if watermark:
        mark = ("body::after { content: 'PREVIEW \\2014  EVALUATION ONLY'; position: fixed; top: 45%; left: 0; "
                "right: 0; text-align: center; font: 700 42px Arial, sans-serif; color: rgba(30,58,138,.22); "
                "transform: rotate(-30deg); pointer-events: none; }")
    safe_css = (css or "").replace("</", "<\\/")
    return (
        "<!DOCTYPE html><html><head><meta charset=\"utf-8\">"
        f"<meta http-equiv=\"Content-Security-Policy\" content=\"{_CSP}\">"
        f"<style>{variables}</style><style>{safe_css}</style>"
        f"{'<style>' + mark + '</style>' if mark else ''}"
        f"</head><body>{body}</body></html>"
    )


# ── Payslip context ──────────────────────────────────────────────────────────

_ONES = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven",
         "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
_TENS = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]


def _words_below_thousand(n: int) -> str:
    parts = []
    if n >= 100:
        parts.append(_ONES[n // 100] + " Hundred")
        n %= 100
    if n >= 20:
        parts.append(_TENS[n // 10] + (" " + _ONES[n % 10] if n % 10 else ""))
    elif n:
        parts.append(_ONES[n])
    return " ".join(parts)


def _international_words(amount: int) -> str:
    if amount == 0:
        return "Zero"
    parts = []
    for value, name in ((10 ** 9, "Billion"), (10 ** 6, "Million"), (1000, "Thousand"), (1, "")):
        chunk, amount = divmod(amount, value)
        if chunk:
            parts.append((_words_below_thousand(chunk) + (" " + name if name else "")).strip())
    return " ".join(parts)


def amount_in_words(amount, country: str) -> str:
    from app.modules.payroll import service as payroll_service
    whole = int(round(float(amount or 0)))
    if country == "IN":
        return f"Rupees {payroll_service._amount_to_words(whole)} Only"
    sign = "Minus " if whole < 0 else ""
    return f"{sign}{_international_words(abs(whole))} Only"


def _mask_account(acc) -> str:
    if not acc:
        return ""
    s = str(acc)
    return s if len(s) <= 4 else "X" * (len(s) - 4) + s[-4:]


def _fmt_date(value) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        try:
            value = datetime.strptime(value[:10], "%Y-%m-%d").date()
        except ValueError:
            return value
    try:
        return value.strftime("%d-%b-%Y")
    except AttributeError:
        return str(value)


def _money(symbol: str, value) -> str:
    return f"{symbol} {float(value or 0):,.2f}"


def _line(symbol: str, label: str, amount) -> dict:
    return {"label": label, "amount": float(amount or 0), "amount_formatted": _money(symbol, amount)}


class NotRepresentable(Exception):
    """The payslip cannot be shown through a template; show the statutory one."""


def build_payslip_context(db: Session, organization_id: int, payslip_id: int, config: Optional[dict] = None
                          ) -> Tuple[dict, PayslipItem]:
    """The template context for one payslip of this organisation."""
    from app.modules.payroll import service as payroll_service
    from app.modules.payroll.models import CompanyComplianceDetails
    from app.modules.organizations.models import Organization

    data, item, run = payroll_service.get_payslip_by_id(db, payslip_id, organization_id)
    if item.status in (PayslipStatus.FAILED, PayslipStatus.PARTIAL):
        raise NotRepresentable("This payslip is blocked or partially calculated; it is shown in the standard format.")

    country = payroll_service._normalize_country(data.get("country") or "IN")
    earnings_items, deduction_items = payroll_service.payslip_line_items(dict(data), country)
    gross = Decimal(str(data.get("salary") or 0))
    total_deductions = Decimal(str(data.get("totalDeductions") or 0))
    earned = sum((Decimal(str(v or 0)) for _l, v in earnings_items), Decimal("0"))
    deducted = sum((Decimal(str(v or 0)) for _l, v in deduction_items), Decimal("0"))
    if abs(earned - gross) > _RECONCILE_TOLERANCE or abs(deducted - total_deductions) > _RECONCILE_TOLERANCE:
        raise NotRepresentable(
            "This payslip's statutory breakdown has lines a template cannot show; it is shown in the standard format.")

    symbol = payroll_service._get_currency_symbol(country)
    cfg = normalize_config(config)

    company = db.query(CompanyComplianceDetails).filter(
        CompanyComplianceDetails.organization_id == organization_id).first()
    org = db.query(Organization).filter(Organization.id == organization_id).first()
    logo = None
    if cfg.get("showCompanyLogo") and org is not None and getattr(org, "logo_path", None):
        from app.modules.organizations.router import _read_logo_data_uri
        logo = _read_logo_data_uri(org.logo_path)

    identifiers = [{"label": label, "value": value or ""}
                   for label, value in payroll_service._payslip_identity_rows(country, data)]
    net = data.get("netPay") or 0

    context = {
        "company": {
            "name": getattr(company, "name", None) or (org.organization_name if org else ""),
            "address": getattr(company, "address", None) or "",
            "tax_id": getattr(company, "tax_no", None) or "",
            "registration_no": getattr(company, "employer_id", None) or "",
            "logo_data_uri": logo,
        },
        "employee": {
            "name": data.get("employee") or "",
            "id": data.get("employeeId"),
            "department": data.get("department") or "",
            "designation": data.get("designation") or "",
            "date_of_joining": _fmt_date(data.get("dateOfJoining")),
            "bank_name": data.get("bankName") or "",
            "bank_account": _mask_account(data.get("bankAccount")),
            "identifiers": identifiers,
        },
        "payroll": {
            "period": data.get("period") or "",
            "pay_date": _fmt_date(data.get("payDate")),
            "payslip_number": data.get("payslipNumber") or "",
            "total_days": data.get("totalWorkingDays"),
            "payable_days": data.get("payableDays"),
            "unpaid_days": data.get("unpaidLeaveDays"),
            "country": country,
        },
        "currency": {"code": payroll_service._get_currency_code(country), "symbol": symbol},
        "earnings": [_line(symbol, label, amount) for label, amount in earnings_items],
        "deductions": [_line(symbol, label, amount) for label, amount in deduction_items],
        "totals": {
            "gross_pay": float(gross), "gross_pay_formatted": _money(symbol, gross),
            "total_deductions": float(total_deductions), "total_deductions_formatted": _money(symbol, total_deductions),
            "net_pay": float(net), "net_pay_formatted": _money(symbol, net),
            "net_pay_in_words": amount_in_words(net, country),
        },
        "config": cfg,
        "disclaimer": cfg["disclaimerText"],
        "generated_on": _fmt_date(date.today()),
    }
    return context, item


def sample_context(country: str = "IN", config: Optional[dict] = None) -> dict:
    """Illustrative data for the editor preview (no real person)."""
    from app.modules.payroll import service as payroll_service
    country = payroll_service._normalize_country(country or "IN")
    symbol = payroll_service._get_currency_symbol(country)
    cfg = normalize_config(config)
    earnings = [("Basic Salary", 50000), ("House Rent Allowance (HRA)", 20000), ("Special Allowance", 12000)]
    deductions = [("Income Tax", 6200), ("Provident Fund (PF)", 6000), ("Professional Tax", 200)]
    gross = sum(v for _l, v in earnings)
    ded = sum(v for _l, v in deductions)
    net = gross - ded
    return {
        "company": {"name": "Example Company Ltd", "address": "1 Example Street, Example City",
                    "tax_id": "TAX-0000000", "registration_no": "REG-0000", "logo_data_uri": None},
        "employee": {"name": "Sample Employee", "id": 1001, "department": "Engineering",
                     "designation": "Software Engineer", "date_of_joining": "01-Apr-2024",
                     "bank_name": "Example Bank", "bank_account": "XXXXXXXX1234",
                     "identifiers": [{"label": "Tax ID", "value": "XXXXX1234X"}]},
        "payroll": {"period": "June 2026", "pay_date": "30-Jun-2026", "payslip_number": "PS-000001",
                    "total_days": 30, "payable_days": 30, "unpaid_days": 0, "country": country},
        "currency": {"code": payroll_service._get_currency_code(country), "symbol": symbol},
        "earnings": [_line(symbol, label, amount) for label, amount in earnings],
        "deductions": [_line(symbol, label, amount) for label, amount in deductions],
        "totals": {"gross_pay": gross, "gross_pay_formatted": _money(symbol, gross),
                   "total_deductions": ded, "total_deductions_formatted": _money(symbol, ded),
                   "net_pay": net, "net_pay_formatted": _money(symbol, net),
                   "net_pay_in_words": amount_in_words(net, country)},
        "config": cfg,
        "disclaimer": cfg["disclaimerText"],
        "generated_on": _fmt_date(date.today()),
    }


# ── Serialisation ────────────────────────────────────────────────────────────

def _version_dict(v: Optional[PayslipTemplateVersion], with_content: bool = True) -> Optional[dict]:
    if v is None:
        return None
    out = {
        "id": v.id,
        "versionNumber": v.version_number,
        "status": v.status,
        "changeSummary": v.change_summary,
        "publishedAt": v.published_at.isoformat() if v.published_at else None,
    }
    if with_content:
        out.update({"htmlContent": v.html_content, "cssContent": v.css_content or "",
                    "configurationJson": normalize_config(v.configuration_json)})
    return out


def _template_dict(t: PayslipTemplate, assigned_countries: List[str]) -> dict:
    versions = list(t.versions)
    latest = versions[-1] if versions else None
    active = next((v for v in reversed(versions) if v.status == "Active"), None)
    return {
        "id": t.id,
        "code": t.code,
        "name": t.name,
        "description": t.description or "",
        "country": t.jurisdiction_country,
        "sourceStarter": t.source_starter,
        "isArchived": bool(t.is_archived),
        "latestVersion": _version_dict(latest),
        "activeVersion": _version_dict(active, with_content=False),
        "hasUnpublishedChanges": bool(latest and latest.status == "Draft"),
        "assignedCountries": assigned_countries,
        "updatedAt": (t.updated_at or t.created_at).isoformat() if (t.updated_at or t.created_at) else None,
    }


# ── Lookups (always org-scoped) ──────────────────────────────────────────────

def _get_template(db: Session, organization_id: int, template_id: int) -> PayslipTemplate:
    t = db.query(PayslipTemplate).filter(
        PayslipTemplate.id == template_id, PayslipTemplate.organization_id == organization_id).first()
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Payslip template not found.")
    return t


def _assignments(db: Session, organization_id: int) -> List[PayslipTemplateAssignment]:
    return db.query(PayslipTemplateAssignment).filter(
        PayslipTemplateAssignment.organization_id == organization_id).all()


def _normalize_scope(country: Optional[str]) -> str:
    c = (country or "").strip().upper()
    if not c or c in ("ALL", "GLOBAL", "DEFAULT"):
        return ALL_COUNTRIES
    if c == "GB":
        c = "UK"
    if not re.fullmatch(r"[A-Z]{2,3}", c):
        raise _bad_request("Country must be a 2-letter code such as IN, UK or US, or ALL.")
    return c


def get_template_detail(db: Session, organization_id: int, template_id: int) -> dict:
    t = _get_template(db, organization_id, template_id)
    assigned = sorted(a.jurisdiction_country for a in _assignments(db, organization_id) if a.template_id == t.id)
    return _template_dict(t, assigned)


def list_templates(db: Session, organization_id: int) -> dict:
    templates = db.query(PayslipTemplate).filter(
        PayslipTemplate.organization_id == organization_id
    ).order_by(PayslipTemplate.is_archived.asc(), PayslipTemplate.name.asc()).all()
    assignments = _assignments(db, organization_id)
    by_template: dict = {}
    for a in assignments:
        by_template.setdefault(a.template_id, []).append(a.jurisdiction_country)
    return {
        "starters": list_starters(),
        "templates": [_template_dict(t, sorted(by_template.get(t.id, []))) for t in templates],
        "assignments": [
            {"country": a.jurisdiction_country, "templateId": a.template_id,
             "templateName": a.template.name if a.template else None,
             "versionId": a.version_id,
             "versionNumber": a.version.version_number if a.version else None}
            for a in sorted(assignments, key=lambda a: (a.jurisdiction_country != ALL_COUNTRIES, a.jurisdiction_country))
        ],
    }


# ── Mutations ────────────────────────────────────────────────────────────────

def _unique_code(db: Session, organization_id: int, wanted: Optional[str], name: str) -> str:
    base = re.sub(r"[^A-Z0-9]+", "-", (wanted or name or "TEMPLATE").upper()).strip("-")[:50] or "TEMPLATE"
    if wanted:
        if db.query(PayslipTemplate.id).filter(PayslipTemplate.organization_id == organization_id,
                                               PayslipTemplate.code == base).first():
            raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Template code '{base}' is already used.")
        return base
    code, n = base, 1
    while db.query(PayslipTemplate.id).filter(PayslipTemplate.organization_id == organization_id,
                                              PayslipTemplate.code == code).first():
        n += 1
        code = f"{base[:46]}-{n}"
    return code


def create_template(db: Session, organization_id: int, actor_id: Optional[int], data: dict) -> dict:
    name = (data.get("name") or "").strip()
    starter_key = (data.get("starter") or "").strip().upper() or None
    starter = STARTERS.get(starter_key) if starter_key else None
    if starter_key and starter is None:
        raise _bad_request(f"Unknown starter '{starter_key}'.")
    if not name:
        name = f"{starter['name']} (copy)" if starter else ""
    if not name:
        raise _bad_request("Template name is required.")

    html_content = data.get("htmlContent") or (starter or STARTERS["CLASSIC_NAVY"])["html"]
    css_content = data.get("cssContent") if data.get("htmlContent") else (starter or STARTERS["CLASSIC_NAVY"])["css"]
    config = data.get("configurationJson") or (starter or STARTERS["CLASSIC_NAVY"])["configuration"]
    fragment, css, warnings = validate_template(html_content, css_content)
    config = normalize_config(config)
    country = data.get("country")
    country = None if not country or _normalize_scope(country) == ALL_COUNTRIES else _normalize_scope(country)

    t = PayslipTemplate(
        organization_id=organization_id,
        code=_unique_code(db, organization_id, (data.get("code") or "").strip() or None, name),
        name=name[:200],
        description=(data.get("description") or (starter["description"] if starter else "")).strip() or None,
        jurisdiction_country=country,
        source_starter=starter_key,
        created_by_id=actor_id,
    )
    db.add(t)
    db.flush()
    db.add(PayslipTemplateVersion(
        organization_id=organization_id, template_id=t.id, version_number=1, status="Draft",
        html_content=fragment, css_content=css, configuration_json=config,
        change_summary=(data.get("changeSummary") or "Initial draft")[:300], created_by_id=actor_id,
    ))
    db.commit()
    db.refresh(t)
    out = get_template_detail(db, organization_id, t.id)
    out["warnings"] = warnings
    return out


def update_template(db: Session, organization_id: int, template_id: int, actor_id: Optional[int], data: dict) -> dict:
    t = _get_template(db, organization_id, template_id)
    if t.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This template is archived.")
    if "name" in data and (data.get("name") or "").strip():
        t.name = data["name"].strip()[:200]
    if "description" in data:
        t.description = (data.get("description") or "").strip() or None
    if "country" in data:
        c = data.get("country")
        t.jurisdiction_country = None if not c or _normalize_scope(c) == ALL_COUNTRIES else _normalize_scope(c)

    versions = list(t.versions)
    latest = versions[-1] if versions else None
    warnings: List[str] = []
    content_keys = ("htmlContent", "cssContent", "configurationJson")
    if any(k in data for k in content_keys) or latest is None:
        html_content = data.get("htmlContent") if data.get("htmlContent") is not None else (
            latest.html_content if latest else STARTERS["CLASSIC_NAVY"]["html"])
        css_content = data.get("cssContent") if "cssContent" in data else (latest.css_content if latest else "")
        config = data.get("configurationJson") if "configurationJson" in data else (
            latest.configuration_json if latest else None)
        fragment, css, warnings = validate_template(html_content, css_content)
        config = normalize_config(config)
        if latest is not None and latest.status == "Draft":
            latest.html_content, latest.css_content, latest.configuration_json = fragment, css, config
            if data.get("changeSummary"):
                latest.change_summary = data["changeSummary"][:300]
        else:
            db.add(PayslipTemplateVersion(
                organization_id=organization_id, template_id=t.id,
                version_number=(latest.version_number + 1) if latest else 1, status="Draft",
                html_content=fragment, css_content=css, configuration_json=config,
                change_summary=(data.get("changeSummary") or "Draft revision")[:300], created_by_id=actor_id,
            ))
    t.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(t)
    out = get_template_detail(db, organization_id, t.id)
    out["warnings"] = warnings
    return out


def publish_template(db: Session, organization_id: int, template_id: int, actor_id: Optional[int]) -> dict:
    """Make the latest Draft the Active version. Countries already using this
    template move to the new version (payslips already issued keep theirs)."""
    t = _get_template(db, organization_id, template_id)
    if t.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This template is archived.")
    versions = list(t.versions)
    latest = versions[-1] if versions else None
    if latest is None or latest.status != "Draft":
        raise HTTPException(status.HTTP_409_CONFLICT, detail="There are no unpublished changes to publish.")
    # Re-validate: rules may have tightened since the draft was saved.
    validate_template(latest.html_content, latest.css_content)
    # A template without real payslip data would show the same static text
    # on every employee's payslip.
    missing = missing_required(latest.html_content)
    if missing:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail="This template cannot be published until it shows " + ", ".join(missing) +
                                   ". Add those placeholders and save the draft again.")
    for v in versions:
        if v.status == "Active":
            v.status = "Archived"
    latest.status = "Active"
    latest.published_by_id = actor_id
    latest.published_at = datetime.utcnow()
    for a in _assignments(db, organization_id):
        if a.template_id == t.id:
            a.version_id = latest.id
            a.assigned_by_id = actor_id
    t.updated_at = datetime.utcnow()
    db.commit()
    return get_template_detail(db, organization_id, t.id)


def assign_template(db: Session, organization_id: int, actor_id: Optional[int], template_id: int,
                    country: Optional[str]) -> dict:
    t = _get_template(db, organization_id, template_id)
    if t.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="This template is archived.")
    active = next((v for v in reversed(list(t.versions)) if v.status == "Active"), None)
    if active is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Publish the template before assigning it.")
    scope = _normalize_scope(country)
    a = db.query(PayslipTemplateAssignment).filter(
        PayslipTemplateAssignment.organization_id == organization_id,
        PayslipTemplateAssignment.jurisdiction_country == scope).first()
    if a is None:
        a = PayslipTemplateAssignment(organization_id=organization_id, jurisdiction_country=scope)
        db.add(a)
    a.template_id, a.version_id, a.assigned_by_id = t.id, active.id, actor_id
    db.commit()
    return list_templates(db, organization_id)


def unassign(db: Session, organization_id: int, country: Optional[str]) -> dict:
    scope = _normalize_scope(country)
    db.query(PayslipTemplateAssignment).filter(
        PayslipTemplateAssignment.organization_id == organization_id,
        PayslipTemplateAssignment.jurisdiction_country == scope).delete(synchronize_session=False)
    db.commit()
    return list_templates(db, organization_id)


def archive_template(db: Session, organization_id: int, template_id: int) -> dict:
    """Archive (never delete: issued payslips may point at its versions) and
    remove it from every country it was assigned to."""
    t = _get_template(db, organization_id, template_id)
    db.query(PayslipTemplateAssignment).filter(
        PayslipTemplateAssignment.organization_id == organization_id,
        PayslipTemplateAssignment.template_id == t.id).delete(synchronize_session=False)
    t.is_archived = True
    t.updated_at = datetime.utcnow()
    db.commit()
    return list_templates(db, organization_id)


# ── Preview / render ─────────────────────────────────────────────────────────

def preview(html_content: str, css_content: Optional[str], config: Optional[dict], country: Optional[str]) -> dict:
    fragment, css, warnings = validate_template(html_content, css_content)
    context = sample_context(country or "IN", config)
    return {"renderedHtml": render_document(fragment, css, context), "warnings": warnings}


def _resolve_version(db: Session, organization_id: int, country: Optional[str]) -> Optional[PayslipTemplateVersion]:
    scopes = []
    if country:
        scopes.append(_normalize_scope(country))
    scopes.append(ALL_COUNTRIES)
    for scope in scopes:
        a = db.query(PayslipTemplateAssignment).filter(
            PayslipTemplateAssignment.organization_id == organization_id,
            PayslipTemplateAssignment.jurisdiction_country == scope).first()
        if a is not None and a.version is not None and a.version.status == "Active":
            return a.version
    return None


def render_payslip(db: Session, organization_id: int, payslip_id: int) -> dict:
    """The payslip rendered through its frozen template version, or (before its
    run is approved) the org's current assignment. 404 TEMPLATE_NOT_ASSIGNED /
    409 TEMPLATE_NOT_REPRESENTABLE tell the UI to show the statutory payslip."""
    from app.modules.payroll import service as payroll_service

    item = db.query(PayslipItem).filter(
        PayslipItem.id == payslip_id, PayslipItem.organization_id == organization_id).first()
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=f"Payslip {payslip_id} not found.")
    version = None
    frozen = False
    if item.template_version_id:
        version = db.query(PayslipTemplateVersion).filter(
            PayslipTemplateVersion.id == item.template_version_id,
            PayslipTemplateVersion.organization_id == organization_id).first()
        frozen = version is not None
    if version is None:
        version = _resolve_version(db, organization_id, item.country_code)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND,
                            detail={"code": "TEMPLATE_NOT_ASSIGNED", "message": "No payslip template is assigned."})
    try:
        context, _item = build_payslip_context(db, organization_id, payslip_id, version.configuration_json)
    except NotRepresentable as exc:
        raise HTTPException(status.HTTP_409_CONFLICT,
                            detail={"code": "TEMPLATE_NOT_REPRESENTABLE", "message": str(exc)})
    watermark = payroll_service._is_evaluation_workspace(db, organization_id)
    return {
        "renderedHtml": render_document(version.html_content, version.css_content, context, watermark=watermark),
        "metadata": {
            "payslipId": item.id,
            "templateId": version.template_id,
            "templateName": version.template.name if version.template else None,
            "versionId": version.id,
            "versionNumber": version.version_number,
            "frozen": frozen,
        },
    }


# ── Freezing at approval ─────────────────────────────────────────────────────

def freeze_run_templates(db: Session, run: PayrollRun) -> None:
    """Pin each payslip of an approved run to the template version it is issued
    with. Runs in a savepoint: a failure is logged and never blocks approval."""
    try:
        with db.begin_nested():
            cache: dict = {}
            items = db.query(PayslipItem).filter(
                PayslipItem.payroll_run_id == run.id, PayslipItem.template_version_id.is_(None)).all()
            for it in items:
                key = (it.country_code or "").upper()
                if key not in cache:
                    cache[key] = _resolve_version(db, run.organization_id, it.country_code)
                if cache[key] is not None:
                    it.template_version_id = cache[key].id
    except Exception:  # noqa: BLE001 — presentation only; payroll approval must proceed
        logger.exception("Could not freeze payslip templates for run %s", run.id)
