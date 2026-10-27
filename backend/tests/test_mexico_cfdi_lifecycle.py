"""Mexico Phase 7 — CFDI lifecycle on SYNTHETIC seams + the test-only mock PAC:
preconditions (§2), generation → SIGNED → stamp, an event per transition,
illegal transitions, rejection, MX-016, durable storage (D4), the reset rule
(D2/D3), lifecycles kept separate (MX-041), and production unreachability."""

import re
from pathlib import Path

import pytest

from tests import _mx_cfdi_helpers as ch
from tests import _mx_run_helpers as rh


def _S():
    from app.modules.payroll import mexico_cfdi_service as S

    return S


def test_preconditions_each_refuse_with_their_code(db, monkeypatch, tmp_path):
    S = _S()
    w = rh.world(db, monkeypatch, code="MXPRE")
    rh.generate(db, w)
    codes = {r["code"] for r in S.preflight(db, w.run)["reasons"]}
    assert {"MX_CFDI_RUN_NOT_COMMITTED", "MX_CFDI_NO_ACTIVE_SCHEMA_RELEASE", "MX_CFDI_CSD_UNAVAILABLE",
            "MX_CFDI_PAC_NOT_SET"} <= codes
    rh.advance(db, w)
    rh.advance(db, w)
    ch.schema_release(db)
    ch.employer_ready(db, w, environment="PRODUCTION")
    codes = {r["code"] for r in S.preflight(db, w.run)["reasons"]}
    assert codes == {"MX_CFDI_STAMP_TEST_REQUIRED"}                       # D7
    with pytest.raises(Exception) as exc:
        S.generate(db, w.run, w.users[0].id)
    assert exc.value.key == "MX_CFDI_STAMP_TEST_REQUIRED" and ch.docs(db, w.run) == []


def test_production_seams_refuse_and_nothing_is_created(db, monkeypatch, tmp_path):
    S = _S()
    from app.modules.payroll import mexico_cfdi_builder as B

    from app.modules.payroll import mexico_cfdi_schema

    w = ch.committed_world(db, monkeypatch, tmp_path)
    monkeypatch.setattr(B, "_BUILDER", B.SatBuilder())
    with pytest.raises(Exception) as exc:                 # Phase 11b: the builder runs, but only on a release
        S.generate(db, w.run, w.users[0].id)              # loaded from a verified pinned set (this one is synthetic)
    assert exc.value.key == "MX_CFDI_SCHEMA_SET_UNUSABLE"
    db.rollback()
    monkeypatch.setattr(mexico_cfdi_schema, "ROOT", tmp_path / "no-pinned-sets")
    with pytest.raises(Exception) as exc:                 # no verified pinned set installed at all
        S.generate(db, w.run, w.users[0].id)
    assert exc.value.key in ("MX_CFDI_BUILDER_BLOCKED", "MX_CFDI_SCHEMA_SET_UNUSABLE")
    assert B.SatBuilder().blocked().key == "MX_CFDI_BUILDER_BLOCKED"
    db.rollback()
    monkeypatch.setattr(B, "_BUILDER", ch.SyntheticBuilder())
    monkeypatch.setattr(B, "_SIGNER", B.GcpSmSigner())
    with pytest.raises(Exception) as exc:
        S.generate(db, w.run, w.users[0].id)
    assert exc.value.key == "MX_CSD_SIGNING_BLOCKED"
    db.rollback()
    assert ch.docs(db, w.run) == []


def test_generate_sign_stamp_with_an_event_per_transition(db, monkeypatch, tmp_path):
    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    pac = ch.mock(monkeypatch)
    out = S.generate(db, w.run, w.users[0].id)
    (doc,) = ch.docs(db, w.run)
    assert out["created"][0]["status"] == "SIGNED" and doc.folio == "1" and doc.payload_hash and doc.xml_storage_ref
    assert Path(doc.xml_storage_ref).read_bytes().startswith(b"<SYNTHETIC-NOT-A-CFDI")
    ch.process(db, w)
    db.refresh(doc)
    assert doc.status == "STAMPED" and doc.uuid.startswith("SYN-") and doc.sat_certificate_number == "SYN-SAT-CERT"
    assert ch.events(db, doc) == ["GENERATED", "SIGNED", "STAMP_SENT", "STAMPED",
                                 "STAMPED_XML_STORED"]                  # W4-3b: the PAC answer kept
    assert [c[0] for c in pac.calls] == ["stamp"]
    S.generate(db, w.run, w.users[0].id)                         # idempotent: one live document per payslip
    assert len(ch.docs(db, w.run)) == 1


def test_xml_never_in_the_database(db, monkeypatch, tmp_path):
    from sqlalchemy import text

    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    ch.mock(monkeypatch)
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    for table in ("payroll_mx_cfdi_documents", "payroll_mx_cfdi_outbox_items", "payroll_mx_cfdi_events"):
        dump = " ".join(str(r) for r in db.execute(text(f"SELECT * FROM {table}")).fetchall())
        assert "SYNTHETIC-NOT-A-CFDI" not in dump and "SELLO" not in dump, table


def test_durable_storage_refusal_in_production(db, monkeypatch, tmp_path):
    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    monkeypatch.setenv("ENVIRONMENT", "production")              # on the local /tmp fallback
    with pytest.raises(Exception) as exc:
        S.generate(db, w.run, w.users[0].id)
    assert exc.value.key == "MX_CFDI_STORAGE_NOT_DURABLE" and "nothing was stored" in exc.value.reason
    db.rollback()
    assert ch.docs(db, w.run) == [] and not (tmp_path / "uploads").exists()


def test_rejection_and_illegal_transitions(db, monkeypatch, tmp_path):
    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    ch.mock(monkeypatch, stamp=["reject"])
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    (doc,) = ch.docs(db, w.run)
    assert doc.status == "REJECTED" and doc.pac_response_code == "SYN-REJECT"
    with pytest.raises(Exception) as exc:
        S._transition(db, doc, "STAMPED", "X")
    assert exc.value.key == "MX_CFDI_ILLEGAL_TRANSITION"
    S.generate(db, w.run, w.users[0].id)                         # a corrected document is a NEW document
    assert sorted(d.status for d in ch.docs(db, w.run)) == ["REJECTED", "SIGNED"]


def test_stamped_fields_are_immutable_and_events_append_only(db, monkeypatch, tmp_path):
    S = _S()
    src = Path(S.__file__).read_text(encoding="utf-8")
    assert not re.search(r"PayrollMxCfdiEvent\)\.(?:filter|update|delete)\(.*\)\.(?:update|delete)", src)
    assert ".delete(" not in src.split("def _event")[1].split("def _transition")[0]
    w = ch.committed_world(db, monkeypatch, tmp_path)
    ch.mock(monkeypatch)
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    (doc,) = ch.docs(db, w.run)
    for to in ("SIGNED", "SUBMITTED", "REJECTED", "GENERATED"):
        with pytest.raises(Exception):
            S._transition(db, doc, to, "X")


def test_mx016_preview_and_recalculation_never_touch_a_document(db, monkeypatch, tmp_path):
    S = _S()
    from app.modules.payroll import service

    w = ch.committed_world(db, monkeypatch, tmp_path)
    ch.mock(monkeypatch)
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    (doc,) = ch.docs(db, w.run)
    before = (doc.status, doc.uuid, doc.payload_hash, doc.xml_storage_ref)
    service.preview_payroll_run(db, w.org.id, [w.employee.id], "MX", *rh.PERIOD, pay_date=rh.PAY_DATE)
    with pytest.raises(Exception):                               # the run is locked (Approved) — no recalculation
        service.regenerate_employee_payslip(db, w.run.id, w.employee.id, w.org.id)
    db.rollback()
    db.refresh(doc)
    assert (doc.status, doc.uuid, doc.payload_hash, doc.xml_storage_ref) == before


@pytest.mark.parametrize("script,expect", [({}, "STAMPED"), ({"stamp": ["timeout"]}, "UNKNOWN")])
def test_reset_refused_once_transmitted(db, monkeypatch, tmp_path, script, expect):
    from app.modules.payroll import mexico_run_service

    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    ch.mock(monkeypatch, **script)
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    assert ch.docs(db, w.run)[0].status == expect
    with pytest.raises(Exception) as exc:
        mexico_run_service.reset_run(db, w.run, w.users[0].id, "correct a figure")
    assert "MX_RESET_DOWNSTREAM_ACTED" in str(getattr(exc.value, "detail", exc.value))


def test_reset_voids_untransmitted_documents(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_run_service

    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    S.generate(db, w.run, w.users[0].id)                         # SIGNED, never sent
    out = mexico_run_service.reset_run(db, w.run, w.users[0].id, "correct a figure")
    (doc,) = ch.docs(db, w.run)
    assert out["removed"]["cfdiVoided"] == 1 and doc.status == "VOIDED" and "VOIDED_ON_RESET" in ch.events(db, doc)


def test_cfdi_never_moves_payroll_authority_or_bank_state(db, monkeypatch, tmp_path):
    from app.modules.payroll import mexico_run_service

    S = _S()
    w = ch.committed_world(db, monkeypatch, tmp_path)
    ch.mock(monkeypatch)
    before = mexico_run_service.run_status(db, w.run)
    S.generate(db, w.run, w.users[0].id)
    ch.process(db, w)
    after = mexico_run_service.run_status(db, w.run)
    assert before["payroll"]["status"] == after["payroll"]["status"] == "Approved"
    assert before["bank"] == after["bank"] and before["authorities"] == after["authorities"]
    assert before["ledgers"] == after["ledgers"]
    assert before["cfdi"]["status"] == "NOT_STARTED" and after["cfdi"]["status"] == "STAMPED"
    with pytest.raises(Exception) as exc:                        # a stamp does not unlock AUTHORIZED (D8, MX-017)
        rh.advance(db, w)
    assert exc.value.key == "MX_RUN_NOT_SUPPORTED"


def test_production_has_no_adapter_and_no_adapter_code():
    from app.modules.payroll import mexico_pac as P

    assert P._ADAPTERS == {} and P._PROVIDER_RETRY_CONFIG == {}
    with pytest.raises(Exception) as exc:
        P.get_adapter("MOCK", "SANDBOX")
    assert exc.value.key == "MX_PAC_NOT_CONFIGURED"
    app_dir = Path(P.__file__).resolve().parents[2]
    hits = [p.name for p in app_dir.rglob("*.py") if re.search(r"class \w+\((?:\w+\.)?PacAdapter\)", p.read_text(
        encoding="utf-8", errors="ignore"))]
    assert hits == []


def test_flag_off_refuses_every_cfdi_route(db, monkeypatch, tmp_path):
    from app.config import settings
    from tests._mx_employer_helpers import ORG_BASE, http, principal

    w = ch.committed_world(db, monkeypatch, tmp_path)
    monkeypatch.setattr(settings, "MX_TENANT_ONBOARDING_ENABLED", False)
    with http(db, principal(w.org.id, w.users[0].id)) as client:
        for method, path in (("get", f"/runs/{w.run.id}/cfdi"), ("post", f"/runs/{w.run.id}/cfdi/generate"),
                             ("post", "/cfdi/outbox/process"), ("get", "/cfdi/documents/1"),
                             ("post", "/cfdi/documents/1/status-query"), ("post", "/cfdi/documents/1/confirm-retry"),
                             ("post", "/cfdi/documents/1/cancel"), ("post", "/cfdi/reconcile"),
                             ("get", "/cfdi/cancellation-reasons")):
            r = getattr(client, method)(ORG_BASE + path, **({"json": {}} if method == "post" else {}))
            assert r.status_code == 403, (path, r.status_code)
    from app.modules.payroll import mexico_cfdi_service as S

    with pytest.raises(Exception) as exc:
        S.generate(db, w.run, w.users[0].id)
    assert exc.value.key == "MX_DORMANT"
