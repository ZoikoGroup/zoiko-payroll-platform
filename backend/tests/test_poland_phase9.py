"""Poland Phase 9 (ZP-PL-ENG-001 §14 / §15): release gates G1-G7 re-derived from
data, the authority-example golden check (AC-PL-02), parallel cycles
(AC-PL-03, G6), identifier key rotation (G5) and the canary allow-list
(AC-PL-08)."""
import json
from datetime import date
from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException, NotFoundException
from tests.test_poland_filing import _paid
from tests.test_poland_service import PESEL, world  # noqa: F401  (pytest fixture)
from tests.test_poland_super_admin import _sign_everything, console  # noqa: F401  (pytest fixture)

F1 = "G=8000;AR=1.67;D=2026-03-31;PIT2=FULL;PPK=ENROLLED => pit=513;zusEe=1096.80;health=621.29;net=5608.91"


# ── golden check (AC-PL-02) ────────────────────────────────────────────────
@pytest.mark.parametrize("text, message", [
    ("G=8000", "inputs => expected"),
    ("G=8000 => pit=1", "AR is required"),
    ("G=8000;AR=1 => tax=1", "unknown expected figure"),
    ("G=8000;AR=1;PIT2=QUARTER => pit=1", "PIT2 must be"),
    ("G=8000;AR=1;PPK=MAYBE => pit=1", "PPK must be"),
    ("G=x;AR=1 => pit=1", "G must be a number"),
    ("G=8000;AR=1;D=31-03-2026 => pit=1", "D must be a date"),
    ("G=8000;AR=1 =>", "at least one expected"),
    ("G=8000;AR=1;" + "PIT2=FULL;" * 15 + " => pit=1", "at most 150"),
])
def test_examples_are_validated(text, message):
    from app.modules.payroll import poland_golden

    with pytest.raises(ValueError, match=message):
        poland_golden.parse_example(text)


def test_examples_need_a_reason_and_replay_exactly(console):
    c = console
    add = lambda **d: c.psa.add_golden_example(c.db, c.pack, {"name": "F1", "taxFormula": F1,  # noqa: E731
                                                             "sourceDocumentId": c.source, "reason": "AC-PL-02", **d},
                                               c.editor)
    # Gate removal (2026-11-25): the source document is optional provenance (no reviewed-source requirement).
    with pytest.raises(BadRequestException, match="change reason"):
        add(reason="")
    with pytest.raises(BadRequestException, match="taxFormula"):
        add(taxFormula="G=1")
    with pytest.raises(BadRequestException, match="not a field"):
        add(ratePct="1")
    add()
    with pytest.raises(BadRequestException, match="already has"):
        add()
    seeded = c.psa.golden_check(c.db, c.pack)
    # Gate removal (2026-11-25): the seeded pack carries the approved values, so it already replays F1.
    assert seeded["examples"] == 1 and seeded["passed"] is True and seeded["results"][0]["error"] is None
    _sign_everything(c)
    out = c.psa.golden_check(c.db, c.pack)
    assert out["passed"] is True and out["results"][0]["failures"] == []
    add(name="F1-wrong", taxFormula=F1.replace("net=5608.91", "net=5608.90"))
    out = c.psa.golden_check(c.db, c.pack)
    assert out["passed"] is False
    assert {"field": "net", "expected": "5608.90", "actual": "5608.91"} in out["results"][1]["failures"]


def test_golden_check_with_no_example_does_not_pass(console):
    out = console.psa.golden_check(console.db, console.pack)
    assert (out["examples"], out["passed"]) == (0, False)


# ── release gates ──────────────────────────────────────────────────────────
def _gate(state, key):
    return next(g for g in state["gates"] if g["gate"] == key)


def _check(gate, key):
    return next(c for c in gate["checks"] if c["key"] == key)


# ── G5: identifier key rotation ────────────────────────────────────────────
def test_key_rotation_is_dry_run_by_default_and_all_or_nothing(world, monkeypatch):
    from app.config import settings
    from app.modules.payroll import pl_identifiers as pid
    from app.modules.payroll import poland_service as pl
    from app.modules.payroll.models import PayrollPlIdentifierAccessEvent

    w = world
    row = pl.create_pl_identifier(w.db, w.org, "PESEL", PESEL, w.a, employee_id=w.employee.id)
    w.db.commit()
    assert pl.pl_vault_stale_rows(w.db) == 0
    monkeypatch.setattr(settings, "PL_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32, "2": "n" * 32}))
    assert pl.pl_vault_stale_rows(w.db) == 1
    dry = pl.rotate_pl_identifier_keys(w.db)
    assert (dry["rotated"], dry["written"], row.key_version) == (1, False, 1)
    assert PESEL not in json.dumps(dry)
    out = pl.rotate_pl_identifier_keys(w.db, dry_run=False)
    w.db.commit()
    assert (out["written"], row.key_version) == (True, 2) and pl.pl_vault_stale_rows(w.db) == 0
    assert pid.decrypt(row.ciphertext, row.key_version, pl._vault_owner(row)) == PESEL
    assert w.db.query(PayrollPlIdentifierAccessEvent).filter_by(vault_id=row.id, action="ROTATED").count() == 1
    monkeypatch.setattr(settings, "PL_IDENTIFIER_KEYRING", json.dumps({"2": "n" * 32, "3": "m" * 32}))
    row.ciphertext = row.ciphertext[:-4] + "AAAA"                           # damaged row
    w.db.commit()
    failed = pl.rotate_pl_identifier_keys(w.db, dry_run=False)
    assert failed["written"] is False and failed["failed"] == [{"id": row.id,
                                                                "reason": "does not decrypt with its owner binding"}]
    monkeypatch.setattr(settings, "PL_IDENTIFIER_KEYRING", "")
    assert pl.pl_vault_stale_rows(w.db) is None
    with pytest.raises(BadRequestException, match="not configured"):
        pl.rotate_pl_identifier_keys(w.db)


# ── G6: parallel cycles ────────────────────────────────────────────────────
MAP = {"employeeCode": "code", "gross": "brutto", "pit_advance": "pit", "zus_employee": "zus_ee",
       "health": "zdrowotna", "net_pay": "netto"}


def _csv(net="5608.91", extra_header="", extra_cell=""):
    head = "code,brutto,pit,zus_ee,zdrowotna,netto" + extra_header
    return f"{head}\nPL1,\"8 000,00\",513.00,1096.80,621.29,{net}{extra_cell}\n"


def _paid_parallel(w):
    run, item = _paid(w)
    item.net_pay = Decimal("5608.91")
    w.db.commit()
    return run, item


def test_identifiers_refuse_the_whole_file(world):
    from app.modules.payroll import poland_parallel as pp

    w = world
    run, _item = _paid_parallel(w)
    body = {"runId": run.id, "sourceName": "Incumbent", "columnMap": MAP, "reason": "cycle 1"}
    for header, cell, message in ((",PESEL", ",1", "identifier column"),
                                  (",note", f",{PESEL}", "PESEL"),
                                  (",note", ",526-104-08-28", "NIP"),
                                  (",note", ",PL61109010140000071219812874", "bank account")):  # privacy-scan: allow
        with pytest.raises(BadRequestException, match=message):
            pp.import_parallel(w.db, w.org, {**body, "csv": _csv(extra_header=header, extra_cell=cell)}, w.a)
    assert pp.list_parallel_imports(w.db, w.org) == []


def test_zero_tolerance_compare_explain_accept_with_four_eyes(world):
    from app.modules.payroll import poland_parallel as pp

    w = world
    run, item = _paid_parallel(w)
    body = {"runId": run.id, "sourceName": "Incumbent", "columnMap": MAP, "reason": "cycle 1"}
    clean = pp.import_parallel(w.db, w.org, {**body, "csv": _csv()}, w.a)
    assert (clean["matchedCount"], clean["unmatchedCount"], clean["differences"], clean["clean"]) == (1, 0, [], True)
    with pytest.raises(BadRequestException, match="already imported"):
        pp.import_parallel(w.db, w.org, {**body, "csv": _csv()}, w.a)
    off = pp.import_parallel(w.db, w.org, {**body, "csv": _csv(net="5608.90")}, w.a)
    diff = off["differences"][0]
    assert (diff["concept"], diff["difference"], off["clean"]) == ("net_pay", "0.01", False)
    with pytest.raises(BadRequestException, match="Every row must match"):
        pp.accept_import(w.db, w.org, off["id"], w.b)
    pp.explain_difference(w.db, w.org, diff["id"], "incumbent rounds net down", w.a)
    w.db.commit()
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        pp.accept_difference(w.db, w.org, diff["id"], w.a)
    w.db.rollback()
    pp.accept_difference(w.db, w.org, diff["id"], w.b)
    w.db.commit()
    with pytest.raises(Exception, match="(?i)four|approv|same"):
        pp.accept_import(w.db, w.org, off["id"], w.a)
    w.db.rollback()
    assert pp.accept_import(w.db, w.org, off["id"], w.b)["status"] == "ACCEPTED"
    ok, detail = pp.g6_state(w.db)
    assert ok is False and "0 legal employer(s)" in detail and "1 accepted cycle month" in detail
    with pytest.raises(NotFoundException):
        pp.parallel_summary(w.db, w.org + 999, off["id"])


def test_g6_needs_two_employers_each_with_two_months(world):
    from app.modules.payroll import poland_parallel as pp
    from app.modules.payroll.models import PayrollPlParallelImport

    w = world
    for entity_key, months in ((1, (3, 4)), (2, (3,))):
        for month in months:
            w.db.add(PayrollPlParallelImport(organization_id=w.org, legal_entity_id=None, run_id=None,
                                             pay_date=date(2026, month, 28), cycle_month=date(2026, month, 1),
                                             source_name=f"E{entity_key}", file_hash=f"{entity_key}{month}" * 8,
                                             column_map={}, status="ACCEPTED", created_by_id=w.a,
                                             approved_by_id=w.b))
    w.db.commit()
    ok, detail = pp.g6_state(w.db)
    assert ok is False and "1 legal employer(s)" in detail                   # both rows share legal entity None


# ── AC-PL-08: canary ───────────────────────────────────────────────────────
def test_phase_9_routes_are_exposed():
    from app.modules.payroll.pl_org_router import router
    from app.modules.super_admin.router import router as sa_router

    paths = {(m, r.path) for r in router.routes for m in r.methods}
    for method, path in (("GET", "/poland/parallel-imports"), ("POST", "/poland/parallel-imports"),
                         ("GET", "/poland/parallel-imports/{import_id}"),
                         ("POST", "/poland/parallel-imports/{import_id}/accept"),
                         ("POST", "/poland/parallel-imports/{import_id}/withdraw"),
                         ("POST", "/poland/parallel-differences/{difference_id}/explain"),
                         ("POST", "/poland/parallel-differences/{difference_id}/accept")):
        assert (method, path) in paths, path
    sa_paths = {(m, r.path) for r in sa_router.routes for m in r.methods}
    for path in ("/super-admin/compliance/poland/packs/{pack_row_id}/authority-examples",
                 "/super-admin/compliance/poland/packs/{pack_row_id}/golden-check"):
        assert any(p.endswith(path.split("/super-admin", 1)[1]) and m == "POST" for m, p in sa_paths), path
