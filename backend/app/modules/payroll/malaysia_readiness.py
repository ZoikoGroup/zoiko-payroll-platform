"""Malaysia release gates G1-G7 (ZP-MY-ENG-001 §16; Phase 10; mirrors
poland_readiness.py).

Each gate passes only when (a) every code check on the CANONICAL Malaysia
pack and platform state is met — re-derived on every request, nothing ticked
by hand — and (b) its evidence artefact ``MY-GATE-<Gn>`` (G7 also the four
``MY-SIGNOFF-*`` artefacts) is recorded and reviewed by someone other than its
uploader (malaysia_service._evidence). A pack row counts as signed only when
it has its value and no longer carries the "[PENDING G1]" marker. Nothing
here changes data; Malaysia's service availability may move to AVAILABLE
only when every gate and every launch-blocking owner decision passes (the
service_registry_transition hook).

  G1 Statutory content   every row signed; schedules and holiday calendars
                         loaded and signed; official examples replay exactly,
                         including at least one HASiL PCB example (Phase 4)
  G2 Territory/coverage  every territorial labour row signed for all three
                         territories; transfer rule signed; earning-class
                         matrix complete with no REVIEW; release-1 scope signed
  G3 Authority interfaces an archived layout for every in-scope form; due-date
                         rows (PCB remittance, EPF / PERKESO / HRD, EA / Form E,
                         CP22 / CP22A / CP21, clearance hold) signed
  G4 PDPA / privacy      identifier keys configured; every vault row on the
                         newest key; approved retention periods (decision D-8)
  G5 Parallel run        two legal employers each with accepted cycles in two
                         distinct months, at least one with a foreign worker
  G6 Operations          reconciliation tolerance, record retention and
                         parallel materiality rows signed; runbook evidence
  G7 Commercial          product / compliance / engineering / commercial
                         sign-offs
"""
from __future__ import annotations

from sqlalchemy.orm import Session

MARK = "[PENDING G1]"
GATES = (
    ("G1", "Statutory content (PCB, EPF, PERKESO, EIS, HRD, minimum wage) signed and proven",
     "Payroll Content + Malaysian specialist"),
    ("G2", "Territory matrix and worker coverage (Peninsular + Labuan, Sabah, Sarawak; fail-closed facts)",
     "Product + Legal / payroll specialist"),
    ("G3", "Authority interfaces (HASiL, KWSP, PERKESO, HRD Corp layouts, due dates, receipts)",
     "Integration + Payroll Ops"),
    ("G4", "PDPA and privacy (roles, transfers, DPO, identifier keys, retention)", "Security + Privacy"),
    ("G5", "Parallel run (two employers, two cycles, a foreign-worker scenario)", "QA + Implementation"),
    ("G6", "Operations (reconciliation, runbooks, support)", "Payroll Ops"),
    ("G7", "Commercial (launch employers, scope claims, sign-offs)", "Product / Management"),
)
SIGNOFFS = ("PRODUCT", "COMPLIANCE", "ENGINEERING", "COMMERCIAL")
RETENTION_CATEGORIES = ("PAYROLL_RECORDS", "TAX_RECORDS", "SOCIAL_SECURITY_RECORDS")
IN_SCOPE_FORMS = ("PCB_MONTHLY", "EPF_MONTHLY", "PERKESO_EIS_MONTHLY", "HRD_MONTHLY", "EA", "FORM_E", "CP8D",
                  "CP22", "CP22A", "CP21")
G2_KEYS = ("my_supported_contract_types", "my_supported_pay_frequencies", "my_transfer_split_rule")
G3_KEYS = ("my_pcb_remittance_day", "my_epf_due_rule", "my_socso_due_rule", "my_hrd_due_rule", "my_ea_due",
           "my_form_e_due", "my_cp22_days_after_start", "my_cp22a_days_before_cessation",
           "my_cp22a_days_after_death", "my_cp21_days_before_departure", "my_clearance_hold_max_days")
G6_KEYS = ("my_reconciliation_tolerance", "my_record_retention_years", "my_parallel_materiality_amount")


def _content():
    from app.modules.payroll.engine.countries import malaysia_content

    return malaysia_content


def _pack_rows(db: Session):
    """The canonical Malaysia tax pack (the newest Active one, else the newest)
    with its rows."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "MY",
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
    if (row.text_value or "").strip().upper() == "PENDING_G1":
        return False, f"{key} is still PENDING_G1"
    return True, f"{key} signed"


def _table(slabs, rule_type: str) -> tuple:
    rows = [s for s in slabs if (s.rule_type or "").upper() == rule_type]
    pending = [s for s in rows if MARK in (s.rate_label or "")]
    if not rows:
        return False, f"{rule_type}: no rows"
    if pending:
        return False, f"{rule_type}: {len(pending)} of {len(rows)} row(s) PENDING G1"
    return True, f"{rule_type}: {len(rows)} signed row(s)"


def my_code_checks(db: Session) -> dict:
    """{gate: [{key, ok, detail}]} — every check re-derived from the data."""
    from app.config import settings
    from app.modules.payroll import malaysia_golden, malaysia_parallel, retention_service
    from app.modules.payroll import malaysia_service as mys

    content = _content()
    pack, rates, slabs = _pack_rows(db)
    checks = {g: [] for g, _label, _owner in GATES}

    def add(gate, key, result):
        ok, detail = result
        checks[gate].append({"key": key, "ok": bool(ok), "detail": detail})

    # G1 — statutory content signed and proven
    add("G1", "pack_seeded", (pack is not None, f"{pack.pack_id} {pack.version} ({pack.status})" if pack
                              else "no canonical Malaysia pack is seeded"))
    pending = ([r.component_key for r in rates.values() if MARK in (r.label or "")]
               + [s.rule_type for s in slabs if MARK in (s.rate_label or "")])
    add("G1", "no_pending_rows", (pack is not None and not pending,
                                  f"{len(pending)} row(s) PENDING G1" if pending else "every row signed"))
    for rule in content.REQUIRED_TABLES:
        add("G1", rule, _table(slabs, rule))
    golden = malaysia_golden.my_golden_check(db, pack) if pack is not None else None
    add("G1", "authority_examples_match", (bool(golden and golden["passed"]),
                                           "no pack" if golden is None else
                                           f"{golden['examples']} example(s); "
                                           + ("all match exactly" if golden["passed"] else
                                              "none recorded" if not golden["examples"] else
                                              f"{sum(1 for r in golden['results'] if not r['ok'])} do not match")))
    add("G1", "pcb_proven", (bool(golden and golden["pcbProven"]),
                             "a HASiL PCB example replays exactly" if golden and golden["pcbProven"]
                             else "PCB is not built / no PCB example matches (Phase 4 needs the HASiL specification)"))

    # G2 — territory matrix and worker coverage
    missing_rows = [content.territory_key(base, t) for base in content.MALAYSIA_TERRITORY_KEYS
                    for t in content.TERRITORIES if not _signed(rates, content.territory_key(base, t))[0]]
    add("G2", "territorial_rows_signed", (pack is not None and not missing_rows,
                                          "every territorial labour row signed for all three territories"
                                          if not missing_rows else
                                          f"{len(missing_rows)} territorial row(s) not signed"))
    add("G2", content.MY_EARNING_CLASS_RULE, _table(slabs, content.MY_EARNING_CLASS_RULE))
    classes = [s for s in slabs if (s.rule_type or "").upper() == content.MY_EARNING_CLASS_RULE]
    present = {((s.tax_regime or "").upper(), (s.filing_status or "").upper()) for s in classes}
    expected = {(o.upper(), c.upper()) for (o, _t, c, _l, _s) in content.MALAYSIA_EARNING_CLASSES}
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

    # G3 — authority interfaces: archived layouts and due-date rows
    catalog = content.MY_FORM_SCHEMA_CATALOG
    unarchived = [f for f in IN_SCOPE_FORMS if not (catalog.get(f) or {}).get("versions")]
    add("G3", "form_layouts_archived", (not unarchived, "every in-scope form has an archived layout"
                                        if not unarchived else f"no archived layout for: {', '.join(unarchived)}"))
    for key in G3_KEYS:
        add("G3", key, _signed(rates, key))

    # G4 — PDPA / privacy: keys (presence only), vault on the newest key, retention
    for name in ("MY_IDENTIFIER_KEYRING", "MY_IDENTIFIER_FINGERPRINT_KEY"):
        present = bool((getattr(settings, name, "") or "").strip())
        add("G4", name.lower(), (present, f"{name} is configured" if present else f"{name} is not configured"))
    stale = mys.my_vault_stale_rows(db)
    add("G4", "vault_on_newest_key", (stale == 0, "no keyring" if stale is None else
                                      f"{stale} identifier(s) not under the newest key version"))
    policies = {c["category"]: c for c in retention_service.retention_policies(db, mys.MY)["categories"]}
    for category in RETENTION_CATEGORIES:
        entry = policies.get(category) or {}
        add("G4", f"retention_{category.lower()}", (entry.get("state") == "APPROVED",
                                                    f"{entry.get('retentionYears')} year(s), approved"
                                                    if entry.get("state") == "APPROVED"
                                                    else entry.get("blocker") or "no approved retention period"))

    # G5 — parallel run
    add("G5", "parallel_cycles", malaysia_parallel.g5_state(db))

    # G6 — operations rows
    for key in G6_KEYS:
        add("G6", key, _signed(rates, key))
    return checks


def my_readiness(db: Session) -> dict:
    from app.modules.payroll import malaysia_service as mys

    checks = my_code_checks(db)
    gates = []
    for key, label, owner in GATES:
        tags = [f"MY-GATE-{key}"] + ([f"MY-SIGNOFF-{s}" for s in SIGNOFFS] if key == "G7" else [])
        evidence = []
        for tag in tags:
            accepted, submitted = mys._evidence(db, tag)
            evidence.append({"tag": tag, "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                             "artifactId": getattr(accepted, "id", None)})
        passed = all(c["ok"] for c in checks[key]) and all(e["state"] == "RECORDED" for e in evidence)
        gates.append({"gate": key, "label": label, "owner": owner, "checks": checks[key], "evidence": evidence,
                      "passed": passed, "checklist": f"docs/malaysia/release-gates/{key}.md"})
    decisions = mys.owner_decisions(db)
    blocking = [d for d in decisions if d["blocksLaunch"]]
    return {"jurisdiction": mys.MY, "gates": gates, "decisions": decisions,
            "allPassed": all(g["passed"] for g in gates) and all(d["state"] == "RECORDED" for d in blocking)}


def my_unmet_requirements(db: Session) -> list:
    """[{key, label, detail}] for the service-registry AVAILABLE step."""
    state = my_readiness(db)
    unmet = [{"key": g["gate"], "label": g["label"],
              "detail": "; ".join([c["detail"] for c in g["checks"] if not c["ok"]]
                                  + [f"{e['tag']} {e['state']}" for e in g["evidence"] if e["state"] != "RECORDED"])}
             for g in state["gates"] if not g["passed"]]
    unmet += [{"key": f"MY-DECISION-{d['key']}", "label": d["label"], "detail": f"owner decision {d['state']}"}
              for d in state["decisions"] if d["blocksLaunch"] and d["state"] != "RECORDED"]
    return unmet
