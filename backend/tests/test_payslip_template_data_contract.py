"""
tests/test_payslip_template_data_contract.py
--------------------------------------------
Payslip-template data contract (exact-layout work, P1):

  * service.payslip_line_items is unchanged (pinned to a frozen copy of the
    pre-refactor function for every country) — the standard PDF is untouched;
  * every line has a stable code; earnings_by_code / deductions_by_code and
    the 'any other' buckets always add up to the stored gross / deductions;
  * entitled = the stored (full-month) amount; employer EPF, CTC, net paid,
    payment mode, IFSC, PAN and month days are outside the tie-out;
  * a code a payslip doesn't have renders blank, never an error;
  * the new placeholders validate; unknown ones are still refused.
"""
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.organizations.models import Organization
from app.modules.payroll import payslip_template_service as tpl
from app.modules.payroll import service
from app.modules.payroll.models import PayrollEmployee, PayrollRun, PayslipItem

from tests import _legacy_payslip_line_items as legacy


# ── payslip_line_items unchanged ─────────────────────────────────────────────

_FULL = {
    "basicPay": 50000, "hra": 20000, "specialAllowance": 12000, "overtime": 1500, "additionalCompensation": 2500,
    "allowanceItems": [{"key": "transport", "label": "Transport", "amount": 1600},
                       {"key": "Medical Aid", "label": "Medical", "amount": 500}],
    "attendanceDeduction": 900, "unpaidLeaveDays": 1, "tds": 6200, "pf": 6000, "esi": 300, "professionalTax": 200,
    "federalIncomeTax": 400, "stateIncomeTax": 100, "localTax": 50, "soli": 30, "churchTax": 40,
    "socialSecurity": 70, "medicare": 20, "niEmployee": 33, "employeePension": 44, "studyLoanDeduction": 5,
    "postgradLoanDeduction": 6, "stateDisabilityInsurance": 7, "stateProgramDeductions": 8,
    "myCalculationSnapshot": {"my_epf": {"employee": 11}, "my_socso": {"employee": 2}, "my_eis": {"employee": 1}},
    "plCalculationSnapshot": {"pl_zus_employee": {"EMERYTALNE": 9, "RENTOWE": 4, "X": 1}, "pl_health": 3,
                              "pl_ppk_employee": {"a": 2}},
}
_SPARSE = {**_FULL, "overtime": 0, "additionalCompensation": 0, "soli": 0, "federalIncomeTax": 0,
           "stateIncomeTax": 0, "localTax": 0, "unpaidLeaveDays": 2.5, "allowanceItems": [], "esi": 0}
_SIMPLE = {"basicPay": 50000, "hra": 20000, "specialAllowance": 10000, "attendanceDeduction": 0}
_COUNTRIES = ["IN", "US", "UK", "DE", "CA", "AU", "HK", "SG", "TT", "BB", "DO", "JM", "MY", "PL", "FR", "IE", "XX"]


@pytest.mark.parametrize("country", _COUNTRIES)
@pytest.mark.parametrize("data", [_FULL, _SPARSE, _SIMPLE], ids=["full", "sparse", "simple"])
def test_payslip_line_items_identical_to_pre_refactor(country, data):
    assert service.payslip_line_items(dict(data), country) == legacy.payslip_line_items(dict(data), country)


@pytest.mark.parametrize("country", _COUNTRIES)
def test_coded_lines_are_the_same_lines_with_a_code(country):
    earnings, deductions = service.payslip_line_items_coded(dict(_FULL), country)
    plain_e, plain_d = legacy.payslip_line_items(dict(_FULL), country)
    assert [(l, a) for _c, l, a in earnings] == plain_e
    assert [(l, a) for _c, l, a in deductions] == plain_d
    for code, _l, _a in earnings + deductions:
        assert code and all(ch.isalnum() or ch == "_" for ch in code), code


def test_in_line_codes():
    earnings, deductions = service.payslip_line_items_coded(dict(_FULL), "IN")
    assert [c for c, _l, _a in earnings] == ["basic", "hra", "allowance_transport", "allowance_medical_aid",
                                            "special", "overtime", "additional_compensation"]
    assert [c for c, _l, _a in deductions][:5] == ["lop", "tds", "pf", "esi", "professional_tax"]


# ── helpers ──────────────────────────────────────────────────────────────────

def _org(db, code):
    org = Organization(organization_name=f"Org {code}", organization_code=code, country="IN")
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _payslip(db, org, *, ctc=Decimal("1200000"), employer_pf=Decimal("1800"), lop=None):
    emp = PayrollEmployee(organization_id=org.id, employee_code=f"E-{org.id}", name="Asha Rao",
                          country_code="IN", ctc=ctc, pan="ABCDE1234F", ifsc="HDFC0000123")
    db.add(emp)
    run = PayrollRun(organization_id=org.id, run_code=f"RUN-{org.id}", period_label="June 2026",
                     pay_date=date(2026, 6, 30), period_start=date(2026, 6, 1),
                     period_end=date(2026, 6, 30), status="Draft")
    db.add(run)
    db.flush()
    lop = lop or Decimal("0")
    item = PayslipItem(
        organization_id=org.id, payroll_run_id=run.id, employee_id=emp.id, employee_name="Asha Rao",
        country_code="IN", basic_salary=Decimal("50000"), hra=Decimal("20000"),
        special_allowance=Decimal("10000"), gross_pay=Decimal("80000"),
        tds=Decimal("5000"), pf=Decimal("1800"), professional_tax=Decimal("200"),
        attendance_deduction=lop, unpaid_leave_days=1 if lop else None,
        total_deductions=Decimal("7000") + lop, net_pay=Decimal("73000") - lop,
        employer_pf=employer_pf, pan="ABCDE1234F", ifsc="HDFC0000123", total_working_days=30,
        status="Pending",
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


def _sum(lines):
    return sum(Decimal(str(line["amount"])) for line in lines)


# ── context: codes, keyed views, buckets, tie-out ────────────────────────────

def test_context_lines_have_code_and_entitled(db):
    org = _org(db, "DC_A")
    item = _payslip(db, org)
    ctx, _item = tpl.build_payslip_context(db, org.id, item.id)
    by = ctx["earnings_by_code"]
    assert set(by) >= {"basic", "hra", "special"}
    assert by["basic"]["entitled"] == by["basic"]["amount"] == 50000.0
    assert by["basic"]["entitled_formatted"] == "₹ 50,000.00"
    assert ctx["deductions_by_code"]["tds"]["amount"] == 5000.0
    for line in ctx["earnings"] + ctx["deductions"]:
        assert line["code"] and line["entitled"] == line["amount"]


def test_buckets_and_keyed_views_tie_out_to_stored_totals(db):
    org = _org(db, "DC_B")
    item = _payslip(db, org, lop=Decimal("2666.67"))
    cfg = {"fields": {"basic": {"include": True, "side": "earnings", "code": "basic"},
                      "hra": {"include": True, "side": "earnings", "code": "hra"},
                      "tds": {"include": True, "side": "deductions", "code": "tds"},
                      "epf": {"include": True, "side": "deductions", "code": "pf"}}}
    ctx, _item = tpl.build_payslip_context(db, org.id, item.id)
    ctx = {**ctx, **tpl._line_views("₹", ctx["earnings"], ctx["deductions"], cfg)}
    gross, ded = Decimal(str(ctx["totals"]["gross_pay"])), Decimal(str(ctx["totals"]["total_deductions"]))
    placed_e = sum(Decimal(str(ctx["earnings_by_code"][c]["amount"])) for c in ("basic", "hra"))
    placed_d = sum(Decimal(str(ctx["deductions_by_code"][c]["amount"])) for c in ("tds", "pf"))
    assert placed_e + Decimal(str(ctx["other_earnings"]["amount"])) == gross
    assert placed_d + Decimal(str(ctx["other_deductions"]["amount"])) == ded
    # LOP has no row of its own -> it is in 'Any other'.
    assert any(label.startswith("LOP Deduction") for label in ctx["other_deductions"]["labels"])
    assert _sum(ctx["earnings"]) == gross and _sum(ctx["deductions"]) == ded


def test_without_field_settings_every_line_is_in_the_bucket(db):
    org = _org(db, "DC_C")
    item = _payslip(db, org)
    ctx, _item = tpl.build_payslip_context(db, org.id, item.id)
    assert Decimal(str(ctx["other_earnings"]["amount"])) == Decimal("80000")
    assert Decimal(str(ctx["other_deductions"]["amount"])) == Decimal("7000")


def test_values_outside_the_tie_out(db):
    org = _org(db, "DC_D")
    item = _payslip(db, org)
    ctx, _item = tpl.build_payslip_context(db, org.id, item.id)
    assert ctx["employer"]["epf"]["paid_formatted"] == "₹ 1,800.00"
    assert ctx["totals"]["ctc"]["entitled"] == 100000.0          # 1,200,000 / 12
    assert ctx["totals"]["ctc"]["paid_formatted"] == "₹ 100,000.00"
    assert ctx["totals"]["net_paid"] == ctx["totals"]["net_pay_formatted"]
    assert ctx["payment"]["mode"] == "NEFT"
    assert ctx["employee"]["ifsc"] == "HDFC0000123" and ctx["employee"]["pan"] == "ABCDE1234F"
    assert ctx["payroll"]["month_days"] == 30
    # None of them changes the totals.
    assert ctx["totals"]["gross_pay"] == 80000.0 and ctx["totals"]["total_deductions"] == 7000.0


def test_missing_ctc_and_employer_pf_render_blank(db):
    org = _org(db, "DC_E")
    item = _payslip(db, org, ctc=None, employer_pf=Decimal("0"))
    ctx, _item = tpl.build_payslip_context(db, org.id, item.id)
    assert ctx["totals"]["ctc"] is None and ctx["employer"]["epf"] is None
    html = tpl._render_body(
        "[{{ totals.ctc.paid_formatted }}][{{ employer.epf.paid_formatted or '-' }}]"
        "[{{ earnings_by_code.bonus.amount_formatted or '-' }}][{{ deductions_by_code.advance.amount_formatted }}]"
        "{{ employee.name }}{{ totals.net_pay_formatted }}{% for e in earnings %}{% endfor %}"
        "{% for d in deductions %}{% endfor %}", ctx)
    assert html.startswith("[][-][-][]")


# ── placeholders ─────────────────────────────────────────────────────────────

_NEW = ("{{ earnings_by_code.basic.entitled_formatted }}{{ earnings_by_code.allowance_conveyance.amount_formatted }}"
        "{{ deductions_by_code.tds.amount_formatted }}{{ other_earnings.amount_formatted }}"
        "{{ other_deductions.amount_formatted }}{% for l in other_deductions.labels %}{{ l }}{% endfor %}"
        "{{ employer.epf.entitled_formatted }}{{ employer.epf.paid_formatted }}"
        "{{ totals.ctc.entitled_formatted }}{{ totals.ctc.paid_formatted }}{{ totals.net_paid }}"
        "{{ payment.mode }}{{ employee.ifsc }}{{ employee.pan }}{{ payroll.month_days }}"
        "{% for e in earnings %}{{ e.code }}{{ e.entitled_formatted }}{% endfor %}"
        "{{ employee.name }}{{ totals.net_pay_formatted }}{% for d in deductions %}{% endfor %}")


def test_new_placeholders_validate_and_preview():
    _fragment, _css, warnings = tpl.validate_template(_NEW, "")
    assert warnings == []
    html = tpl.preview(_NEW, "", None, "IN")["renderedHtml"]
    assert "₹ 1,600.00" in html and "NEFT" in html and "EXMP0001234" in html


@pytest.mark.parametrize("bad", ["{{ earnings_by_code.Basic.amount }}", "{{ earnings_by_code.basic.amout }}",
                                 "{{ employer.esi.paid }}", "{{ totals.ctc.total }}", "{{ payment.bank }}"])
def test_unknown_new_placeholders_are_refused(bad):
    with pytest.raises(HTTPException) as exc:
        tpl.validate_template(bad, "")
    assert exc.value.status_code == 400


def test_sample_totals_unchanged():
    ctx = tpl.sample_context("IN")
    assert ctx["totals"]["gross_pay"] == 82000 and ctx["totals"]["total_deductions"] == 12400
    assert ctx["totals"]["net_pay"] == 69600
    assert ctx["earnings_by_code"]["additional_compensation"]["label"] == "Bonus"


# ── P2: field catalogue + include / exclude ──────────────────────────────────

def test_fields_default_from_catalogue_and_required_forced_on():
    fields = tpl.normalize_fields({"name": {"include": False}, "net_paid": {"include": False},
                                   "other_deductions": {"include": False}, "pan": {"include": False},
                                   "not_a_field": {"include": True}})
    assert set(fields) == {f["key"] for f in tpl.FIELD_CATALOGUE}
    assert fields["name"]["include"] and fields["net_paid"]["include"] and fields["other_deductions"]["include"]
    assert fields["pan"]["include"] is False
    assert fields["company_address"]["include"] is False          # default off
    assert fields["conveyance"] == {"include": True, "label": "Conv. Allowance",
                                    "code": "allowance_conveyance", "side": "earnings"}


def test_field_labels_are_cleaned_and_codes_checked():
    fields = tpl.normalize_fields({"pan": {"label": "<b>PAN</b> {{x}} \"no\""}, "conveyance": {"code": "allowance_transport"}})
    assert fields["pan"]["label"] == "bPAN/b x no"
    assert fields["conveyance"]["code"] == "allowance_transport"
    with pytest.raises(HTTPException):
        tpl.normalize_fields({"conveyance": {"code": "x.y"}})
    with pytest.raises(HTTPException):
        tpl.normalize_fields(["pan"])


def test_config_without_fields_normalises_exactly_as_before():
    for starter in tpl.STARTERS.values():
        assert tpl.normalize_config(starter["configuration"]) == {**tpl.DEFAULT_CONFIG, **starter["configuration"]}
    assert "fields" not in tpl.normalize_config({"primaryColor": "#123456"})


def test_show_employee_bank_turns_bank_fields_off():
    cfg = tpl.normalize_config({"showEmployeeBank": False, "fields": {}})
    resolved = tpl.resolved_fields(cfg)
    assert not resolved["bank_account"]["include"] and not resolved["ifsc"]["include"]
    assert resolved["payment_mode"]["include"]
    assert tpl.resolved_fields(tpl.normalize_config({"showNetInWords": False}))["net_in_words"]["include"] is False


_GRID = (
    "<table>"
    "{% if config.fields.employee_id.include or config.fields.date_of_joining.include %}<tr class='r1'>"
    "<td>{% if config.fields.employee_id.include %}{{ config.fields.employee_id.label }}{% endif %}</td>"
    "<td>{% if config.fields.employee_id.include %}{{ employee.id }}{% endif %}</td>"
    "<td>{% if config.fields.date_of_joining.include %}{{ config.fields.date_of_joining.label }}{% endif %}</td>"
    "<td>{% if config.fields.date_of_joining.include %}{{ employee.date_of_joining }}{% endif %}</td>"
    "</tr>{% endif %}"
    "<tr><td>{{ config.fields.name.label }}</td><td>{{ employee.name }}</td></tr>"
    "{% if config.fields.basic.include %}<tr><td>{{ config.fields.basic.label }}</td>"
    "<td>{{ earnings_by_code[config.fields.basic.code].amount_formatted or '-' }}</td></tr>{% endif %}"
    "{% if other_earnings.count %}<tr><td>{{ config.fields.other_earnings.label }}</td>"
    "<td>{{ other_earnings.amount_formatted }}</td></tr>{% endif %}"
    "<tr><td>{{ config.fields.tds.label }}</td><td>{{ deductions_by_code[config.fields.tds.code].amount_formatted or '-' }}</td></tr>"
    "<tr><td>{{ config.fields.other_deductions.label }}</td><td>{{ other_deductions.amount_formatted }}</td></tr>"
    "<tr><td>{{ config.fields.net_paid.label }}</td><td>{{ totals.net_pay_formatted }}</td></tr>"
    "</table>"
)


def _grid(fields):
    return tpl.preview(_GRID, "", {"fields": fields}, "IN")["renderedHtml"]


def test_field_template_validates_without_warnings():
    assert tpl.validate_template(_GRID, "")[2] == []
    assert tpl.missing_required(_GRID) == []


def test_excluded_field_blanks_its_cells_and_row_goes_when_all_excluded():
    html = _grid({"employee_id": {"include": False}})
    assert "class='r1'" in html.replace('"', "'") and "Employee ID" not in html and "DOJ" in html
    html = _grid({"employee_id": {"include": False}, "date_of_joining": {"include": False}})
    assert "r1" not in html


def test_relabel_and_excluded_line_moves_to_any_other():
    html = _grid({"name": {"label": "Employee Name"}, "basic": {"include": False}})
    assert "Employee Name" in html and "Basic Salary" not in html
    # Basic (50,000) now has no row: it is the only line in Other Earnings
    # (HRA / Conveyance / Special / Bonus keep their default rows); Any other
    # holds Professional Tax (TDS and EPF have rows).
    assert "Other Earnings</td><td>₹ 50,000.00" in html
    assert "Any other</td><td>₹ 200.00" in html


def test_publish_accepts_keyed_lines_plus_any_other_and_refuses_without(db):
    org = _org(db, "DC_PUB")
    ok = tpl.create_template(db, org.id, None, {"name": "Grid", "htmlContent": _GRID, "configurationJson": {"fields": {}}})
    assert tpl.publish_template(db, org.id, ok["id"], None)["activeVersion"]
    bad_html = _GRID.replace("{{ other_deductions.amount_formatted }}", "")
    bad = tpl.create_template(db, org.id, None, {"name": "Grid 2", "htmlContent": bad_html})
    assert any("deduction" in w for w in bad["warnings"])
    with pytest.raises(HTTPException) as exc:
        tpl.publish_template(db, org.id, bad["id"], None)
    assert exc.value.status_code == 409


@pytest.mark.parametrize("bad", ["{{ config.fields.salary.include }}", "{{ config.fields.basic.includ }}"])
def test_unknown_field_placeholders_refused(bad):
    with pytest.raises(HTTPException):
        tpl.validate_template(bad, "")


def test_list_returns_field_catalogue(db):
    org = _org(db, "DC_LIST")
    cat = tpl.list_templates(db, org.id)["fieldCatalogue"]
    assert {c["key"] for c in cat} == {f["key"] for f in tpl.FIELD_CATALOGUE}
    assert all("value" not in c for c in cat)
