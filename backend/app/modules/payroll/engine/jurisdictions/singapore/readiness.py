"""
engine/jurisdictions/singapore/readiness.py
-------------------------------------------
Employer Registration readiness — ZP-SG-ENG-001 §9 panel H and SG-027:
"Employer setup must not reach LIVE until CSN/CPF process is validated, AIS
mode is explicitly set, SDL payment route exists, foreign-workforce/PWM
applicability is determined, bank workflow is proven and PDPA controls are
approved." SG-028: where the official process is a file upload through CPF
EZPay, the file is generated and the customer submits it through Corppass —
no direct API is claimed.

Pure: `evaluate_employer_readiness(facts)` takes the facts service.py
gathered and returns the checklist. Statuses:
  PASS     - evidenced in Zoiko.
  FAIL     - a configuration the employer must fix.
  REVIEW   - set, but inconsistent with payroll data or needs a human decision.
  BLOCKED  - depends on an external party / evidence Zoiko cannot produce.
LIVE_READY only when every item is PASS.

Rule sources (hashed retrievals, see seed_singapore_canonical_pack.SOURCES):
  - CSN = UEN/NRIC/FIN + Payment Type + Sno — CPF Board "CPF EZPay (FTP)
    File Specifications" (effective 16 Jan 2025), page 1.
  - AIS mandatory for employers with 5 or more employees — IRAS "Join the
    Auto-Inclusion Scheme (AIS) for Employment Income".
  - SDL payable through the CPF submission (payment code 11) — EZPay spec p3.
"""

import re

PASS, FAIL, REVIEW, BLOCKED = "PASS", "FAIL", "REVIEW", "BLOCKED"
_CSN = re.compile(r"^([A-Z0-9]{9,10})([A-Z]{3})(\d{2})$")
MANDATORY_CPF_PAYMENT_TYPES = ("PTE",)          # voluntary CSNs (AMS/VCT/MSE) cannot carry SDL/SHG (EZPay spec p3)


def parse_csn(value):
    """(uen, payment_type, sno) or None — hyphens tolerated."""
    if not value:
        return None
    m = _CSN.match(str(value).replace("-", "").strip().upper())
    return m.groups() if m else None


def _item(key, panel, label, status, evidence, blocker=None, owner="Employer payroll administrator", action=None):
    return {"key": key, "panel": panel, "label": label, "status": status, "evidence": evidence,
            "blocker": blocker if status != PASS else None, "owner": owner,
            "action": action if status != PASS else None}


def evaluate_employer_readiness(facts: dict) -> dict:
    """facts keys: identifiers (tax_identifiers dict), company_name,
    company_address, settlement_bank, settlement_acc, employee_count,
    foreign_pass_holders, work_permit_holders, work_permit_sectors (set),
    pwm_flagged_employees, active_pack (str | None), ais_threshold (Decimal |
    None), ezpay_accepted (bool), ezpay_generated (bool)."""
    ids = facts.get("identifiers") or {}
    items = []

    # A. Legal employer
    uen = ids.get("uen")
    items.append(_item("legal_employer", "A", "Legal employer (UEN, name, address)",
                       PASS if uen and facts.get("company_name") and facts.get("company_address") else FAIL,
                       f"UEN {uen or 'missing'}; name {'set' if facts.get('company_name') else 'missing'}; "
                       f"address {'set' if facts.get('company_address') else 'missing'}",
                       blocker="UEN, legal name and registered address are required",
                       action="Complete Company Details and the Singapore UEN"))

    # B. CPF Board
    csn = parse_csn(ids.get("cpf_submission_number"))
    if csn is None:
        items.append(_item("cpf_csn", "B", "CPF Submission Number (CSN)", FAIL, "CSN missing or not UEN + payment type + Sno",
                           blocker="No valid CSN — the CPF EZPay file cannot be produced",
                           action="Enter the CSN issued by CPF Board (e.g. 201912345KPTE01)"))
    elif uen and csn[0] != uen:
        items.append(_item("cpf_csn", "B", "CPF Submission Number (CSN)", REVIEW,
                           f"CSN entity {csn[0]} differs from UEN {uen}",
                           blocker="The CSN does not belong to this legal employer's UEN",
                           action="Confirm the CSN with CPF Board"))
    elif csn[1] not in MANDATORY_CPF_PAYMENT_TYPES:
        items.append(_item("cpf_csn", "B", "CPF Submission Number (CSN)", REVIEW,
                           f"payment type {csn[1]} is not a mandatory-contribution CSN (PTE)",
                           blocker="SDL and SHG cannot be paid with a voluntary-contribution CSN (CPF EZPay spec)",
                           action="Use the mandatory CSN (payment type PTE) for payroll"))
    else:
        items.append(_item("cpf_csn", "B", "CPF Submission Number (CSN)", PASS,
                           f"UEN {csn[0]} · payment type {csn[1]} · Sno {csn[2]}"))
    method = ids.get("cpf_ezpay_method")
    items.append(_item("cpf_ezpay_method", "B", "CPF EZPay method", PASS if method else FAIL,
                       f"method {method or 'not set'}; payment {ids.get('cpf_payment_method') or 'not set'}",
                       blocker="The CPF submission method is not declared", action="Select the EZPay method"))
    if facts.get("ezpay_accepted"):
        items.append(_item("cpf_file_validated", "B", "CPF EZPay file accepted by CPF Board", PASS,
                           "an EZPay submission is recorded ACCEPTED"))
    else:
        items.append(_item("cpf_file_validated", "B", "CPF EZPay file accepted by CPF Board", BLOCKED,
                           "EZPay file generated and validated in Zoiko" if facts.get("ezpay_generated")
                           else "no EZPay file generated yet",
                           blocker="CPF Board acceptance of a submitted file is external — not evidenced",
                           owner="Employer (Corppass submitter) / CPF Board",
                           action="Submit a generated file via CPF EZPay (Corppass) and record the outcome"))

    # C. IRAS / AIS
    mode = ids.get("ais_submission_mode")
    if mode == "DIRECT_API":
        items.append(_item("ais_mode", "C", "IRAS AIS submission mode", BLOCKED, "DIRECT API selected",
                           blocker="AIS-API 2.0 onboarding (APEX OAuth 2.1 + Corppass) is not evidenced — Zoiko "
                                   "only produces an export",
                           owner="Employer / IRAS", action="Select EXPORT_ONLY until API onboarding is evidenced"))
    else:
        items.append(_item("ais_mode", "C", "IRAS AIS submission mode", PASS if mode == "EXPORT_ONLY" else FAIL,
                           f"mode {mode or 'not set'}", blocker="AIS mode must be explicitly set (SG-027)",
                           action="Set the AIS submission mode"))
    threshold = facts.get("ais_threshold")
    count = facts.get("employee_count") or 0
    ais_status = ids.get("ais_status")
    if threshold is None:
        items.append(_item("ais_participation", "C", "AIS participation", BLOCKED, "AIS threshold not configured in the active pack",
                           blocker="No active Singapore pack row ais_mandatory_employee_threshold", owner="Super Admin",
                           action="Activate the Singapore pack"))
    elif count >= threshold and ais_status != "PARTICIPANT":
        items.append(_item("ais_participation", "C", "AIS participation", FAIL,
                           f"{count} employees ≥ {threshold} (IRAS: AIS mandatory) but participation is {ais_status or 'not set'}",
                           blocker="AIS is mandatory for this employer", action="Join AIS and set participation"))
    else:
        items.append(_item("ais_participation", "C", "AIS participation", PASS if ais_status else FAIL,
                           f"{count} employees; participation {ais_status or 'not set'}",
                           blocker="AIS participation not declared", action="Declare AIS participation"))
    items.append(_item("corppass", "C", "Corppass authorisation", PASS if ids.get("corppass_authorised") == "YES" else FAIL,
                       f"Corppass authorised: {ids.get('corppass_authorised') or 'not set'}; reporting owner "
                       f"{ids.get('annual_reporting_owner') or 'not set'}",
                       blocker="Customer-controlled Corppass submission is required (SG-028)",
                       action="Authorise the submitter in Corppass and record it"))

    # D. Foreign workforce
    declared = ids.get("employs_foreign_workers")
    holders = facts.get("foreign_pass_holders") or 0
    if declared is None:
        items.append(_item("foreign_workforce", "D", "Foreign workforce determined", FAIL, "not declared",
                           blocker="Foreign-workforce applicability not determined", action="Declare it"))
    elif (declared == "YES") != (holders > 0):
        items.append(_item("foreign_workforce", "D", "Foreign workforce determined", REVIEW,
                           f"declared {declared}, payroll has {holders} EP/S Pass/WP holder(s)",
                           blocker="Declaration contradicts employee work-pass data", action="Correct the declaration"))
    else:
        items.append(_item("foreign_workforce", "D", "Foreign workforce determined", PASS,
                           f"declared {declared}; {holders} pass holder(s)"))
    wp = facts.get("work_permit_holders") or 0
    if wp:
        sector = ids.get("mom_sector")
        worker_sectors = facts.get("work_permit_sectors") or set()
        if not sector or sector == "NOT_APPLICABLE":
            status, evidence = FAIL, f"{wp} Work Permit holder(s); employer MOM sector not set"
        elif worker_sectors - {sector}:
            status, evidence = REVIEW, f"employer sector {sector}; worker sectors {sorted(worker_sectors)}"
        else:
            status, evidence = PASS, f"sector {sector}; {wp} Work Permit holder(s)"
        items.append(_item("mom_sector", "D", "MOM sector / levy account", status, evidence,
                           blocker="Work Permit levy needs the MOM sector", action="Set the MOM sector per the levy account"))
    pwm = ids.get("pwm_applicable")
    flagged = facts.get("pwm_flagged_employees") or 0
    if pwm is None:
        items.append(_item("pwm_applicability", "D", "PWM / LQS applicability determined", FAIL, "not declared",
                           blocker="PWM applicability not determined (SG-027)", action="Declare PWM applicability"))
    elif pwm == "NO" and flagged:
        items.append(_item("pwm_applicability", "D", "PWM / LQS applicability determined", REVIEW,
                           f"declared NO but {flagged} employee(s) carry a PWM classification",
                           blocker="Declaration contradicts employee PWM data", action="Correct the declaration"))
    else:
        items.append(_item("pwm_applicability", "D", "PWM / LQS applicability determined", PASS,
                           f"declared {pwm}; {flagged} PWM-classified employee(s)"))

    # E. SDL / SHG
    route = ids.get("sdl_payment_route")
    items.append(_item("sdl_route", "E", "SDL payment route", PASS if route else FAIL, f"route {route or 'not set'}",
                       blocker="No SDL payment route (SG-027)", action="Set the SDL route (CPF EZPay payment code 11)"))

    # G. Banking
    bank_ok = facts.get("settlement_bank") and facts.get("settlement_acc")
    validated = ids.get("bank_workflow_validated") == "YES"
    items.append(_item("banking", "G", "Salary payment bank workflow proven", PASS if bank_ok and validated else FAIL,
                       f"settlement account {'set' if bank_ok else 'missing'}; workflow validated "
                       f"{ids.get('bank_workflow_validated') or 'not set'}",
                       blocker="Bank workflow must be validated separately from payroll (spec §9 G)",
                       action="Validate the bank file with the bank and record it"))

    # PDPA
    items.append(_item("pdpa", "H", "PDPA / NRIC controls approved", PASS if ids.get("pdpa_controls_approved") == "YES" else FAIL,
                       f"approved: {ids.get('pdpa_controls_approved') or 'not set'}",
                       blocker="PDPA controls not approved (SG-027)", owner="Employer data protection officer",
                       action="Approve the NRIC/FIN handling controls"))

    # Statutory configuration
    pack = facts.get("active_pack")
    items.append(_item("statutory_pack", "H", "Active Singapore statutory pack", PASS if pack else BLOCKED,
                       f"active pack {pack}" if pack else "no Active Singapore pack for today",
                       blocker="Statutory configuration not activated (maker-checker + certification)",
                       owner="Super Admin", action="Activate the Singapore pack"))

    # Parallel run (G8) — external
    items.append(_item("parallel_run", "H", "Parallel payroll run with the customer", BLOCKED,
                       "internal two-cycle simulation only",
                       blocker="A real parallel run needs customer payroll data (external)",
                       owner="Customer / implementation team", action="Run a parallel cycle against the incumbent payroll"))

    counts = {s: sum(1 for i in items if i["status"] == s) for s in (PASS, FAIL, REVIEW, BLOCKED)}
    return {"status": "LIVE_READY" if counts[PASS] == len(items) else "NOT_READY", "counts": counts, "items": items}
