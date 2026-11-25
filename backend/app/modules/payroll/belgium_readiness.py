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
from typing import Optional

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


# Who acts on a failing check — shown on the Release Readiness tab as Done /
# Missing / Who acts. "code" = engineering work; "data" = content or
# configuration someone must supply (rows, schemas, launch employers, keys);
# "sign-off" = a human approval or accepted evidence (signing, certification,
# owner / security sign-offs). Keys not listed: evidence tags are sign-offs.
CHECK_ACTORS = {
    "pack_seeded": "data", "catalogue_complete": "data", "no_pending_rows": "sign-off",
    "authority_examples_match": "data", "golden_certification": "sign-off",
    "launch_employers_named": "data", "sector_coverage": "data", "no_special_regimes": "data",
    "transmission_adapter": "code",
    "parallel_cycles": "data",
    "accepted_dimona": "data", "accepted_dmfa": "data", "reconciled_obligation": "data",
    "be_identifier_keyring": "data", "be_identifier_fingerprint_key": "data",
    "retention_decided": "sign-off",
}
ACTORS = ("code", "data", "sign-off")


def check_actor(key: str) -> str:
    if key in CHECK_ACTORS:
        return CHECK_ACTORS[key]
    if key.startswith("schema_"):
        return "data"                 # an authority schema to archive
    return "sign-off"                 # an evidence tag (BE-CONNECTIVITY-*, BE-SIGNOFF-*, BE-OWNER-*, ...)


def _today() -> date:
    return date.today()


def _covers(pack, day: date) -> bool:
    return ((pack.effective_from is None or pack.effective_from <= day)
            and (pack.effective_to is None or pack.effective_to >= day))


def _be_tax_packs(db: Session) -> list:
    """Belgian tax packs, latest start date first (ties: newest row first)."""
    from app.modules.payroll.models import JurisdictionPack

    return (db.query(JurisdictionPack)
            .filter(JurisdictionPack.jurisdiction_country == "BE", JurisdictionPack.pack_type == "tax")
            .order_by(JurisdictionPack.effective_from.desc(), JurisdictionPack.id.desc()).all())


def be_g1_overlap_warning(db: Session, today: Optional[date] = None) -> Optional[str]:
    """A warning when more than one non-Active Belgian tax pack covers today
    (gate G1 then judges the one with the latest start date), or None. Active
    packs cannot overlap: activation refuses it."""
    day = today or _today()
    covering = [p for p in _be_tax_packs(db) if p.status != "Active" and _covers(p, day)]
    if len(covering) <= 1:
        return None
    listed = ", ".join(f"{p.pack_id} v{p.version} ({p.status}, from {p.effective_from})" for p in covering)
    return (f"{len(covering)} non-Active Belgian packs cover today: {listed}. Gate G1 judges the one with the "
            f"latest start date, {covering[0].pack_id} v{covering[0].version}. Overlapping packs should be resolved "
            "— adjust their effective dates so that only one covers any day.")


def be_g1_pack(db: Session, today: Optional[date] = None) -> tuple:
    """(pack, why) — the Belgian tax pack gate G1 judges, in this order:
      1. the Active pack (the one in force today if several are Active);
      2. otherwise the pack whose effective dates include today — if several
         non-Active packs cover today, the one with the LATEST start date
         (be_g1_overlap_warning then flags the overlap on Readiness);
      3. only if neither exists, the next upcoming pack (earliest future start);
      4. otherwise (only past, non-Active packs) the most recent one.
    A future pack is never preferred over one that covers today — an empty
    next-year Draft used to shadow the current pack. The choice only decides
    WHICH pack G1 judges; that pack still fails G1 when its catalogue is
    incomplete, unsigned or unsourced."""
    day = today or _today()
    packs = _be_tax_packs(db)
    active = [p for p in packs if p.status == "Active"]
    if active:
        in_force = [p for p in active if _covers(p, day)]
        return (in_force or active)[0], "the Active pack" + (" (in force today)" if in_force else "")
    current = [p for p in packs if _covers(p, day)]
    if current:
        return current[0], "in force today"
    upcoming = sorted((p for p in packs if p.effective_from and p.effective_from > day),
                      key=lambda p: (p.effective_from, p.id))
    if upcoming:
        return upcoming[0], f"no pack is in force today; the next upcoming pack (starts {upcoming[0].effective_from})"
    if packs:
        return packs[0], "no pack is in force today or upcoming; the most recent pack"
    return None, "no Belgian tax pack exists"


def be_launch_organizations() -> frozenset:
    from app.modules.payroll import belgium_dormancy

    return belgium_dormancy.canary_organization_ids()


def _be_evidence_check(db: Session, tag: str) -> tuple:
    from app.modules.payroll import belgium_service as be

    from app.modules.payroll import belgium_governance as gov

    accepted, submitted = be._evidence(db, tag)
    if accepted is not None:
        return True, f"{tag} recorded (artifact #{accepted.id})"
    evidence = gov.be_accepted_gate_evidence(db, tag)          # K2: accepted by a second Super Admin
    if evidence is not None:
        return True, f"{tag} accepted (gate evidence #{evidence.id})"
    pending = db.query(gov._models().PayrollBeGateEvidence.id).filter_by(evidence_type=tag, status="PENDING").first()
    return False, f"{tag} {'submitted, not reviewed' if submitted or pending else 'missing'}"


def _be_g1(db, pack, add, why: str = ""):
    from app.modules.payroll import belgium_golden
    from app.modules.payroll.engine.countries import belgium_content as content
    from app.modules.payroll.models import ContributionRate, TaxSlab

    add("pack_seeded", pack is not None, f"Judging {pack.pack_id} v{pack.version} ({pack.status}): {why}" if pack
        else "no canonical Belgium pack is seeded")
    if pack is None:
        for key in ("catalogue_complete", "no_pending_rows", "authority_examples_match", "golden_certification"):
            add(key, False, "no pack")
        return
    rates = db.query(ContributionRate).filter(
        ContributionRate.jurisdiction_pack_id == pack.id, ContributionRate.organization_id.is_(None)).all()
    # An empty (or partly seeded) pack has nothing pending — that must not read
    # as "every row signed": the catalogue itself has to be present first.
    missing = sorted(set(content.KEYS) - {r.component_key for r in rates})
    add("catalogue_complete", not missing,
        "every catalogue key has a row" if not missing else
        f"{len(missing)} of {len(content.KEYS)} catalogue row(s) missing (e.g. {', '.join(missing[:5])})")
    pending = ([r.component_key for r in rates if content.PENDING_MARK in (r.label or "")]
               + [s.rule_type for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id,
                                                                TaxSlab.organization_id.is_(None))
                  if content.PENDING_MARK in (s.rate_label or "")])
    if not rates:
        add("no_pending_rows", False, "no catalogue rows to sign")
    else:
        add("no_pending_rows", not pending, f"{len(pending)} row(s) PENDING G1" if pending else "every row signed")
    golden = belgium_golden.be_golden_check(db, pack)
    bad = sum(1 for r in golden["results"] if not r["ok"])
    add("authority_examples_match", golden["passed"],
        f"{golden['examples']} example(s); " + ("all replay exactly" if golden["passed"] else
                                                "none registered" if not golden["examples"] else f"{bad} do not"))
    run, why = belgium_golden.be_certification_for(db, pack)
    add("golden_certification", why is None,
        why or f"certification run #{run.id} PASS for {pack.pack_id} v{pack.version}, content unchanged since")


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
            checks[gate].append({"key": key, "ok": bool(ok), "detail": detail, "actor": check_actor(key)})
        return add

    pack, why = be_g1_pack(db)
    launch = be_launch_organizations()
    _be_g1(db, pack, adder("G1"), why)
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
    warning = be_g1_overlap_warning(db)
    return {"jurisdiction": "BE", "gates": gates, "decisions": decisions,
            "warnings": [warning] if warning else [],
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
