"""Poland release gates G1-G7 (ZP-PL-ENG-001 §15; Phase 9; mirrors
nz_readiness.py).

Each gate passes only when (a) every code check on the CANONICAL Poland pack
and platform state is met — re-derived on every request, nothing ticked by
hand — and (b) its evidence artefact ``PL-GATE-<Gn>`` (G7 also the four
``PL-SIGNOFF-*`` artefacts) is recorded and reviewed by someone other than its
uploader (poland_service._evidence). A pack row counts as signed only when it
has its value and no longer carries the "[PENDING G1]" marker. Nothing here
changes data; Poland's service availability may move to AVAILABLE only when
every gate and every launch-blocking owner decision passes (the
service_registry_transition hook).

  G1 Statutory content   every row signed; PIT bands and earning classes
                         signed; official / independent examples replay exactly
  G2 Worker coverage     earning-class matrix complete, no REVIEW treatment left,
                         supported contract types / pay frequencies signed
  G3 Labour pay/benefits minimum wage, overtime, leave and sickness rows signed
  G4 Filing/settlement   an archived schema for every in-scope form (PL-019);
                         due-date and reconciliation rows signed
  G5 Security/privacy    identifier keys configured; every vault row on the
                         newest key version
  G6 Parallel payroll    two legal employers each with accepted cycles in two
                         distinct months (AC-PL-03)
  G7 Operations          approved retention periods (decision D-7) and the
                         product / compliance / engineering / commercial sign-offs
"""
from __future__ import annotations

from sqlalchemy.orm import Session

MARK = "[PENDING G1]"
GATES = (
    ("G1", "Statutory content (PIT / ZUS / health / funds / PPK / minimum wage) signed and proven",
     "Payroll Content + Polish specialist"),
    ("G2", "Worker coverage (contract / title matrix, fail-closed missing facts)", "Product + Legal / payroll specialist"),
    ("G3", "Labour pay and benefits (minimum wage, overtime, leave, sickness)", "Product + Polish payroll specialist"),
    ("G4", "Filing and settlement (form versions, receipts, corrections, reconciliation)", "Integration + Payroll Ops"),
    ("G5", "Security and privacy (threat model, access matrix, secrets, DPIA, incident runbook)",
     "Security + Privacy"),
    ("G6", "Parallel payroll (two cycles, signed variance report)", "QA + Implementation"),
    ("G7", "Operations and commercial (calendar, runbooks, launch employers, scope claims)",
     "Payroll Ops + Product / Management"),
)
SIGNOFFS = ("PRODUCT", "COMPLIANCE", "ENGINEERING", "COMMERCIAL")
RETENTION_CATEGORIES = ("PAYROLL_RECORDS", "TAX_RECORDS", "SOCIAL_INSURANCE_RECORDS")
IN_SCOPE_FORMS = ("DRA", "RCA", "RSA", "ZUA", "ZZA", "ZWUA", "PIT11", "PIT4R")
G2_KEYS = ("pl_supported_contract_types", "pl_supported_pay_frequencies")
G3_PREFIXES = ("pl_min_wage", "pl_min_hourly", "pl_overtime", "pl_night", "pl_working_hours", "pl_pay_deadline",
               "pl_leave", "pl_sick", "pl_benefit")
G4_KEYS = ("pl_zus_due_day_classes", "pl_pit_remittance_due_rule", "pl_pit11_authority_due", "pl_pit11_employee_due",
           "pl_pit4r_due", "pl_ppk_transfer_day", "pl_reconciliation_tolerance")


def _content():
    from app.modules.payroll.engine.countries import poland_content

    return poland_content


def _pack_rows(db: Session):
    """The canonical Poland tax pack (the newest Active one, else the newest)
    with its rows."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "PL",
                                               JurisdictionPack.pack_type == "tax")
             .order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).all())
    pack = next((p for p in packs if p.status == "Active"), packs[0] if packs else None)
    if pack is None:
        return None, {}, []
    rates = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                               ContributionRate.organization_id.is_(None)).all())
    slabs = (db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id, TaxSlab.organization_id.is_(None))
             .all())
    return pack, {r.component_key: r for r in rates}, slabs


def _signed(rates: dict, key: str) -> tuple:
    row = rates.get(key)
    if row is None:
        return False, f"{key} is missing"
    if MARK in (row.label or ""):
        return False, f"{key} is PENDING G1"
    values = (row.flat_amount, row.employee_rate_pct, row.employer_rate_pct)
    if all(v is None for v in values) and not (row.text_value or "").strip():
        return False, f"{key} has no value"
    return True, f"{key} signed"


def _table(slabs, rule_type: str) -> tuple:
    rows = [s for s in slabs if (s.rule_type or "").upper() == rule_type]
    pending = [s for s in rows if MARK in (s.rate_label or "")]
    if not rows:
        return False, f"{rule_type}: no rows"
    if pending:
        return False, f"{rule_type}: {len(pending)} of {len(rows)} row(s) PENDING G1"
    return True, f"{rule_type}: {len(rows)} signed row(s)"


def pl_code_checks(db: Session) -> dict:
    """{gate: [{key, ok, detail}]} — every check re-derived from the data."""
    from app.config import settings
    from app.modules.payroll import poland_golden, poland_parallel, retention_service
    from app.modules.payroll import poland_service as pls

    content = _content()
    pack, rates, slabs = _pack_rows(db)
    checks = {g: [] for g, _label, _owner in GATES}

    def add(gate, key, result):
        ok, detail = result
        checks[gate].append({"key": key, "ok": bool(ok), "detail": detail})

    # G1 — statutory content signed and proven against official / independent examples
    add("G1", "pack_seeded", (pack is not None, f"{pack.pack_id} {pack.version} ({pack.status})" if pack
                              else "no canonical Poland pack is seeded"))
    pending = ([r.component_key for r in rates.values() if MARK in (r.label or "")]
               + [s.rule_type for s in slabs if MARK in (s.rate_label or "")])
    add("G1", "no_pending_rows", (pack is not None and not pending,
                                  f"{len(pending)} row(s) PENDING G1" if pending else "every row signed"))
    add("G1", content.PL_PIT_BAND_RULE, _table(slabs, content.PL_PIT_BAND_RULE))
    golden = poland_golden.pl_golden_check(db, pack) if pack is not None else None
    add("G1", "authority_examples_match", (bool(golden and golden["passed"]),
                                           "no pack" if golden is None else
                                           f"{golden['examples']} example(s); "
                                           + ("all match exactly" if golden["passed"] else
                                              "none recorded" if not golden["examples"] else
                                              f"{sum(1 for r in golden['results'] if not r['ok'])} do not match")))

    # G2 — worker coverage: the full earning-class matrix, every treatment decided
    add("G2", content.PL_EARNING_CLASS_RULE, _table(slabs, content.PL_EARNING_CLASS_RULE))
    classes = [s for s in slabs if (s.rule_type or "").upper() == content.PL_EARNING_CLASS_RULE]
    present = {((s.tax_regime or "").upper(), (s.filing_status or "").upper()) for s in classes}
    expected = {(o.upper(), c.upper()) for (o, _t, c, _l, _s) in content.POLAND_EARNING_CLASSES}
    missing = sorted(expected - present)
    add("G2", "earning_class_matrix_complete", (pack is not None and not missing,
                                                "every component x obligation present" if not missing
                                                else f"{len(missing)} component x obligation pair(s) missing"))
    review = [s for s in classes if (s.assessment_basis or "").upper() == "REVIEW"]
    add("G2", "no_review_treatments", (pack is not None and not review,
                                       "every treatment decided" if not review
                                       else f"{len(review)} treatment(s) still REVIEW"))
    for key in G2_KEYS:
        add("G2", key, _signed(rates, key))

    # G3 — labour pay and benefits rows signed
    for key in sorted(k for k in content.POLAND_PARAMETER_KEYS if k.startswith(G3_PREFIXES)):
        add("G3", key, _signed(rates, key))

    # G4 — an archived schema for every in-scope form; due-date / reconciliation rows
    catalog = content.PL_FORM_SCHEMA_CATALOG
    unarchived = [f for f in IN_SCOPE_FORMS if not (catalog.get(f) or {}).get("versions")]
    add("G4", "form_schemas_archived", (not unarchived, "every in-scope form has an archived schema"
                                        if not unarchived else f"no archived schema for: {', '.join(unarchived)}"))
    for key in G4_KEYS:
        add("G4", key, _signed(rates, key))

    # G5 — identifier keys configured (presence only) and every vault row on the newest key
    for name in ("PL_IDENTIFIER_KEYRING", "PL_IDENTIFIER_FINGERPRINT_KEY"):
        present = bool((getattr(settings, name, "") or "").strip())
        add("G5", name.lower(), (present, f"{name} is configured" if present else f"{name} is not configured"))
    stale = pls.pl_vault_stale_rows(db)
    add("G5", "vault_on_newest_key", (stale == 0, "no keyring" if stale is None else
                                      f"{stale} identifier(s) not under the newest key version"))

    # G6 — parallel cycles
    add("G6", "parallel_cycles", poland_parallel.g6_state(db))

    # G7 — retention approved for the statutory categories (owner decision D-7)
    policies = {c["category"]: c for c in retention_service.retention_policies(db, pls.PL)["categories"]}
    for category in RETENTION_CATEGORIES:
        entry = policies.get(category) or {}
        add("G7", f"retention_{category.lower()}", (entry.get("state") == "APPROVED",
                                                    f"{entry.get('retentionYears')} year(s), approved"
                                                    if entry.get("state") == "APPROVED"
                                                    else entry.get("blocker") or "no approved retention period"))
    return checks


def pl_readiness(db: Session) -> dict:
    from app.modules.payroll import poland_service as pls

    checks = pl_code_checks(db)
    gates = []
    for key, label, owner in GATES:
        tags = [f"PL-GATE-{key}"] + ([f"PL-SIGNOFF-{s}" for s in SIGNOFFS] if key == "G7" else [])
        evidence = []
        for tag in tags:
            accepted, submitted = pls._evidence(db, tag)
            evidence.append({"tag": tag, "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                             "artifactId": getattr(accepted, "id", None)})
        passed = all(c["ok"] for c in checks[key]) and all(e["state"] == "RECORDED" for e in evidence)
        gates.append({"gate": key, "label": label, "owner": owner, "checks": checks[key], "evidence": evidence,
                      "passed": passed, "checklist": f"docs/poland/release-gates/{key}.md"})
    decisions = pls.owner_decisions(db)
    blocking = [d for d in decisions if d["blocksLaunch"]]
    return {"jurisdiction": pls.PL, "gates": gates, "decisions": decisions,
            "allPassed": all(g["passed"] for g in gates) and all(d["state"] == "RECORDED" for d in blocking)}


def pl_unmet_requirements(db: Session) -> list:
    """[{key, label, detail}] for the service-registry AVAILABLE step."""
    state = pl_readiness(db)
    unmet = [{"key": g["gate"], "label": g["label"],
              "detail": "; ".join([c["detail"] for c in g["checks"] if not c["ok"]]
                                  + [f"{e['tag']} {e['state']}" for e in g["evidence"] if e["state"] != "RECORDED"])}
             for g in state["gates"] if not g["passed"]]
    unmet += [{"key": f"PL-DECISION-{d['key']}", "label": d["label"], "detail": f"owner decision {d['state']}"}
              for d in state["decisions"] if d["blocksLaunch"] and d["state"] != "RECORDED"]
    return unmet
