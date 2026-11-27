"""Frozen copy of service.payslip_line_items (and its helpers) as it was
before line codes were added (2026-11-27). test_payslip_template_data_contract
pins the refactored function to it: same lines, labels, amounts, order.
Never edit this file to make a test pass."""
# flake8: noqa


def payslip_line_items(data: dict, country: str):
    """The employee-facing earnings and deduction lines of a payslip, as the
    PDF prints them: ([(label, amount)], [(label, amount)]). Shared by the PDF
    and the payslip-template renderer so both always show the same lines.
    May add the derived 'lohnsteuerOnly' key to ``data`` (Germany)."""
    # ── Build earnings & deduction items (pre-computed for layout) ──
    earnings_items = [
        ("Basic Salary", data["basicPay"]),
        ("Housing Allowance" if country == "HK" else "House Rent Allowance (HRA)", data["hra"]),
    ]
    # Named allowance components (Transport/Medical/Other/...), if this org
    # has any configured — shown as their own line items, same as Overtime/
    # Additional Compensation below. Special Allowance stays the final
    # catch-all, listed after these named slices.
    for allowance in data.get("allowanceItems") or []:
        earnings_items.append((allowance["label"], allowance["amount"]))
    earnings_items.append(("Special Allowance", data["specialAllowance"]))
    ov = float(data.get("overtime", 0) or 0)
    if ov > 0:
        earnings_items.append(("Overtime", ov))
    add_comp = float(data.get("additionalCompensation", 0) or 0)
    if add_comp > 0:
        # Singapore: this is exactly the CPF Additional Wages figure the
        # engine used (engine/countries/singapore.py — OW = gross − AW).
        earnings_items.append(("Additional Wages (AW)" if country == "SG" else "Additional Compensation", add_comp))

    deduction_items = []
    attendance_ded = float(data.get("attendanceDeduction", 0) or 0)
    if attendance_ded > 0:
        unpaid_days = data.get("unpaidLeaveDays")
        lbl = "No-pay Leave Deduction" if country == "HK" else "LOP Deduction"
        if unpaid_days:
            lbl += f" ({float(unpaid_days):g} day{'s' if float(unpaid_days) != 1 else ''})"
        deduction_items.append((lbl, attendance_ded))
    # Every jurisdiction routes its income-tax withholding through the same
    # `tds` field (India-named historically) — label it with each
    # jurisdiction's own plain term (not a generic "Income Tax" gloss) so a
    # German/UK/Australian/etc. payslip reads the way that country's own
    # payslips actually do.
    income_tax_labels = {
        "IN": "TDS", "US": "Federal Withholding", "UK": "PAYE",
        "AU": "PAYG", "DE": "Lohnsteuer", "CA": "Federal Tax",
        # Ireland (ZP-IE-ENG-001) routes PAYE through `tds`; without this row
        # an Irish payslip read the "TDS" default, which is India's term.
        "IE": "PAYE", "FR": "Prélèvement à la Source",
        # Caribbean production jurisdictions (ZP-MJR-2026-002, 2026-09-24) —
        # real terms verified from each country's own engine module
        # docstring (engine/countries/*.py), not guessed. Bahamas/Cayman
        # deliberately have no entry here: `tds` is always Decimal("0") for
        # both (no personal income tax — see bahamas.py/cayman_islands.py's
        # own module docstrings), so the existing `if v > 0` filter below
        # already omits the line correctly; adding a label would risk it
        # being read as "this country's income tax happened to be zero".
        "BB": "PAYE", "DO": "ISR", "GY": "PAYE", "JM": "PAYE", "TT": "PAYE",
        "PR": "Hacienda Withholding",
        # Poland / Malaysia route the monthly income-tax advance through `tds`
        # (engine/countries/poland.py, malaysia.py): PIT advance / PCB (MTD).
        "PL": "PIT Advance (zaliczka)", "MY": "PCB / MTD",
    }
    # US: federal/state/local are stored (and shown here) as three separate
    # lines instead of one combined "Federal Withholding" figure — `tds`
    # remains the correct combined total, only used here as a fallback for
    # a payslip generated before this split existed (all three would be
    # exactly 0 in that case, never partially populated), so an old US
    # payslip's PDF is unaffected. Same fallback rule as
    # jurisdictionLabels.js's getIncomeTaxLines on the frontend.
    us_split_total = float(data.get("federalIncomeTax", 0) or 0) + float(data.get("stateIncomeTax", 0) or 0) + float(data.get("localTax", 0) or 0)
    if country == "US" and us_split_total > 0:
        income_tax_line_items = [
            ("Federal Withholding", "federalIncomeTax"),
            ("State Tax", "stateIncomeTax"),
            ("Local Tax", "localTax"),
        ]
    elif country == "DE" and float(data.get("soli", 0) or 0) > 0:
        # Phase 8BR: `tds` for Germany is (Lohnsteuer + Soli)/12 combined
        # (engine/countries/germany.py's monthly_lohnsteuer_soli) — shown
        # here as two separate lines (Lohnsteuer alone, then Soli) so the
        # PDF doesn't mislabel the combined figure as pure Lohnsteuer.
        # `data["lohnsteuerOnly"]` is computed just below; falls back to
        # the old combined-under-"Lohnsteuer" behavior if soli is 0.
        data["lohnsteuerOnly"] = float(data.get("tds", 0) or 0) - float(data.get("soli", 0) or 0)
        income_tax_line_items = [
            ("Lohnsteuer", "lohnsteuerOnly"),
            ("Solidaritätszuschlag (Soli)", "soli"),
        ]
    else:
        income_tax_line_items = [(income_tax_labels.get(country, "TDS"), "tds")]
    pf_esi_labels = {
        "DE": {"pf": "Pension Insurance", "esi": "Social Insurance (Health / Unemployment / Care)"},
        "CA": {"esi": "Employment Insurance (EI)"},
    }.get(country, {})
    # Trinidad reuses the `professional_tax` field for its Health Surcharge
    # (see trinidad_and_tobago.py's own comment on that field) — it was
    # previously shown under the literal "Professional Tax" for every
    # country, mislabeling Trinidad's deduction with an India-specific term.
    # Singapore reuses professional_tax for its Self-Help Group deduction
    # (CDAC/ECF/MBMF/SINDA) — see engine/countries/singapore.py.
    professional_tax_label = {"TT": "Health Surcharge", "SG": "SHG Contribution"}.get(country, "Professional Tax")
    for lbl, key in [
        *income_tax_line_items,
        (pf_esi_labels.get("pf", "Provident Fund (PF)"), "pf"),
        (pf_esi_labels.get("esi", "Employee State Insurance (ESI)"), "esi"),
        (professional_tax_label, "professionalTax"),
    ]:
        v = float(data.get(key, 0) or 0)
        if v > 0:
            deduction_items.append((lbl, v))
    # Germany: Kirchensteuer (church tax) is a statutory deduction from the
    # employee's pay when de_church_tax_liable is set — persisted in
    # PayslipItem.church_tax and populated by the engine. Only shown when
    # the value is actually nonzero.
    if country == "DE":
        # Key is the serializer's camelCase "churchTax" (emitted by
        # _serialize_payslip) — the previous snake_case key never existed
        # in the data dict, so this branch was dead and Kirchensteuer
        # never appeared on a German PDF.
        church_tax_val = float(data.get("churchTax", 0) or 0)
        if church_tax_val > 0:
            deduction_items.append(("Kirchensteuer", church_tax_val))
    other_labels = {
        "CA": {"socialSecurity": "Canada Pension Plan (CPP)"},
        "AU": {"medicare": "Medicare Levy"},
        # Caribbean production jurisdictions (ZP-MJR-2026-002, 2026-09-24) —
        # real terms verified from each country's own engine module
        # docstring. `employeePension` and `niEmployee` are both reused/
        # repurposed fields in these countries, NOT a literal pension or UK
        # National Insurance — see barbados.py/dominican_republic.py/
        # jamaica.py's own comments on those fields.
        "BB": {"socialSecurity": "NIS", "employeePension": "Reserve & Retraining (R&R) Levy"},
        "DO": {"socialSecurity": "SFS (Seguro Familiar de Salud)", "employeePension": "Pension (SVDS)"},
        "GY": {"socialSecurity": "NIS"},
        "JM": {"socialSecurity": "NIS", "employeePension": "National Housing Trust (NHT)", "niEmployee": "Education Tax"},
        "TT": {"socialSecurity": "NIS"},
        "BS": {"socialSecurity": "NIB"},
        "KY": {"socialSecurity": "NIB Pension"},
        # Singapore reuses employee_pension for employee CPF.
        "SG": {"employeePension": "CPF (Employee)"},
        # Hong Kong: MPF employee mandatory contribution — never an income
        # tax line (no `tds` is ever set for HK).
        "HK": {"employeePension": "MPF Mandatory Contribution (Employee)"},
    }.get(country, {})
    for lbl, key in [
        (other_labels.get("socialSecurity", "Social Security"), "socialSecurity"),
        (other_labels.get("medicare", "Medicare"), "medicare"),
        (other_labels.get("niEmployee", "National Insurance"), "niEmployee"),
        # UK: Workplace Pension (employee side) and Student/Postgraduate
        # Loan — both correctly computed/persisted but previously invisible
        # on every UK payslip PDF (see _serialize_payslip's own fix note).
        (other_labels.get("employeePension", "Workplace Pension"), "employeePension"),
        ("Student Loan Deduction", "studyLoanDeduction"),
        ("Postgraduate Loan Deduction", "postgradLoanDeduction"),
    ]:
        v = float(data.get(key, 0) or 0)
        if v > 0:
            deduction_items.append((lbl, v))
    # US: State Disability Insurance / other state payroll-program employee
    # deductions (CA SDI, NY/NJ/RI TDI, CT/MA/WA/CO/OR/etc. paid-leave
    # employee share) — computed and persisted but never shown on the PDF
    # before this fix (found 2026-09-15 Org Admin visibility audit).
    if country == "US":
        for lbl, key in [
            ("State Disability Insurance", "stateDisabilityInsurance"),
            ("State Payroll Programs (e.g. Paid Leave/TDI)", "stateProgramDeductions"),
        ]:
            v = float(data.get(key, 0) or 0)
            if v > 0:
                deduction_items.append((lbl, v))
    # Poland / Malaysia: the employee social contributions travel in the
    # frozen calculation snapshot (pl_employee_total / my_employee_total), not
    # in the generic pf / esi / pension fields — itemise them from it, so the
    # lines add up to the stored total deductions (PCB / PIT is the tds line).
    deduction_items.extend(_snapshot_deduction_lines(data, country))
    # Employer-side contributions (Employer PF/ESI/Social Security/Medicare/
    # Pension/NI) are deliberately NOT shown here — this is the employee's
    # own payslip, and none of these are amounts deducted from the
    # employee's pay. They were previously mixed into this same
    # "Deductions" list (mislabeled, since they're the employer's own
    # cost, not the employee's) — removed at Venu's request. They remain
    # visible to admins on the Payroll Register / Run Detail views, which
    # are internal cost-review screens, not the payslip document itself.
    return earnings_items, deduction_items


_PL_ZUS_EMPLOYEE_LABELS = {"EMERYTALNE": "ZUS Pension (emerytalne)", "RENTOWE": "ZUS Disability (rentowe)",
                           "CHOROBOWE": "ZUS Sickness (chorobowe)"}


def _snapshot_deduction_lines(data: dict, country: str) -> list:
    """[(label, amount)] of the employee contributions a Poland / Malaysia
    payslip keeps in its frozen snapshot (zero lines omitted). Read as stored —
    never recomputed. Empty for every other country or without a snapshot."""
    def amount(value) -> float:
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    lines = []
    if country == "MY":
        snap = data.get("myCalculationSnapshot") or {}
        for label, key in (("EPF (Employee)", "my_epf"), ("SOCSO (Employee)", "my_socso"),
                           ("EIS (Employee)", "my_eis")):
            lines.append((label, amount((snap.get(key) or {}).get("employee"))))
    elif country == "PL":
        snap = data.get("plCalculationSnapshot") or {}
        for key, value in sorted((snap.get("pl_zus_employee") or {}).items()):
            lines.append((_PL_ZUS_EMPLOYEE_LABELS.get(str(key).upper(), f"ZUS ({key})"), amount(value)))
        lines.append(("Health contribution (zdrowotna)", amount(snap.get("pl_health"))))
        lines.append(("PPK (Employee)", sum(amount(v) for v in (snap.get("pl_ppk_employee") or {}).values())))
    return [(label, value) for label, value in lines if value > 0]
