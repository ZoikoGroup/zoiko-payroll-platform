"""Malaysia Phase 10 (ZP-MY-ENG-001 §16): release gates G1-G7 re-derived from
data, the golden check (official worked examples replayed exactly; contribution
figures provable while PCB is blocked), parallel payroll cycles at zero
tolerance with four-eyes acceptance and the foreign-worker condition of G5,
and identifier key rotation. Amounts are the TEST pack's — never certifying."""
import json
from datetime import date
from decimal import Decimal

import pytest

from app.core.exceptions import BadRequestException
from tests.test_malaysia_service import (NRIC, _run_with_payslip, _setup, with_pcb, world)  # noqa: F401


# ── golden examples ────────────────────────────────────────────────────────
@pytest.mark.parametrize("text, message", [
    ("G=5000", "inputs => expected"), ("D=2026-03-31 => epfEe=550", "G is required"),
    ("G=5000 => tax=1", "unknown expected figure"), ("G=5000;CLS=MY_65 => epfEe=1", "CLS must be one of"),
    ("G=5000;D=31-03-2026 => epfEe=1", "D must be a date"), ("G=5000 =>", "at least one expected"),
    ("G=" + "1" * 200 + " => epfEe=1", "at most 150"),
])
def test_example_format_is_validated(text, message):
    from app.modules.payroll.malaysia_golden import parse_example

    with pytest.raises(ValueError, match=message):
        parse_example(text)


def _pack_with_examples(db, examples):
    """A Draft MY pack whose rows are the signed TEST pack, plus examples."""
    from app.modules.payroll.engine.countries import malaysia_content as content
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxSlab
    from tests._my_engine_helpers import build_pack

    version = f"1.{db.query(JurisdictionPack).filter_by(pack_id='MY-PAYROLL-2026').count()}"
    pack = JurisdictionPack(pack_id="MY-PAYROLL-2026", version=version, jurisdiction_country="MY", pack_type="tax",
                            status="Draft", effective_from=date(2026, 1, 1), effective_to=date(2026, 12, 31))
    db.add(pack)
    db.flush()
    rate_map, slabs = build_pack()
    for key, r in rate_map.items():
        db.add(ContributionRate(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country="MY",
                                component_key=key, label=r["label"], employee_share="-", employer_share="-",
                                total="-", employee_rate_pct=r["employee_rate_pct"],
                                employer_rate_pct=r["employer_rate_pct"], flat_amount=r["flat_amount"],
                                text_value=r["text_value"], effective_from=r["effective_from"],
                                effective_to=r["effective_to"], jurisdiction_state=r["jurisdiction_state"]))
    for s in slabs:
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country="MY",
                       rule_type=s["rule_type"], filing_status=s.get("filing_status"), tax_regime=s.get("tax_regime"),
                       assessment_basis=s.get("assessment_basis"), rate_label=s["rate_label"],
                       tax_formula=s.get("tax_formula") or "", jurisdiction_state=s.get("jurisdiction_state"),
                       min_amount=s.get("min_amount"), max_amount=s.get("max_amount"), flat_amount=s.get("flat_amount"),
                       rate_pct=Decimal("0"), effective_from=s.get("effective_from"), effective_to=s.get("effective_to"),
                       sort_order=s.get("sort_order") or 0))
    for n, formula in enumerate(examples):
        db.add(TaxSlab(jurisdiction_pack_id=pack.id, organization_id=None, jurisdiction_country="MY",
                       rule_type=content.MY_AUTHORITY_EXAMPLE_RULE, filing_status=f"EX{n}", rate_label=f"Example {n}",
                       tax_formula=formula, min_amount=Decimal("0"), rate_pct=Decimal("0"), sort_order=9000 + n))
    db.commit()
    return pack


def test_golden_check_proves_contributions_while_pcb_is_blocked(db):
    from app.modules.payroll import malaysia_golden

    pack = _pack_with_examples(db, [
        "G=5000;D=2026-03-31 => epfEe=550;epfEr=650;socsoEe=24.75;eisEe=9.90",
        "G=5000;D=2026-06-30;CIT=NON_CITIZEN;CLS=NONMY_POST_1998;SOC=FOREIGN_WORKER;EIS=FOREIGN_EXCLUDED "
        "=> epfEe=100;socsoEe=37.50",
    ])
    out = malaysia_golden.my_golden_check(db, pack)
    assert out["examples"] == 2 and out["passed"] is True and out["pcbProven"] is False
    assert all(r["partial"] for r in out["results"])
    wrong = _pack_with_examples(db, ["G=5000;D=2026-03-31 => epfEe=551", "G=5000;D=2026-03-31 => pcb=100"])
    out = malaysia_golden.my_golden_check(db, wrong)
    assert out["passed"] is False
    assert out["results"][0]["failures"] == [{"field": "epfEe", "expected": "551", "actual": "550.00"}]
    assert "MY_PCB_SPEC_NOT_ARCHIVED" in out["results"][1]["error"]                 # PCB is never approximated


def test_golden_check_is_exact_once_pcb_is_built(db, with_pcb):
    from app.modules.payroll import malaysia_golden

    pack = _pack_with_examples(db, ["G=5000;D=2026-03-31 => pcb=100;net=4315.35"])
    out = malaysia_golden.my_golden_check(db, pack)
    assert out["passed"] is True and out["pcbProven"] is True


# ── release gates ──────────────────────────────────────────────────────────
def test_every_gate_fails_closed_on_a_fresh_platform(db):
    from app.modules.payroll import malaysia_readiness

    state = malaysia_readiness.my_readiness(db)
    assert [g["gate"] for g in state["gates"]] == ["G1", "G2", "G3", "G4", "G5", "G6", "G7"]
    assert state["allPassed"] is False and not any(g["passed"] for g in state["gates"])
    g1 = {c["key"]: c for c in state["gates"][0]["checks"]}
    assert g1["pack_seeded"]["detail"] == "no canonical Malaysia pack is seeded"
    g3 = {c["key"]: c for c in state["gates"][2]["checks"]}
    assert "PCB_MONTHLY" in g3["form_layouts_archived"]["detail"]
    g7 = state["gates"][6]
    assert [e["tag"] for e in g7["evidence"]] == ["MY-GATE-G7", "MY-SIGNOFF-PRODUCT", "MY-SIGNOFF-COMPLIANCE",
                                                  "MY-SIGNOFF-ENGINEERING", "MY-SIGNOFF-COMMERCIAL"]
    unmet = {u["key"] for u in malaysia_readiness.my_unmet_requirements(db)}
    assert {"G1", "G2", "G3", "G4", "G5", "G6", "G7", "MY-DECISION-D-8"} <= unmet


def test_gate_g1_needs_pcb_even_when_every_other_example_matches(db):
    from app.modules.payroll import malaysia_readiness

    _pack_with_examples(db, ["G=5000;D=2026-03-31 => epfEe=550;epfEr=650"])
    g1 = {c["key"]: c for c in malaysia_readiness.my_readiness(db)["gates"][0]["checks"]}
    assert g1["pack_seeded"]["ok"] and g1["authority_examples_match"]["ok"] and g1["no_pending_rows"]["ok"]
    assert g1["MY_EPF_SCHEDULE"]["ok"] and g1["pcb_proven"]["ok"] is False


def test_malaysia_cannot_be_opened_and_the_summary_carries_the_gates(world):
    from app.modules.payroll import jurisdiction_hooks

    with pytest.raises(Exception):
        jurisdiction_hooks.call("MY", "service_registry_transition", world.db, "AVAILABLE", "launch", world.a)
    summary = jurisdiction_hooks.call("MY", "statutory_summary", world.db)
    assert summary["readiness"]["allPassed"] is False and len(summary["readiness"]["gates"]) == 7


# ── parallel cycles (gate G5) ──────────────────────────────────────────────
def _paid_run(w):
    from app.modules.payroll import malaysia_service as my
    from app.modules.payroll.models import PayrollStatus

    _setup(w)
    run, item = _run_with_payslip(w)
    item.net_pay = Decimal(item.my_calculation_snapshot["my_net"])
    run.status = PayrollStatus.PAID
    w.employee.employee_code = "MY1"
    w.db.commit()
    return run, item


def _import(w, run, csv, mapping=None):
    from app.modules.payroll import malaysia_parallel as mpp

    return mpp.import_parallel(w.db, w.org, {"runId": run.id, "sourceName": "Incumbent", "reason": "cycle 1",
                                             "csv": csv, "columnMap": mapping or {"employeeCode": "Code",
                                                                                  "gross": "Gross", "pcb": "PCB",
                                                                                  "epf_employee": "EPF"}}, w.a)


def test_parallel_cycle_compares_at_zero_tolerance_with_four_eyes(world, with_pcb):
    from app.modules.payroll import malaysia_parallel as mpp

    w = world
    run, _item = _paid_run(w)
    out = _import(w, run, "Code,Gross,PCB,EPF\nMY1,5000.00,100.00,549.99\n")
    assert out["matchedCount"] == 1 and out["unmatchedCount"] == 0 and out["clean"] is False
    diff = out["differences"][0]
    assert (diff["concept"], diff["incumbentAmount"], diff["zoikoAmount"]) == ("epf_employee", "549.99", "550.00")
    w.db.commit()
    with pytest.raises(BadRequestException, match="Every row"):
        mpp.accept_import(w.db, w.org, out["id"], w.b)
    mpp.explain_difference(w.db, w.org, diff["id"], "incumbent rounds EPF down", w.a)
    w.db.commit()
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        mpp.accept_difference(w.db, w.org, diff["id"], w.a)
    w.db.rollback()
    mpp.accept_difference(w.db, w.org, diff["id"], w.b)
    accepted = mpp.accept_import(w.db, w.org, out["id"], w.b)
    assert accepted["status"] == "ACCEPTED" and accepted["clean"]
    with pytest.raises(BadRequestException, match="already imported"):
        _import(w, run, "Code,Gross,PCB,EPF\nMY1,5000.00,100.00,549.99\n")


def test_parallel_files_with_identifiers_are_refused(world, with_pcb):
    w = world
    run, _item = _paid_run(w)
    with pytest.raises(BadRequestException, match="NRIC"):
        _import(w, run, f"Code,Gross,Note\nMY1,5000.00,{NRIC[:6]}-{NRIC[6:8]}-{NRIC[8:]}\n",
                {"employeeCode": "Code", "gross": "Gross"})
    with pytest.raises(BadRequestException, match="identifier column"):
        _import(w, run, "Code,Gross,TIN\nMY1,5000.00,x\n", {"employeeCode": "Code", "gross": "Gross"})


def test_g5_needs_two_employers_two_months_and_a_foreign_worker(world, with_pcb, monkeypatch):
    from app.modules.payroll import malaysia_parallel as mpp

    w = world
    assert mpp.g5_state(w.db)[0] is False
    monkeypatch.setattr(mpp, "accepted_cycles", lambda db: {(1, 1): {date(2026, 3, 1), date(2026, 4, 1)},
                                                            (1, 2): {date(2026, 3, 1), date(2026, 4, 1)}})
    ok, detail = mpp.g5_state(w.db)
    assert ok is False and "0 accepted cycle(s) with a foreign worker" in detail
    monkeypatch.setattr(mpp, "foreign_worker_cycles", lambda db: 1)
    assert mpp.g5_state(w.db)[0] is True


# ── key rotation (gate G4) ─────────────────────────────────────────────────
def test_rotation_moves_every_identifier_to_the_newest_key(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll import malaysia_service as my

    w = world
    row = my.create_my_identifier(w.db, w.org, "NRIC", NRIC, w.a, employee_id=w.employee.id)
    assert my.my_vault_stale_rows(w.db) == 0
    monkeypatch.setattr(settings, "MY_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32, "2": "n" * 32}))
    assert my.my_vault_stale_rows(w.db) == 1
    dry = my.rotate_my_identifier_keys(w.db)
    assert dry == {**dry, "rotated": 1, "written": False, "failed": []} and NRIC not in json.dumps(dry)
    applied = my.rotate_my_identifier_keys(w.db, dry_run=False)
    assert applied["written"] is True and row.key_version == 2 and my.my_vault_stale_rows(w.db) == 0
    my.request_my_identifier_reveal(w.db, w.org, row.id, "check after rotation", w.a)
    my.approve_my_identifier_reveal(w.db, w.org, row.id, w.b)
    assert my.reveal_my_identifier(w.db, w.org, row.id, w.a)["value"] == NRIC


def test_console_adds_examples_only_with_a_reviewed_source(db):
    from app.modules.auth.models import User, UserRole
    from app.modules.payroll import my_super_admin as msa
    from app.modules.payroll.models import SourceArtifact

    users = []
    for i in range(3):
        u = User(email=f"sa{i}.my10@example.com", hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="S",
                 last_name=str(i), is_active=True, is_verified=True)
        db.add(u)
        users.append(u)
    db.flush()
    reviewed = SourceArtifact(agency="KWSP", title="EPF Third Schedule examples", checksum_sha256="a" * 64,
                              file_path="sources/epf.pdf", created_by_id=users[1].id,
                              reviewer_id=users[2].id)
    draft = SourceArtifact(agency="KWSP", title="notes", created_by_id=users[1].id)
    db.add_all([reviewed, draft])
    db.flush()
    pack_id = msa.seed_draft(db, {"reason": "start"}, users[0].id)["packs"][0]["id"]
    payload = {"name": "EPF 5000", "taxFormula": "G=5000 => epfEe=550", "reason": "official example",
               "sourceDocumentId": reviewed.id}
    row = msa.add_golden_example(db, pack_id, payload, users[0].id)
    assert row["ruleType"] == "MY_AUTHORITY_EXAMPLE" and row["detail"] == "G=5000 => epfEe=550"
    with pytest.raises(BadRequestException, match="already has"):
        msa.add_golden_example(db, pack_id, payload, users[0].id)
    with pytest.raises(BadRequestException, match="taxFormula"):
        msa.add_golden_example(db, pack_id, {**payload, "name": "bad", "taxFormula": "G=5000"}, users[0].id)
    with pytest.raises(BadRequestException):
        msa.add_golden_example(db, pack_id, {**payload, "name": "draft src", "sourceDocumentId": draft.id},
                               users[0].id)
    assert msa.golden_check(db, pack_id)["examples"] == 1
