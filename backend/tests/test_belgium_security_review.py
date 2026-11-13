"""Belgium (ZP-BE-ENG-001) Block D2: the NISS / BIS and the employer's ONSS number
never leave the encrypted vault (spec §15, BE-040).

A full synthetic month runs with a NISS and an ONSS number on file: payroll
generated and committed, Dimona, DmfA, withholding and Belcotax built and
accepted, a parallel cycle imported, the payroll-register CSV exported. Every
representative output is then scanned for either value (and the Belcotax /
DmfA renditions for any eleven-digit run): payslip snapshots incl. the frozen
context, the serialized payslip, filings (payload, rendition, idempotency key,
response), obligations, parallel imports / differences, every audit row, the
identifier access events, every log record emitted during the month, error
messages, and the CSV. SYNTHETIC TEST ONLY values."""
import json
import logging
import re
from datetime import date

import pytest
from fastapi import HTTPException

from app.core.exceptions import BadRequestException
from tests._be_filing_helpers import accept
from tests.test_belgium_run_lifecycle import NISS, _approve, _run, world  # noqa: F401  (pytest fixture)

ONSS = "51234567890"                   # privacy-scan: allow (synthetic TEST ONLY employer number)
ELEVEN_DIGITS = re.compile(r"(?<!\d)\d{11}(?!\d)")


def _rows(db, model):
    out = []
    for row in db.query(model).all():
        out.append({c.name: getattr(row, c.name) for c in model.__table__.columns})
    return json.dumps(out, default=str)


@pytest.fixture
def month(world, caplog):
    from app.modules.payroll import belgium_filing as bf
    from app.modules.payroll import belgium_parallel as bp
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import PayrollBeEmployerRegistration, PayslipItem

    w = world
    caplog.set_level(logging.DEBUG)
    be.create_be_identifier(w.db, w.org, "NISS", NISS, w.a, employee_id=w.employee.id)
    draft = be.record_be_employer_registration(w.db, w.org, {
        "effective_from": "2026-02-01", "legal_name": "Lifecycle BV", "enterprise_number": "0999999999",
        "employer_category_code": "X1", "onss_special_160_status": "NOT_APPLICABLE",
        "special_160_evidence_ref": "TEST ONLY workforce count", "withholding_declaration_frequency": "MONTHLY"},
        w.a, "new version with the ONSS number")
    w.db.commit()
    be.set_be_employer_onss(w.db, w.org, draft.id, ONSS, w.a)
    w.db.commit()
    be.approve_be_employer_registration(w.db, w.org, draft.id, w.b)
    w.db.commit()
    be.verify_be_employer_registration(w.db, w.org, draft.id, w.b, "VERIFIED", "checked")
    w.db.commit()
    reg = w.db.query(PayrollBeEmployerRegistration).filter_by(id=draft.id).one()
    assert reg.status == "ACTIVE" and reg.id == draft.id and reg.onss_number_vault_id
    run = _approve(w, _run(w))
    item = w.db.query(PayslipItem).filter_by(payroll_run_id=run.id).one()
    w.db.commit()
    dmfa, _o = bf.build_be_dmfa(w.db, w.org, "2026Q1", None, w.a)
    wht, _o = bf.build_be_withholding(w.db, w.org, "2026-03", None, w.a)
    fiches = bf.build_be_belcotax(w.db, w.org, 2026, None, w.a, today=date(2027, 1, 15))
    w.db.commit()
    for i, filing in enumerate([dmfa, wht, *fiches]):
        accept(w.db, w.org, filing, w.b, w.a, f"SEC{i}")
    csv_text = (f"code,gross,net\nBE1,{item.gross_pay},{item.net_pay}\n")
    imported = bp.import_be_parallel(w.db, w.org, {"runId": run.id, "sourceName": "TEST ONLY", "csv": csv_text,
                                                   "columnMap": {"employeeCode": "code", "gross": "gross",
                                                                 "net": "net"}, "reason": "cycle"}, w.a)
    w.db.commit()
    return w, run, item, [dmfa, wht, *fiches], imported, caplog


def _assert_clean(text, where):
    assert NISS not in text, f"NISS found in {where}"
    assert ONSS not in text, f"ONSS number found in {where}"


def test_no_identifier_in_payslips_filings_obligations_or_imports(month):
    from app.modules.payroll import belgium_filing as bf
    from app.modules.payroll import service
    from app.modules.payroll.models import (PayrollBeObligation, PayrollBeParallelDifference,
                                            PayrollBeParallelImport, PayslipItem)

    w, run, item, filings, imported, _log = month
    _assert_clean(json.dumps(item.be_calculation_snapshot, default=str), "be_calculation_snapshot")
    _assert_clean(json.dumps(service._serialize_payslip(item, run, "BE"), default=str), "serialized payslip")
    snapshot_identity = item.be_calculation_snapshot.get("identifierMasked")
    assert snapshot_identity and not re.search(r"\d", snapshot_identity)                # masked, no digit
    for f in filings:
        view = json.dumps(bf.get_be_filing(w.db, w.org, f.id), default=str)
        _assert_clean(view, f"filing {f.form_code} #{f.id}")
        _assert_clean(f.idempotency_key, "idempotency key")
        lines = [ln for ln in (f.rendition or "").splitlines() if "hash" not in ln.lower()]
        assert not ELEVEN_DIGITS.search("\n".join(lines)), f"eleven-digit value in the {f.form_code} rendition"
    for model in (PayrollBeObligation, PayrollBeParallelImport, PayrollBeParallelDifference, PayslipItem):
        _assert_clean(_rows(w.db, model), model.__tablename__)
    _assert_clean(json.dumps(imported, default=str), "parallel import summary")


def test_no_identifier_in_audit_access_events_or_logs(month):
    from app.modules.payroll.models import PayrollBeIdentifierAccessEvent, TaxConfigurationAudit

    w, _run_, _item, _f, _i, caplog = month
    _assert_clean(_rows(w.db, TaxConfigurationAudit), "payroll_tax_configuration_audit")
    _assert_clean(_rows(w.db, PayrollBeIdentifierAccessEvent), "identifier access events")
    _assert_clean(caplog.text, "log records")


def test_no_identifier_in_the_payroll_register_csv(month):
    from app.modules.payroll import service

    w, run, _item, _f, _i, _log = month
    text = service.generate_report_csv_bytes(w.db, run.id, w.org).decode("utf-8", "replace")
    assert text.strip()
    _assert_clean(text, "payroll register CSV")


def test_the_vault_holds_ciphertext_only_and_errors_never_echo(month):
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.models import PayrollBeIdentifierVault

    w, *_rest = month
    _assert_clean(_rows(w.db, PayrollBeIdentifierVault), "identifier vault rows")
    for bad in (NISS + "9", "12.34"):
        with pytest.raises((BadRequestException, HTTPException)) as raised:
            be.create_be_identifier(w.db, w.org, "BIS", bad, w.a, employee_id=w.employee.id)
        assert bad not in str(getattr(raised.value, "detail", raised.value))
    with pytest.raises((BadRequestException, HTTPException)) as raised:
        be.create_be_identifier(w.db, w.org, "NISS", NISS, w.a, employee_id=w.employee.id)   # duplicate
    assert NISS not in str(getattr(raised.value, "detail", raised.value))


# ── routes (D2) ────────────────────────────────────────────────────────────
READ_ONLY_POSTS = {"/api/payroll/belgium/classification/resolve"}     # the resolver: no side effects


def _be_routes():
    from app.main import app

    for route in app.routes:
        if getattr(route, "path", "").startswith("/api/payroll/belgium"):
            for method in route.methods - {"HEAD", "OPTIONS"}:
                yield method, route


def test_every_belgium_route_is_dormancy_gated_tenant_scoped_and_role_checked():
    import inspect

    routes = list(_be_routes())
    assert len(routes) > 80
    for method, route in routes:
        deps = [d.call.__name__ for d in route.dependant.dependencies]
        assert "require_be_tenant" in deps, route.path                       # dormancy + Belgian org only
        assert "_org_id(current_user)" in inspect.getsource(route.endpoint), route.path   # caller's own org
        roles = [n for n in deps if n.startswith("get_current_")]
        assert roles, route.path
        if method != "GET" and route.path not in READ_ONLY_POSTS:
            assert roles == ["get_current_org_admin"], (method, route.path, roles)      # writes: org admin
        assert "{organization_id}" not in route.path and "org_id" not in route.path      # never an org id input
