"""New Zealand release gates G1-G7 (ZP-NZ-ENG-001 §15; Phase 9; mirrors
japan_readiness.py).

Each gate passes only when (a) every code check on the CANONICAL New Zealand
pack and platform state is met — re-derived on every request, nothing ticked
by hand — and (b) its evidence artefact ``NZ-GATE-<Gn>`` is recorded and
reviewed by someone other than its uploader (new_zealand_service._nz_evidence).
A pack row counts as signed only when it has its value and no longer carries
the "[PENDING G1]" marker. Nothing here changes data; New Zealand's service
availability may move to AVAILABLE only when every gate and every owner
decision passes (the service_registry_transition hook).
"""
from __future__ import annotations

from sqlalchemy.orm import Session

MARK = "[PENDING G1]"
GATES = (
    ("G1", "Statutory content signed (PAYE, ACC, KiwiSaver, student loan, child support)", "Payroll / tax specialist"),
    ("G2", "Holidays and leave content (public holidays, Holidays Act values)", "Employment / leave specialist"),
    ("G3", "Payday filing certified (IRD schema, deadlines, remittance dates)", "Compliance (IRD gateway)"),
    ("G4", "IRD-number security and privacy", "Security lead"),
    ("G5", "Parallel cycles accepted", "Payroll operations"),
    ("G6", "Operations ready (go-live runbook reviewed)", "Operations / support lead"),
    ("G7", "Launch sign-off (product, compliance, engineering, commercial)", "CTO + commercial"),
)
SIGNOFFS = ("PRODUCT", "COMPLIANCE", "ENGINEERING", "COMMERCIAL")
RETENTION_CATEGORIES = ("TAX_RECORDS", "WAGE_TIME_RECORDS", "HOLIDAY_LEAVE_RECORDS")
G3_KEYS = ("nz_working_day_rule", "nz_payday_filing_working_days", "nz_paper_filing_working_days",
           "nz_filing_payload_version", "nz_large_employer_threshold", "nz_remit_monthly_due_day",
           "nz_remit_first_half_due_day", "nz_remit_second_half_due_day", "nz_remit_december_second_half_due")


def _content():
    from app.modules.payroll.engine.countries import new_zealand_content

    return new_zealand_content


def _pack_rows(db: Session):
    """The canonical NZ-PAYROLL pack (the Active version, else the newest) with
    its rows."""
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab

    pack_id = _content().NZ_2026_27[0]
    packs = (db.query(JurisdictionPack).filter(JurisdictionPack.pack_id == pack_id)
             .order_by(JurisdictionPack.id.desc()).all())
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
    if row.flat_amount is None and not (row.text_value or "").strip():
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


def nz_code_checks(db: Session) -> dict:
    """{gate: [{key, ok, detail}]} — every check re-derived from the data."""
    from app.config import settings
    from app.modules.payroll import new_zealand_service as nzs
    from app.modules.payroll import nz_golden, nz_parallel, retention_service

    content = _content()
    pack, rates, slabs = _pack_rows(db)
    checks = {g: [] for g, _label, _owner in GATES}

    def add(gate, key, result):
        ok, detail = result
        checks[gate].append({"key": key, "ok": bool(ok), "detail": detail})

    # G1 — statutory content signed and proven against Inland Revenue's examples
    add("G1", "pack_seeded", (pack is not None, f"{pack.pack_id} {pack.version} ({pack.status})" if pack
                              else "no canonical New Zealand pack is seeded"))
    pending = ([r.component_key for r in rates.values() if MARK in (r.label or "")]
               + [s.rule_type for s in slabs if MARK in (s.rate_label or "")])
    add("G1", "no_pending_rows", (pack is not None and not pending,
                                  f"{len(pending)} row(s) PENDING G1" if pending else "every row signed"))
    for name, table in content.NZ_EMPTY_TABLES.items():
        if table["gate"] == "G1" and not table.get("employer_content"):
            add("G1", table["rule_type"], _table(slabs, table["rule_type"]))
    golden = nz_golden.nz_golden_check(db, pack) if pack is not None else None
    add("G1", "ird_examples_match", (bool(golden and golden["passed"]),
                                     "no pack" if golden is None else
                                     f"{golden['examples']} example(s); "
                                     + ("all match exactly" if golden["passed"] else
                                        f"{sum(1 for r in golden['results'] if not r['ok'])} do not match")))

    # G2 — public holidays (national per pack year, every region's anniversary day) and Holidays Act values
    holidays = [s for s in slabs if (s.rule_type or "").upper() == content.NZ_PUBLIC_HOLIDAY_RULE
                and MARK not in (s.rate_label or "")]
    years = sorted({pack.effective_from.year, (pack.effective_to or pack.effective_from).year}) if pack else []
    national_years = {s.effective_from.year for s in holidays if not s.jurisdiction_state and s.effective_from}
    missing_years = [y for y in years if y not in national_years]
    add("G2", "national_public_holidays", (pack is not None and not missing_years,
                                           "signed national holidays for " + ", ".join(map(str, years))
                                           if not missing_years else
                                           "no signed national holidays for " + ", ".join(map(str, missing_years))))
    regions = {s.jurisdiction_state for s in holidays if s.jurisdiction_state}
    missing_regions = [code for code, _name in content.NZ_REGIONS if code not in regions]
    add("G2", "regional_anniversary_days", (not missing_regions,
                                            "every region has its anniversary day" if not missing_regions
                                            else f"no anniversary day for: {', '.join(missing_regions)}"))
    for key in sorted(k for k in content.NZ_PARAMETER_KEYS if k.startswith("nz_hol_")):
        add("G2", key, _signed(rates, key))

    # G3 — payday filing: a certified schema, the deadline and remittance rules
    add("G3", "export_schemas", (bool(content.NZ_EXPORT_SCHEMAS),
                                 "certified: " + ", ".join(sorted(content.NZ_EXPORT_SCHEMAS))
                                 if content.NZ_EXPORT_SCHEMAS else "no certified payday-filing schema"))
    for key in G3_KEYS:
        add("G3", key, _signed(rates, key))

    # G4 — IRD-number keys configured (presence only) and every vault row rotated to the newest key
    for name in ("NZ_IRD_KEYRING", "NZ_IRD_FINGERPRINT_KEY"):
        present = bool((getattr(settings, name, "") or "").strip())
        add("G4", name.lower(), (present, f"{name} is configured" if present else f"{name} is not configured"))
    stale = nzs.nz_vault_stale_rows(db)
    add("G4", "vault_on_newest_key", (stale == 0, "no keyring" if stale is None else
                                      f"{stale} IRD number(s) not under the newest key version"))

    # G5 — parallel cycles
    add("G5", "parallel_cycles", nz_parallel.g5_state(db))

    # G6 — evidence only (the reviewed go-live runbook)

    # G7 — retention approved for the statutory categories (owner decision D-7)
    policies = {c["category"]: c for c in retention_service.retention_policies(db, nzs.NZ)["categories"]}
    for category in RETENTION_CATEGORIES:
        entry = policies.get(category) or {}
        add("G7", f"retention_{category.lower()}", (entry.get("state") == "APPROVED",
                                                    f"{entry.get('retentionYears')} year(s), approved"
                                                    if entry.get("state") == "APPROVED"
                                                    else entry.get("blocker") or "no approved retention period"))
    return checks


def nz_readiness(db: Session) -> dict:
    from app.modules.payroll import new_zealand_service as nzs

    checks = nz_code_checks(db)
    gates = []
    for key, label, owner in GATES:
        tags = [f"NZ-GATE-{key}"] + ([f"NZ-SIGNOFF-{s}" for s in SIGNOFFS] if key == "G7" else [])
        evidence = []
        for tag in tags:
            accepted, submitted = nzs._nz_evidence(db, tag)
            evidence.append({"tag": tag, "state": "RECORDED" if accepted else ("SUBMITTED" if submitted else "OPEN"),
                             "artifactId": getattr(accepted, "id", None)})
        passed = all(c["ok"] for c in checks[key]) and all(e["state"] == "RECORDED" for e in evidence)
        gates.append({"gate": key, "label": label, "owner": owner, "checks": checks[key], "evidence": evidence,
                      "passed": passed, "checklist": f"docs/new_zealand/release-gates/{key}.md"})
    decisions = nzs.owner_decisions(db)
    return {"jurisdiction": nzs.NZ, "gates": gates, "decisions": decisions,
            "allPassed": all(g["passed"] for g in gates) and all(d["state"] == "RECORDED" for d in decisions)}


def nz_unmet_requirements(db: Session) -> list:
    """[{key, label, detail}] for the service-registry AVAILABLE step."""
    state = nz_readiness(db)
    unmet = [{"key": g["gate"], "label": g["label"],
              "detail": "; ".join([c["detail"] for c in g["checks"] if not c["ok"]]
                                  + [f"{e['tag']} {e['state']}" for e in g["evidence"] if e["state"] != "RECORDED"])}
             for g in state["gates"] if not g["passed"]]
    unmet += [{"key": d["key"], "label": d["label"], "detail": f"owner decision {d['state']}"}
              for d in state["decisions"] if d["state"] != "RECORDED"]
    return unmet
