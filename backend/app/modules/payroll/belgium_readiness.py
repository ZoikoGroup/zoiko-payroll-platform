"""Belgium release gates G1-G7 (ZP-BE-ENG-001 §17; Block C2; mirrors
poland_readiness.py).

Every check is re-derived from data on each request; nothing is ticked by hand.
The result carries COUNTS and organisation ids only, never a worker identity
(the Super Admin readiness route is an aggregate route, route_overrides).
An evidence tag counts only when a reviewed source artifact carries it, with a
file, reviewed by someone other than its uploader (belgium_service._evidence).
Launch employers are the organisations on BE_CANARY_ORG_IDS (the activation
runbook names them there first).

  G1 Statutory content   canonical pack seeded, every row signed (no
                         "[PENDING G1]"), authority examples replay exactly and
                         the latest BE golden-vector certification run passed
  G2 Sector coverage     launch employers named; every ACTIVE employment line of
                         their Belgian employees has a Joint Committee and an
                         Active agreement with wage scales; no special regime
  G3 Connectivity        a certified transmission adapter; a signed, archived
                         schema for Dimona / DmfA / FinProf / Belcotax today;
                         connectivity evidence per form
  G4 Payroll accuracy    two accepted parallel cycles (distinct months) for every
                         launch employer
  G5 Filing/settlement   an accepted Dimona and DmfA, a reconciled obligation,
                         and the end-to-end (incl. outage / retry) evidence
  G6 Security/privacy    identifier keys configured; security, DPIA / privacy
                         and retention sign-offs (retention = owner decision G-21)
  G7 Ownership           named, trained owners: statutory content, payroll
                         operations, incident / on-call, change calendar, local
                         specialist escalation
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.orm import Session

GATES = (
    ("G1", "Statutory content archived, interpreted, signed and covered by regression fixtures",
     "Payroll Content + Belgian specialist"),
    ("G2", "Sector coverage for each launch employer and worker population", "Product + Belgian specialist"),
    ("G3", "Authority connectivity (Dimona, DmfA, FinProf, Belcotax)", "Integration"),
    ("G4", "Payroll accuracy: two parallel cycles per design partner", "QA + Implementation"),
    ("G5", "Filing and settlement end to end, incl. outage / retry", "Integration + Payroll Ops"),
    ("G6", "Security and privacy approved", "Security + Privacy"),
    ("G7", "Operational ownership named and trained", "Payroll Ops + Management"),
)
CONNECTIVITY_TAGS = tuple(f"BE-CONNECTIVITY-{f}" for f in ("DIMONA", "DMFA", "FINPROF", "BELCOTAX"))
FILING_E2E_TAG = "BE-FILING-E2E"
SECURITY_TAGS = ("BE-SIGNOFF-SECURITY", "BE-SIGNOFF-PRIVACY")
OWNER_TAGS = tuple(f"BE-OWNER-{o}" for o in ("CONTENT", "PAYROLL-OPS", "INCIDENT", "CHANGE-CALENDAR", "SPECIALIST"))


def _be_canonical_pack(db: Session):
    from app.modules.payroll.models import JurisdictionPack

    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "BE")
             .order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).all())
    return next((p for p in packs if p.status == "Active"), packs[0] if packs else None)


def be_launch_organizations() -> frozenset:
    from app.modules.payroll import belgium_dormancy

    return belgium_dormancy.canary_organization_ids()


def _be_evidence_check(db: Session, tag: str) -> tuple:
    from app.modules.payroll import belgium_service as be

    accepted, submitted = be._evidence(db, tag)
    if accepted is not None:
        return True, f"{tag} recorded (artifact #{accepted.id})"
    return False, f"{tag} {'submitted, not reviewed' if submitted else 'missing'}"


def _be_g1(db, pack, add):
    from app.modules.payroll import belgium_golden
    from app.modules.payroll.engine.countries import belgium_content as content
    from app.modules.payroll.models import ContributionRate, TaxSlab

    add("pack_seeded", pack is not None, f"{pack.pack_id} {pack.version} ({pack.status})" if pack
        else "no canonical Belgium pack is seeded")
    if pack is None:
        for key in ("no_pending_rows", "authority_examples_match", "golden_certification"):
            add(key, False, "no pack")
        return
    pending = ([r.component_key for r in db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None))
        if content.PENDING_MARK in (r.label or "")]
        + [s.rule_type for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                                         TaxSlab.organization_id.is_(None))
           if content.PENDING_MARK in (s.rate_label or "")])
    add("no_pending_rows", not pending, f"{len(pending)} row(s) PENDING G1" if pending else "every row signed")
    golden = belgium_golden.be_golden_check(db, pack)
    bad = sum(1 for r in golden["results"] if not r["ok"])
    add("authority_examples_match", golden["passed"],
        f"{golden['examples']} example(s); " + ("all replay exactly" if golden["passed"] else
                                                "none registered" if not golden["examples"] else f"{bad} do not"))
    run = belgium_golden.be_latest_certification(db)
    add("golden_certification", bool(run and run.status == "PASS"),
        f"latest BE certification run: {getattr(run, 'status', 'none')}")


def _be_g2(db, launch, add):
    from app.core.authz.scopes import organization_scoped
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import CollectiveAgreement, PayrollEmployee

    add("launch_employers_named", bool(launch), f"{len(launch)} launch employer(s)" if launch
        else "BE_CANARY_ORG_IDS names no launch employer")
    m = be._models()
    C, P = m.PayrollBeEmploymentClassification, m.PayrollBeWorkerProfile
    gaps, special, lines = [], 0, 0
    for org in sorted(launch):
        employees = [e.id for e in organization_scoped(db, PayrollEmployee, org)
                     .filter(PayrollEmployee.country_code == "BE")]
        for row in db.query(C).filter(C.organization_id == org, C.status == be.STATUS_ACTIVE,
                                      C.employee_id.in_(employees or [-1])):
            lines += 1
            agreement = db.get(CollectiveAgreement, row.collective_agreement_id) if row.collective_agreement_id else None
            scales = ((getattr(agreement, "modules", None) or {}).get("wage_scales") if agreement else None)
            if not row.joint_committee or agreement is None or agreement.status != "Active" or not scales:
                gaps.append(org)                                  # counts only: no worker identity leaves here
        special += db.query(P).filter(P.organization_id == org, P.status == be.STATUS_ACTIVE,
                                      P.special_status.isnot(None)).count()
    add("sector_coverage", bool(launch) and lines > 0 and not gaps,
        f"{lines} line(s); " + (f"{len(gaps)} without certified Joint Committee / wage-scale coverage "
                                f"(organisations {sorted(set(gaps))})" if gaps
                                else "all covered" if lines else "no employment line"))
    add("no_special_regimes", special == 0, f"{special} worker profile(s) on a special regime (blocked)"
        if special else "no special regime")


def _be_g3(db, add):
    from app.modules.payroll import belgium_filing as bf

    adapters = {a: type(bf.adapter_for(a)).__name__ for a in ("ONSS", "SPF_FINANCE")}
    certified = all(name != bf.UncertifiedAdapter.__name__ for name in adapters.values())
    add("transmission_adapter", certified, "certified adapters" if certified
        else "no certified authority channel (D9: transmission refused)")
    today = date.today()
    for form in bf.AUTHORITY:
        version, row, why = bf.schema_for(db, 0, form, today)
        archived = row is not None and bf.archived_schema(db, row) is not None
        add(f"schema_{form.lower()}", bool(version and archived),
            f"{form} {version} archived" if version and archived else
            f"{form}: {why or 'schema not archived'}")
    for tag in CONNECTIVITY_TAGS:
        add(tag.lower(), *_be_evidence_check(db, tag))


def _be_g5(db, launch, add):
    from app.modules.payroll import belgium_service as be

    m = be._models()
    F, O = m.PayrollBeFiling, m.PayrollBeObligation
    scope = sorted(launch) or [-1]
    for form in ("DIMONA", "DMFA"):
        n = db.query(F).filter(F.organization_id.in_(scope), F.form_code == form,
                               F.status.in_(("ACCEPTED", "SETTLED"))).count()
        add(f"accepted_{form.lower()}", n > 0, f"{n} accepted {form} filing(s) for launch employers")
    n = db.query(O).filter(O.organization_id.in_(scope), O.status == "RECONCILED").count()
    add("reconciled_obligation", n > 0, f"{n} reconciled obligation(s) for launch employers")
    add(FILING_E2E_TAG.lower(), *_be_evidence_check(db, FILING_E2E_TAG))


def _be_g6(db, add):
    from app.config import settings
    from app.modules.payroll import belgium_service as be

    for name in ("BE_IDENTIFIER_KEYRING", "BE_IDENTIFIER_FINGERPRINT_KEY"):
        present = bool((getattr(settings, name, "") or "").strip())
        add(name.lower(), present, f"{name} is configured" if present else f"{name} is not configured")
    for tag in SECURITY_TAGS:
        add(tag.lower(), *_be_evidence_check(db, tag))
    retention = next((d for d in be.owner_decisions(db) if d["key"] == "G-21"), None)
    add("retention_decided", bool(retention and retention["state"] == "RECORDED"),
        f"owner decision G-21 {retention['state'] if retention else 'missing'}")


def be_code_checks(db: Session) -> dict:
    """{gate: [{key, ok, detail}]} — every check re-derived from the data."""
    from app.modules.payroll import belgium_parallel

    checks = {g: [] for g, _label, _owner in GATES}

    def adder(gate):
        def add(key, ok, detail):
            checks[gate].append({"key": key, "ok": bool(ok), "detail": detail})
        return add

    pack = _be_canonical_pack(db)
    launch = be_launch_organizations()
    _be_g1(db, pack, adder("G1"))
    _be_g2(db, launch, adder("G2"))
    _be_g3(db, adder("G3"))
    ok, detail = belgium_parallel.be_g4_state(db, launch)
    adder("G4")("parallel_cycles", ok, detail)
    _be_g5(db, launch, adder("G5"))
    _be_g6(db, adder("G6"))
    for tag in OWNER_TAGS:
        adder("G7")(tag.lower(), *_be_evidence_check(db, tag))
    return checks


def be_readiness(db: Session) -> dict:
    from app.modules.payroll import belgium_service as be

    checks = be_code_checks(db)
    gates = [{"gate": key, "label": label, "owner": owner, "checks": checks[key],
              "passed": all(c["ok"] for c in checks[key]) and bool(checks[key])}
             for key, label, owner in GATES]
    decisions = be.owner_decisions(db)
    blocking = [d for d in decisions if d["blocksLaunch"]]
    return {"jurisdiction": "BE", "gates": gates, "decisions": decisions,
            "launchEmployers": sorted(be_launch_organizations()),
            "allPassed": all(g["passed"] for g in gates) and all(d["state"] == "RECORDED" for d in blocking)}


def be_unmet(db: Session) -> list:
    """[{key, label, detail}] for the service-registry AVAILABLE step."""
    state = be_readiness(db)
    unmet = [{"key": g["gate"], "label": g["label"],
              "detail": "; ".join(c["detail"] for c in g["checks"] if not c["ok"])}
             for g in state["gates"] if not g["passed"]]
    unmet += [{"key": f"BE-DECISION-{d['key']}", "label": d["label"], "detail": f"owner decision {d['state']}"}
              for d in state["decisions"] if d["blocksLaunch"] and d["state"] != "RECORDED"]
    return unmet
