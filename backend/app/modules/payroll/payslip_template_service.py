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
# come from the --ps-primary / --ps-accent variables set from the template's
# configuration. Table layout and plain CSS only (no flexbox / grid /
# gradients) so a template renders the same in the browser and in the PDF
# engine (xhtml2pdf).

_CLASSIC_NAVY_HTML = """<div class="payslip">
  <table class="ps-header" width="100%"><tr>
    <td width="62%" valign="top">
      {% if config.showCompanyLogo and company.logo_data_uri %}<img src="{{ company.logo_data_uri }}" alt="" class="ps-logo" height="48"><br>{% endif %}
      <h1>{{ company.name }}</h1>
      <p>{{ company.address }}</p>
      {% if company.tax_id %}<p>Tax ID: {{ company.tax_id }}</p>{% endif %}
    </td>
    <td width="38%" valign="top" align="right">
      <span class="ps-badge">&nbsp;PAYSLIP&nbsp;</span>
      <p class="ps-period-label">{{ payroll.period }}</p>
      <p class="ps-muted">Pay date: {{ payroll.pay_date }}</p>
    </td>
  </tr></table>
  <div class="ps-rule"></div>

  {% set details = [
    {"label": "Employee Name", "value": employee.name},
    {"label": "Employee ID", "value": employee.id},
    {"label": "Department", "value": employee.department},
    {"label": "Designation", "value": employee.designation},
    {"label": "Date of Joining", "value": employee.date_of_joining},
    {"label": "Payable / Working Days", "value": (payroll.payable_days or "-") ~ " / " ~ (payroll.total_days or "-")}
  ] + employee.identifiers + ([{"label": "Bank", "value": employee.bank_name},
                               {"label": "Account", "value": employee.bank_account}] if config.showEmployeeBank else []) %}
  <table class="ps-details" width="100%">
    {% for row in details | batch(3, {"label": "", "value": ""}) %}<tr>
      {% for f in row %}<td width="33%"><span class="ps-label">{{ f.label }}</span><br><strong>{{ f.value or ("-" if f.label else "") }}</strong></td>{% endfor %}
    </tr>{% endfor %}
  </table>

  <table class="ps-split" width="100%"><tr>
    <td width="49%" valign="top">
      <table class="ps-table" width="100%">
        <tr><th align="left">EARNINGS</th><th align="right">{{ currency.code }}</th></tr>
        {% for line in earnings %}<tr><td>{{ line.label }}</td><td align="right">{{ line.amount_formatted }}</td></tr>{% endfor %}
        <tr class="ps-foot"><td>Gross Earnings</td><td align="right">{{ totals.gross_pay_formatted }}</td></tr>
      </table>
    </td>
    <td width="2%"></td>
    <td width="49%" valign="top">
      <table class="ps-table" width="100%">
        <tr><th align="left">DEDUCTIONS</th><th align="right">{{ currency.code }}</th></tr>
        {% for line in deductions %}<tr><td>{{ line.label }}</td><td align="right">{{ line.amount_formatted }}</td></tr>{% endfor %}
        <tr class="ps-foot"><td>Total Deductions</td><td align="right">{{ totals.total_deductions_formatted }}</td></tr>
      </table>
    </td>
  </tr></table>

  <table class="ps-net" width="100%"><tr>
    <td valign="middle"><span class="ps-net-title">NET PAY</span>{% if config.showNetInWords %}<br><span class="ps-net-words">{{ totals.net_pay_in_words }}</span>{% endif %}</td>
    <td valign="middle" align="right" class="ps-net-amount">{{ totals.net_pay_formatted }}</td>
  </tr></table>

  <table class="ps-footer" width="100%">
    <tr><td colspan="2" align="center">{{ disclaimer }}</td></tr>
    <tr><td>Payslip {{ payroll.payslip_number }}</td><td align="right">Generated {{ generated_on }}</td></tr>
  </table>
</div>"""

_CLASSIC_NAVY_CSS = """body { font-family: Arial, Helvetica, sans-serif; color: #1e293b; background-color: #ffffff; font-size: 10pt; margin: 0; }
.payslip { max-width: 820px; margin: 0 auto; padding: 24px; }
table { border-collapse: collapse; }
p { margin: 0; }
h1 { font-size: 16pt; color: var(--ps-primary); margin: 0 0 2px 0; }
.ps-header p, .ps-muted { font-size: 8.5pt; color: #64748b; }
.ps-logo { max-height: 48px; }
.ps-badge { background-color: var(--ps-primary); color: #ffffff; font-weight: bold; font-size: 10pt; padding: 3px 10px; }
.ps-period-label { font-weight: bold; font-size: 11pt; margin-top: 6px; }
.ps-rule { border-bottom: 2px solid var(--ps-primary); margin: 10px 0 14px 0; }
.ps-details { background-color: #f8fafc; border: 1px solid #e2e8f0; margin-bottom: 14px; }
.ps-details td { padding: 6px 10px; vertical-align: top; font-size: 9pt; }
.ps-label { font-size: 7.5pt; color: #64748b; }
.ps-split { margin-bottom: 14px; }
.ps-table { border: 1px solid #cbd5e1; }
.ps-table th { background-color: var(--ps-primary); color: #ffffff; font-size: 8.5pt; padding: 6px 8px; }
.ps-table td { padding: 5px 8px; font-size: 9pt; border-bottom: 1px solid #f1f5f9; }
.ps-foot td { background-color: #f1f5f9; font-weight: bold; border-top: 1px solid #cbd5e1; }
.ps-net { background-color: var(--ps-primary); color: #ffffff; margin-bottom: 14px; }
.ps-net td { padding: 10px 14px; }
.ps-net-title { font-weight: bold; font-size: 10pt; }
.ps-net-words { font-size: 8.5pt; font-style: italic; }
.ps-net-amount { font-size: 16pt; font-weight: bold; color: var(--ps-accent); }
.ps-footer { border-top: 1px solid #e2e8f0; color: #94a3b8; font-size: 8pt; }
.ps-footer td { padding-top: 6px; }"""

_MODERN_EMERALD_HTML = """<div class="payslip">
  <div class="ps-bar"></div>
  <table class="ps-header" width="100%"><tr>
    <td width="62%" valign="top">
      {% if config.showCompanyLogo and company.logo_data_uri %}<img src="{{ company.logo_data_uri }}" alt="" class="ps-logo" height="44"><br>{% endif %}
      <h1>{{ company.name }}</h1>
      <p>{{ company.address }}{% if company.tax_id %} &middot; Tax ID: {{ company.tax_id }}{% endif %}</p>
    </td>
    <td width="38%" valign="top" align="right">
      <span class="ps-tag">&nbsp;PAYSLIP&nbsp;</span>
      <h2>{{ payroll.period }}</h2>
      <p>Payment date: {{ payroll.pay_date }}</p>
    </td>
  </tr></table>

  {% set details = [
    {"label": "Employee", "value": employee.name},
    {"label": "Employee ID", "value": employee.id},
    {"label": "Department", "value": employee.department},
    {"label": "Designation", "value": employee.designation}
  ] + employee.identifiers + ([{"label": "Bank account", "value": employee.bank_name ~ " " ~ employee.bank_account}]
                              if config.showEmployeeBank else []) %}
  <table class="ps-employee" width="100%">
    {% for row in details | batch(4, {"label": "", "value": ""}) %}<tr>
      {% for f in row %}<td width="25%"><span class="ps-label">{{ f.label | upper }}</span><br><strong>{{ f.value or ("-" if f.label else "") }}</strong></td>{% endfor %}
    </tr>{% endfor %}
  </table>

  <table class="ps-split" width="100%"><tr>
    <td width="49%" valign="top">
      <table class="ps-table" width="100%">
        <tr><th class="ps-earn" align="left">EARNINGS</th><th class="ps-earn" align="right">{{ currency.code }}</th></tr>
        {% for line in earnings %}<tr><td>{{ line.label }}</td><td align="right"><strong>{{ line.amount_formatted }}</strong></td></tr>{% endfor %}
        <tr class="ps-foot"><td>Gross Pay</td><td align="right">{{ totals.gross_pay_formatted }}</td></tr>
      </table>
    </td>
    <td width="2%"></td>
    <td width="49%" valign="top">
      <table class="ps-table" width="100%">
        <tr><th class="ps-ded" align="left">DEDUCTIONS</th><th class="ps-ded" align="right">{{ currency.code }}</th></tr>
        {% for line in deductions %}<tr><td>{{ line.label }}</td><td align="right"><strong>{{ line.amount_formatted }}</strong></td></tr>{% endfor %}
        <tr class="ps-foot"><td>Total Deductions</td><td align="right">{{ totals.total_deductions_formatted }}</td></tr>
      </table>
    </td>
  </tr></table>

  <table class="ps-net" width="100%"><tr>
    <td valign="middle"><span class="ps-net-title">NET PAYABLE</span>{% if config.showNetInWords %}<br><span class="ps-net-words">{{ totals.net_pay_in_words }}</span>{% endif %}</td>
    <td valign="middle" align="right" class="ps-net-amount">{{ totals.net_pay_formatted }}</td>
  </tr></table>

  <p class="ps-footer">{{ disclaimer }}</p>
</div>"""

_MODERN_EMERALD_CSS = """body { font-family: Arial, Helvetica, sans-serif; color: #0f172a; background-color: #ffffff; font-size: 10pt; margin: 0; }
.payslip { max-width: 820px; margin: 0 auto; padding: 24px; }
table { border-collapse: collapse; }
p { margin: 0; }
.ps-bar { height: 6px; background-color: var(--ps-primary); margin-bottom: 14px; }
h1 { font-size: 17pt; color: var(--ps-primary); margin: 0 0 2px 0; }
h2 { font-size: 12pt; margin: 4px 0 0 0; }
.ps-header p { font-size: 8.5pt; color: #64748b; }
.ps-logo { max-height: 44px; }
.ps-tag { background-color: #ccfbf1; color: var(--ps-primary); font-size: 8pt; font-weight: bold; padding: 2px 8px; }
.ps-employee { background-color: #f8fafc; border: 1px solid #e2e8f0; margin: 14px 0; }
.ps-employee td { padding: 7px 10px; vertical-align: top; font-size: 9pt; }
.ps-label { font-size: 7pt; font-weight: bold; color: #94a3b8; }
.ps-split { margin-bottom: 14px; }
.ps-table { border: 1px solid #e2e8f0; }
.ps-table th { padding: 7px 10px; font-size: 8.5pt; }
.ps-earn { background-color: #f0fdf4; color: #166534; border-bottom: 2px solid #22c55e; }
.ps-ded { background-color: #fef2f2; color: #991b1b; border-bottom: 2px solid #ef4444; }
.ps-table td { padding: 5px 10px; font-size: 9pt; }
.ps-foot td { background-color: #f8fafc; border-top: 1px solid #e2e8f0; font-weight: bold; }
.ps-net { background-color: var(--ps-primary); color: #ffffff; margin-bottom: 14px; }
.ps-net td { padding: 12px 16px; }
.ps-net-title { font-size: 9pt; font-weight: bold; }
.ps-net-words { font-size: 8.5pt; font-style: italic; }
.ps-net-amount { font-size: 17pt; font-weight: bold; color: var(--ps-accent); }
.ps-footer { text-align: center; color: #94a3b8; font-size: 8pt; border-top: 1px solid #f1f5f9; padding-top: 8px; }"""

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
        "description": "Light layout with an emerald accent bar, four-column employee details and a teal net pay panel.",
        "html": _MODERN_EMERALD_HTML,
        "css": _MODERN_EMERALD_CSS,
        "configuration": {**DEFAULT_CONFIG, "primaryColor": "#0F766E", "accentColor": "#ECFDF5"},
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


def _render_body(fragment: str, context: dict) -> str:
    """Render a template fragment in the sandbox; 400 on any template error."""
    try:
        return _sandbox().from_string(fragment).render(**context)
    except SecurityError as exc:
        raise _bad_request(f"Template refused by the sandbox: {exc}")
    except jinja2.TemplateError as exc:
        raise _bad_request(f"Template could not be rendered: {exc}")
    except (TypeError, ValueError, ArithmeticError, AttributeError, KeyError) as exc:
        raise _bad_request(f"Template could not be rendered: {exc}")


def render_document(fragment: str, css: Optional[str], context: dict, watermark: bool = False) -> str:
    """Render a template fragment into a complete, self-contained HTML document."""
    body = _render_body(fragment, context)
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


# ── PDF (xhtml2pdf) ──────────────────────────────────────────────────────────
# xhtml2pdf supports a CSS 2.1 subset: the template's colour variables are
# substituted, its font-family is replaced by a Unicode TTF (the same files
# the reportlab payslip uses) so ₹ / Polish letters render, and it may load
# nothing but those font files and inline data: images — no URL, no file.

_PDF_FONT = "PayslipSans"
_CSS_VAR = re.compile(r"var\(\s*--ps-(primary|accent)\s*(?:,[^)]*)?\)")
_FONT_DECL = re.compile(r"font-family\s*:[^;}]*", re.IGNORECASE)


class PdfRenderError(Exception):
    """The PDF engine failed; callers fall back to the standard payslip PDF."""


def _font_files() -> Optional[Tuple[str, str]]:
    import os
    from app.modules.payroll import service as payroll_service
    for regular, bold in payroll_service.unicode_font_candidates():
        if os.path.isfile(regular):
            return regular, (bold if os.path.isfile(bold) else regular)
    return None


def _pdf_css(css: Optional[str], cfg: dict, has_font: bool) -> str:
    out = _CSS_VAR.sub(lambda m: cfg["primaryColor"] if m.group(1) == "primary" else cfg["accentColor"], css or "")
    if has_font:
        out = _FONT_DECL.sub(f"font-family: {_PDF_FONT}", out)
    return out.replace("</", "<\\/")


def _stamp_evaluation(pdf: bytes) -> bytes:
    """Overlay the same 'PREVIEW — EVALUATION ONLY' mark the standard PDF uses."""
    import io
    from pypdf import PdfReader, PdfWriter
    from reportlab.pdfgen import canvas
    from app.modules.payroll import service as payroll_service

    writer = PdfWriter()
    for page in PdfReader(io.BytesIO(pdf)).pages:
        width, height = float(page.mediabox.width), float(page.mediabox.height)
        buf = io.BytesIO()
        c = canvas.Canvas(buf, pagesize=(width, height))
        payroll_service._draw_evaluation_watermark(c, width, height)
        c.save()
        page.merge_page(PdfReader(io.BytesIO(buf.getvalue())).pages[0])
        writer.add_page(page)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()


def _pdf_resource_policy(fonts: Optional[Tuple[str, str]]):
    """No network at all; local reads confined to the font directory; bounded
    size, image pixels, element depth and render time."""
    from pathlib import Path
    from xhtml2pdf.config.resources import ResourceAccessPolicy

    font_dirs = sorted({str(Path(p).parent) for p in fonts}) if fonts else []
    return ResourceAccessPolicy(
        allow_remote=False,
        allow_private_networks=False,
        base_dir=Path(font_dirs[0]) if font_dirs else None,
        extra_roots=tuple(Path(d) for d in font_dirs[1:]),
        max_local_bytes=4_000_000,          # a 2 MB logo as a data: URI, or a font file
        max_image_pixels=25_000_000,
        max_resources=4,
        max_render_seconds=20,
        max_document_bytes=2_000_000,
        max_depth=64,
    )


def html_to_pdf(body_html: str, css: Optional[str], cfg: dict, watermark: bool = False) -> bytes:
    """A4 PDF of an already-rendered template body."""
    import io
    import os
    from xhtml2pdf import pisa

    fonts = _font_files()
    allowed = set()
    face = ""
    if fonts:
        regular, bold = (p.replace("\\", "/") for p in fonts)
        allowed = {os.path.normcase(os.path.normpath(p)) for p in fonts}
        face = (f'@font-face {{ font-family: {_PDF_FONT}; src: url("{regular}"); }} '
                f'@font-face {{ font-family: {_PDF_FONT}; src: url("{bold}"); font-weight: bold; }} '
                f'body {{ font-family: {_PDF_FONT}; }} ')
    document = (
        "<html><head><meta charset=\"utf-8\"><style>"
        "@page { size: A4; margin: 10mm; } " + face + _pdf_css(css, cfg, bool(fonts)) +
        f"</style></head><body>{body_html}</body></html>"
    )
    blocked = []

    def link_callback(uri, rel):
        if uri.startswith("data:"):
            return uri
        if os.path.normcase(os.path.normpath(uri)) in allowed:
            return uri
        blocked.append(uri)
        return ""          # nothing else is ever fetched or read

    buf = io.BytesIO()
    try:
        result = pisa.CreatePDF(src=document, dest=buf, encoding="utf-8", link_callback=link_callback,
                                resource_policy=_pdf_resource_policy(fonts))
    except Exception as exc:  # noqa: BLE001 — engine failure, never a payroll failure
        raise PdfRenderError(str(exc)) from exc
    if result.err or not buf.getvalue():
        raise PdfRenderError(f"PDF engine reported {result.err} error(s)")
    if blocked:
        logger.warning("Payslip template PDF: refused to load %d resource(s)", len(blocked))
    pdf = buf.getvalue()
    return _stamp_evaluation(pdf) if watermark else pdf


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


def org_countries(db: Session, organization_id: int) -> List[dict]:
    """The countries this organisation runs (or has run) payroll in — its
    default country first, then its entitled countries, REMOVED ones left
    out — the same rule the platform uses for country-specific setup
    (billing.jurisdiction_entitlement.org_payroll_countries). Read-only."""
    from app.modules.billing import jurisdiction_entitlement as entitlement
    from app.modules.billing.models import OrganizationJurisdiction

    codes = entitlement.org_payroll_countries(db, organization_id)
    statuses = dict(db.query(OrganizationJurisdiction.country_code, OrganizationJurisdiction.status).filter(
        OrganizationJurisdiction.organization_id == organization_id).all())
    return [{"code": code, "name": entitlement.country_name(code), "status": statuses.get(code, entitlement.ACTIVE)}
            for code in codes]


def _org_scope(db: Session, organization_id: int, country: Optional[str]) -> str:
    """ALL, or one of the organisation's own countries — never any other."""
    scope = _normalize_scope(country)
    if scope == ALL_COUNTRIES:
        return scope
    if scope not in {c["code"] for c in org_countries(db, organization_id)}:
        from app.modules.billing.jurisdiction_entitlement import country_name
        raise _bad_request(f"Your organisation doesn't run payroll in {country_name(scope)} ({scope}). "
                           "Choose one of its countries, or All countries.")
    return scope


def _sample_country(db: Optional[Session], organization_id: Optional[int], country: Optional[str]) -> str:
    """Country for sample-data previews: the requested one if the organisation
    has it, else its default country, else India."""
    codes = [c["code"] for c in org_countries(db, organization_id)] if db is not None and organization_id else []
    wanted = _normalize_scope(country) if country else None
    if wanted and wanted != ALL_COUNTRIES and (not codes or wanted in codes):
        return wanted
    return codes[0] if codes else "IN"


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
    countries = org_countries(db, organization_id)
    codes = {c["code"] for c in countries}
    return {
        "starters": list_starters(),
        "templates": [_template_dict(t, sorted(by_template.get(t.id, []))) for t in templates],
        # Only this organisation's own countries can be chosen; with one
        # country there is nothing to choose and the UI hides the picker.
        "countries": countries,
        "singleCountry": len(countries) <= 1,
        "assignments": [
            {"country": a.jurisdiction_country, "templateId": a.template_id,
             "templateName": a.template.name if a.template else None,
             "versionId": a.version_id,
             "versionNumber": a.version.version_number if a.version else None,
             # A country the organisation no longer runs payroll in: kept so
             # payslips already issued there keep their layout; can be removed.
             "countryInactive": a.jurisdiction_country != ALL_COUNTRIES and a.jurisdiction_country not in codes}
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
    country = _org_scope(db, organization_id, data.get("country"))
    country = None if country == ALL_COUNTRIES else country

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
        c = _org_scope(db, organization_id, data.get("country"))
        t.jurisdiction_country = None if c == ALL_COUNTRIES else c

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
    scope = _org_scope(db, organization_id, country)
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

def preview(html_content: str, css_content: Optional[str], config: Optional[dict], country: Optional[str],
            db: Optional[Session] = None, organization_id: Optional[int] = None) -> dict:
    fragment, css, warnings = validate_template(html_content, css_content)
    context = sample_context(_sample_country(db, organization_id, country), config)
    return {"renderedHtml": render_document(fragment, css, context), "warnings": warnings}


def preview_pdf(html_content: str, css_content: Optional[str], config: Optional[dict],
                country: Optional[str], db: Optional[Session] = None,
                organization_id: Optional[int] = None) -> bytes:
    """The template as a PDF with sample data — what a downloaded payslip will look like."""
    fragment, css, _warnings = validate_template(html_content, css_content)
    context = sample_context(_sample_country(db, organization_id, country), config)
    try:
        return html_to_pdf(_render_body(fragment, context), css, context["config"])
    except PdfRenderError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY,
                            detail=f"This template could not be turned into a PDF: {exc}")


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


def _payslip_template(db: Session, organization_id: int, payslip_id: int):
    """(item, version, frozen, context) for a payslip shown through a template:
    its frozen version, or (before its run is approved) the org's current
    assignment. 404 TEMPLATE_NOT_ASSIGNED / 409 TEMPLATE_NOT_REPRESENTABLE mean
    the standard statutory payslip is used instead."""
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
    return item, version, frozen, context


def render_payslip(db: Session, organization_id: int, payslip_id: int) -> dict:
    """The payslip rendered through its template, for the on-screen view."""
    from app.modules.payroll import service as payroll_service

    item, version, frozen, context = _payslip_template(db, organization_id, payslip_id)
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


def render_payslip_pdf(db: Session, organization_id: int, payslip_id: int) -> bytes:
    """The payslip as a PDF in its template's layout (same rules as render_payslip)."""
    from app.modules.payroll import service as payroll_service

    _item, version, _frozen, context = _payslip_template(db, organization_id, payslip_id)
    watermark = payroll_service._is_evaluation_workspace(db, organization_id)
    body = _render_body(version.html_content, context)
    return html_to_pdf(body, version.css_content, context["config"], watermark=watermark)


def template_pdf_or_none(db: Session, payslip_id: int, organization_id: Optional[int]) -> Optional[bytes]:
    """For service.generate_payslip_pdf_bytes: the template PDF, or None to use
    the standard PDF. Never raises — a template problem must not stop a payslip
    being downloaded or emailed — and runs in a savepoint so a failed query
    cannot poison the caller's transaction."""
    try:
        with db.begin_nested():
            query = db.query(PayslipItem.organization_id).filter(PayslipItem.id == payslip_id)
            if organization_id is not None:
                query = query.filter(PayslipItem.organization_id == organization_id)
            row = query.first()
            if row is None:
                return None
            return render_payslip_pdf(db, row[0], payslip_id)
    except HTTPException as exc:
        if exc.status_code not in (status.HTTP_404_NOT_FOUND, status.HTTP_409_CONFLICT):
            logger.warning("Payslip %s: template PDF unavailable (%s); using the standard PDF",
                           payslip_id, exc.detail)
        return None
    except Exception:  # noqa: BLE001
        logger.exception("Payslip %s: template PDF failed; using the standard PDF", payslip_id)
        return None


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
