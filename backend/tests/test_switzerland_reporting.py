"""Switzerland (CH Step 14) reporting: Lohnausweis + ELM.

The Lohnausweis certificate is generated ONLY from committed (Approved/
Authorized/Paid/Closed) CH payslips through the dedicated generator, stored
with exact Decimal-string box values, rendered to whole francs at view time,
superseded by regeneration / amendment (a manual amendment is a documented
second-approver RE-ISSUE), and the generic payslip-column generator refuses
the template. The ELM build produces one envelope per (domain, receiver,
period) under its four authority statuses, validates the payload against the
registered CH-ELM:<domain> XSD when one exists (SCHEMA_UNAVAILABLE otherwise,
never blindly "valid"), stays idempotent, links corrected envelopes to the
rejected original, and is transmit-gated off. Every route is service-level
(shared with the router); no network touches any Swiss authority anywhere.
"""
import hashlib
from datetime import date
from decimal import Decimal as D

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service, switzerland_service as svc
from app.modules.payroll.models import (
    ChElmSubmission, ChQstTariffRow, GeneratedReport, PayrollRun, PayslipItem, StatutoryFiling,
)
from app.modules.payroll.schemas import ReportTemplateUpsert
from app.modules.payroll.switzerland_schemas import ChLohnausweisBoxAmend
from tests.test_switzerland_service_integration import (  # noqa: F401 (fixture)
    APPROVER, AUTHORIZER, PREPARER, ch, _item, _run, _ytd,
)


# ── test scaffolding ────────────────────────────────────────────────────

def _make_user(db, email):
    from app.modules.auth.models import User, UserRole
    user = User(email=email, hashed_password="x", role=UserRole.PAYROLL_ADMIN, first_name="Test", last_name="User")
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _approve(db, ch, month):
    run = _run(db, ch.org, month)
    service.generate_payslips_for_run(db, run, ch.org.id)
    service.advance_payroll_run_status(db, run.id, PREPARER, ch.org.id)     # Review
    service.advance_payroll_run_status(db, run.id, APPROVER, ch.org.id)     # Approved
    db.commit()
    return run, _item(db, run, ch.emp)


def _lohnausweis_template(db, creator, approver, activate=True):
    template = service.upsert_report_template(
        db, ReportTemplateUpsert(
            templateKey=svc.CH_LOHNAUSWEIS_TEMPLATE_KEY, name="TEST CH Lohnausweis",
            reportType=svc.CH_LOHNAUSWEIS_REPORT_TYPE, jurisdictionCountry="CH",
            reportingYear="2026", documentScope="PER_EMPLOYEE",
        ), actor_id=creator.id,
    )
    template = service.set_report_template_approver(db, template.id, actor_id=approver.id)
    assert template.status == "Approved"
    template = service.set_report_template_status(db, template.id, "Published", actor_id=creator.id)
    if activate:
        template = service.set_report_template_status(db, template.id, "Active", actor_id=creator.id)
        assert template.status == "Active"
    return template


def _generate(db, ch, template_id, actor_id):
    return svc.generate_ch_lohnausweis(db, ch.org.id, template_id, ch.emp.id, 2026, actor_id=actor_id)


def _tariff_b(db, ch):
    db.add_all([ChQstTariffRow(tariff_file_id=ch.tariff.id, tariff_code="B", children=0, church_tax=False,
                               income_from=D("0"), income_to=D("5000"), rate_pct=D("1")),
                ChQstTariffRow(tariff_file_id=ch.tariff.id, tariff_code="B", children=0, church_tax=False,
                               income_from=D("5000"), income_to=None, rate_pct=D("6"))])
    db.commit()


def _elm_valid_xsd() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema" elementFormDefault="qualified">
  <xs:element name="ELMSubmission">
    <xs:complexType>
      <xs:sequence>
        <xs:element name="EmployeeELM" minOccurs="0" maxOccurs="unbounded">
          <xs:complexType>
            <xs:anyAttribute processContents="lax"/>
          </xs:complexType>
        </xs:element>
        <xs:element name="Totals">
          <xs:complexType>
            <xs:anyAttribute processContents="lax"/>
          </xs:complexType>
        </xs:element>
      </xs:sequence>
      <xs:anyAttribute processContents="lax"/>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""


def _elm_broken_xsd() -> str:
    return """<?xml version="1.0" encoding="UTF-8"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="TotalsOnly">
    <xs:complexType>
      <xs:anyAttribute processContents="lax"/>
    </xs:complexType>
  </xs:element>
</xs:schema>
"""


def _qst_view(subs):
    return next(s for s in subs if s["domain"] == "QST")


# ── Lohnausweis ─────────────────────────────────────────────────────────

def test_lohnausweis_generates_from_committed_periods_stored_exact_rendered_francs(db, ch):  # noqa: F811
    creator, approver = _make_user(db, "la.creator@t.ch"), _make_user(db, "la.approver@t.ch")
    template = _lohnausweis_template(db, creator, approver)
    _approve(db, ch, 3)
    _approve(db, ch, 4)

    cert = _generate(db, ch, template.id, creator.id)
    db.commit()

    assert cert["reportType"] == svc.CH_LOHNAUSWEIS_REPORT_TYPE and cert["reportingYear"] == "2026"
    assert cert["payslipCount"] == 2 and cert["monthsDeclared"] == ["2026-03-01", "2026-04-01"]
    assert cert["employeeId"] == ch.emp.id and cert["employeeCanton"] == "CH-ZH"
    assert cert["supersedesReportIds"] == []
    boxes = {b["boxCode"]: b for b in cert["boxes"]}
    # base_salary -> ch_la treatment BOX_1; two months at 8000 stored EXACT
    assert D(boxes["BOX_1"]["valueExact"]) == D("16000")
    assert boxes["BOX_1"]["valueFrancs"] == 16000
    # 2 x 640 source tax, exact string persisted in rendered_data
    assert D(boxes["BOX_QST_WITHHELD"]["valueExact"]) == D("1280")
    assert boxes["BOX_QST_WITHHELD"]["valueFrancs"] == 1280
    # exact Decimal strings really are what the DB row carries
    row = db.get(GeneratedReport, cert["reportId"])
    stored = row.rendered_data
    assert D(next(b for b in stored["boxes"] if b["boxCode"] == "BOX_1")["valueExact"]) == D("16000")
    assert stored["payslipCount"] == 2 and stored["unmappedEarnings"] == {}


def test_draft_payslips_are_excluded_from_the_certificate(db, ch):  # noqa: F811
    creator, approver = _make_user(db, "la.draft@t.ch"), _make_user(db, "la.draft2@t.ch")
    template = _lohnausweis_template(db, creator, approver)
    run = _run(db, ch.org, 3)
    service.generate_payslips_for_run(db, run, ch.org.id)                    # stays "Draft"
    with pytest.raises(BadRequestException, match="No committed Swiss payslips"):
        _generate(db, ch, template.id, creator.id)
    assert db.query(GeneratedReport).filter_by(organization_id=ch.org.id).count() == 0


def test_generic_generator_refuses_the_ch_lohnausweis_template(db, ch):  # noqa: F811
    creator, approver = _make_user(db, "la.gen@t.ch"), _make_user(db, "la.gen2@t.ch")
    template = _lohnausweis_template(db, creator, approver)
    run = _run(db, ch.org, 4)                                                # irrelevant — refused upfront
    with pytest.raises(BadRequestException, match="dedicated Switzerland generator"):
        service.generate_report_from_template(db, ch.org.id, template.id, run.id)
    with pytest.raises(BadRequestException, match="dedicated Switzerland generator"):
        service.generate_report_from_template(db, ch.org.id, template.id, run.id,
                                              reporting_period="2026-04", actor_id=creator.id)


def test_lohnausweis_requires_only_the_active_template(db, ch):  # noqa: F811
    creator, approver = _make_user(db, "la.pub@t.ch"), _make_user(db, "la.pub2@t.ch")
    template = _lohnausweis_template(db, creator, approver, activate=False)  # Published, not Active
    _approve(db, ch, 3)
    with pytest.raises(BadRequestException, match="Active template version"):
        _generate(db, ch, template.id, creator.id)


def test_lohnausweis_regeneration_supersedes_and_links_corrections(db, ch):  # noqa: F811
    creator, approver = _make_user(db, "la.reg@t.ch"), _make_user(db, "la.reg2@t.ch")
    template = _lohnausweis_template(db, creator, approver)
    march_run, march_item = _approve(db, ch, 3)
    _approve(db, ch, 4)
    _tariff_b(db, ch)

    first = _generate(db, ch, template.id, creator.id)
    db.commit()
    assert first["corrections"] == []

    # correct March's source tax (tariff A 8% -> tariff B 6%) and approve the delta run
    # (the correction run was created BY the approver, so a THIRD person approves it)
    out = svc.create_ch_correction(db, ch.org.id, march_item.id, "TEST tariff code was wrong",
                                   ["ch_qst"], {"ch_qst_tariff_code": "B"}, APPROVER,
                                   idempotency_key=hashlib.sha256(b"reg-la-1").hexdigest(),
                                   correlation_id="la-corr-1")
    db.commit()
    corr_run = db.get(PayrollRun, out["correctionRunId"])
    service.advance_payroll_run_status(db, corr_run.id, PREPARER, ch.org.id)     # Review
    service.advance_payroll_run_status(db, corr_run.id, AUTHORIZER, ch.org.id)   # Approved (not the preparer/creator)
    db.commit()

    second = _generate(db, ch, template.id, creator.id)
    db.commit()

    # regeneration superseded the first issue and shows the absorbed correction
    assert first["reportId"] != second["reportId"]
    assert second["supersedesReportIds"] == [first["reportId"]]
    assert db.get(GeneratedReport, first["reportId"]).status == "Superseded"
    db.refresh(march_item)
    boxes = {b["boxCode"]: b for b in second["boxes"]}
    assert D(boxes["BOX_QST_WITHHELD"]["valueExact"]) == D("1120")          # 480 (March) + 640 (April)
    assert len(second["corrections"]) == 1
    corr = second["corrections"][0]
    assert corr["periodStart"] == "2026-03-01" and corr["sequence"] == 1
    assert corr["originalPayslipId"] == march_item.id and corr["reason"] == "TEST tariff code was wrong"


def test_lohnausweis_manual_amendment_is_a_second_approver_reissue(db, ch):  # noqa: F811
    creator, approver = _make_user(db, "la.amend@t.ch"), _make_user(db, "la.amend2@t.ch")
    second = _make_user(db, "la.amend3@t.ch")
    template = _lohnausweis_template(db, creator, approver)
    _approve(db, ch, 3)
    original = _generate(db, ch, template.id, creator.id)
    db.commit()

    amendments = [ChLohnausweisBoxAmend(boxCode="BOX_1", value="16123.50", note="SVA scan received")]
    reissued = svc.amend_ch_lohnausweis(db, ch.org.id, original["reportId"], amendments,
                                        "TEST recorded a later SVA scan", actor_id=creator.id,
                                        second_approver_id=second.id)
    db.commit()
    assert reissued["reportId"] != original["reportId"]
    assert reissued["supersedesReportIds"] == [original["reportId"]]
    assert db.get(GeneratedReport, original["reportId"]).status == "Superseded"
    # the amended issue renders the override EXACT ("16123.50") and rounds it whole-franc,
    # while the superseded report's stored history is untouched
    box = next(b for b in reissued["boxes"] if b["boxCode"] == "BOX_1")
    assert box["valueExact"] == "16123.50" and box["valueFrancs"] == 16124
    stored_orig = db.get(GeneratedReport, original["reportId"]).rendered_data
    assert next(b for b in stored_orig["boxes"] if b["boxCode"] == "BOX_1")["valueExact"] == "8000.00"
    assert len(reissued["amendments"]) == 1 and reissued["amendments"][0]["secondApproverId"] == second.id

    # note-only amendment keeps the exact value
    noted = svc.amend_ch_lohnausweis(db, ch.org.id, reissued["reportId"],
                                     [ChLohnausweisBoxAmend(boxCode="BOX_1", note="paper copy archived")],
                                     "TEST archived paper copy", actor_id=approver.id,
                                     second_approver_id=creator.id)
    db.commit()
    note_box = next(b for b in noted["boxes"] if b["boxCode"] == "BOX_1")
    assert note_box["valueExact"] == "16123.50" and note_box["note"] == "paper copy archived"

    # maker-checker refusals
    with pytest.raises(BadRequestException, match="second approver"):
        svc.amend_ch_lohnausweis(db, ch.org.id, noted["reportId"], amendments,
                                 "TEST no second approver", actor_id=creator.id, second_approver_id=None)
    with pytest.raises(BadRequestException, match="different user"):
        svc.amend_ch_lohnausweis(db, ch.org.id, noted["reportId"], amendments,
                                 "TEST self-approval", actor_id=creator.id, second_approver_id=creator.id)
    with pytest.raises(BadRequestException, match="not a declared Lohnausweis box"):
        svc.amend_ch_lohnausweis(db, ch.org.id, noted["reportId"], [ChLohnausweisBoxAmend(boxCode="BOX_99", value="1")],
                                 "TEST unknown box", actor_id=creator.id, second_approver_id=second.id)


# ── ELM ─────────────────────────────────────────────────────────────────

def test_elm_builds_one_envelope_per_domain_with_four_statuses(db, ch):  # noqa: F811
    _approve(db, ch, 3)
    out = svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3, actor_id=AUTHORIZER)
    db.commit()

    assert out["periodKey"] == "2026-03" and out["transmitEnabled"] is False
    subs = {s["domain"]: s for s in out["submissions"]}
    # AHV/QST/FAK/UVG/BFS have real numbers; KTG (uninsured) gets no empty envelope
    assert set(subs) == {"AHV", "QST", "FAK", "UVG", "BFS"}
    for domain, sub in subs.items():
        assert sub["transportStatus"] == "NOT_SENT"
        assert sub["receiverValidationStatus"] == "SCHEMA_UNAVAILABLE"   # no XSD registered yet
        assert sub["authorityAckStatus"] == "PENDING" and sub["settlementStatus"] == "NOT_SETTLED"
        assert sub["schemaVersion"] == svc.CH_ELM_SCHEMA_VERSION
        assert sub["payload"] and sub["payloadSha256"] == hashlib.sha256(sub["payload"].encode("utf8")).hexdigest()

    qst = subs["QST"]
    assert qst["receiverId"] == "CANTON:CH-ZH" and qst["canton"] == "CH-ZH"
    assert 'ch_qst_total="640"' in qst["payload"]

    ahv = subs["AHV"]
    assert ahv["receiverId"] == "SVA-TEST"                                # compensation office scheme code
    assert 'ch_ahv_employee="' in ahv["payload"] and 'headcount="1"' in ahv["payload"]

    bfs = subs["BFS"]
    assert bfs["receiverId"] == "CH-BFS" and 'headcount="1"' in bfs["payload"]

    filings = {f.filing_type: f for f in db.query(StatutoryFiling).all()}
    assert {"ELM:AHV", "ELM:QST", "ELM:FAK", "ELM:UVG", "ELM:BFS"} <= set(filings)
    assert filings["ELM:QST"].jurisdiction == "CH" and filings["ELM:QST"].submission_status == "PENDING"


def test_elm_build_is_idempotent_and_never_duplicates(db, ch):  # noqa: F811
    _approve(db, ch, 3)
    first = svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3, actor_id=AUTHORIZER)
    db.commit()
    ids = {s["submissionId"] for s in first["submissions"]}
    count = db.query(ChElmSubmission).count()

    again = svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3, actor_id=AUTHORIZER)
    db.commit()
    assert {s["submissionId"] for s in again["submissions"]} == ids            # reused, not re-emitted
    assert db.query(ChElmSubmission).count() == count
    assert len({s["idempotencyKey"] for s in again["submissions"]}) == len(ids)

    # requesting non-committed periods is refused, never silently empty
    with pytest.raises(BadRequestException, match="No committed Swiss payslips"):
        svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=1, actor_id=AUTHORIZER)


def test_elm_xsd_registration_controls_validation_status(db, ch, tmp_path):  # noqa: F811
    _approve(db, ch, 3)
    valid = tmp_path / "elm-ahv.xsd"
    valid.write_text(_elm_valid_xsd(), encoding="utf-8")
    broken = tmp_path / "elm-qst.xsd"
    broken.write_text(_elm_broken_xsd(), encoding="utf-8")

    svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3, actor_id=AUTHORIZER)
    db.commit()
    assert _qst_view(svc.list_ch_elm_submissions(db, ch.org.id, domain="QST"))["receiverValidationStatus"] == \
        "SCHEMA_UNAVAILABLE"

    reg = svc.register_ch_elm_xsd(db, "AHV", str(valid), actor_id=AUTHORIZER)
    db.commit()
    assert reg["domain"] == "AHV" and reg["formNumber"] == "CH-ELM:AHV"
    # re-registering the identical file is idempotent
    same = svc.register_ch_elm_xsd(db, "AHV", str(valid), actor_id=AUTHORIZER)
    db.commit()
    assert same["artifactId"] == reg["artifactId"]

    svc.register_ch_elm_xsd(db, "QST", str(broken), actor_id=AUTHORIZER)
    db.commit()

    out = svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3, actor_id=AUTHORIZER)
    db.commit()
    subs = {s["domain"]: s for s in out["submissions"]}
    assert subs["AHV"]["receiverValidationStatus"] == "VALID"
    assert subs["QST"]["receiverValidationStatus"] == "INVALID"

    # an unknown domain can never be registered
    with pytest.raises(BadRequestException, match="unknown ELM domain"):
        svc.register_ch_elm_xsd(db, "GST", str(valid), actor_id=AUTHORIZER)
    # a missing file is refused
    with pytest.raises(BadRequestException, match="not found"):
        svc.register_ch_elm_xsd(db, "BFS", str(tmp_path / "nope.xsd"), actor_id=AUTHORIZER)


def test_elm_rejection_never_touches_payroll_and_correction_path_stays_committed(db, ch):  # noqa: F811
    run, item = _approve(db, ch, 3)
    qst = _qst_view(svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3, actor_id=AUTHORIZER)["submissions"])
    db.commit()

    frozen = {c: getattr(item, c) for c in ("gross_pay", "total_deductions", "net_pay", "status")}
    ytd_before = _ytd(db, ch.emp, "ch_qst")

    rejected = svc.transition_ch_elm_submission(db, ch.org.id, qst["submissionId"], "REJECT",
                                                reason="TEST wrong tariff reference", actor_id=AUTHORIZER)
    db.commit()
    assert rejected["authorityAckStatus"] == "REJECTED" and rejected["settlementStatus"] == "NOT_SETTLED"
    assert rejected["rejectionDetail"]["reason"] == "TEST wrong tariff reference"

    # nothing about the payroll changed: figures, status, YTD identical
    db.refresh(item)
    assert all(getattr(item, c) in frozen.values() for c in ("gross_pay", "total_deductions", "net_pay", "status"))
    assert _ytd(db, ch.emp, "ch_qst") == ytd_before

    # the committed correction path still works on that same finalized original
    _tariff_b(db, ch)
    out = svc.create_ch_correction(db, ch.org.id, item.id, "TEST tariff code was wrong",
                                   ["ch_qst"], {"ch_qst_tariff_code": "B"}, APPROVER,
                                   idempotency_key=hashlib.sha256(b"rej-cor-1").hexdigest(),
                                   correlation_id="rej-corr")
    db.commit()
    delta = db.get(PayslipItem, out["deltaPayslipId"])
    assert delta is not None and (delta.ch_calculation_snapshot or {}).get("correction", {}).get("sequence") == 1

    # rebuilding links the replacement to the rejected original
    rebuilt = {s["domain"]: s for s in svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3,
                                                                   actor_id=AUTHORIZER)["submissions"]}
    db.commit()
    fresh_qst = rebuilt["QST"]
    assert fresh_qst["correctionOfId"] == qst["submissionId"]
    assert fresh_qst["authorityAckStatus"] == "PENDING" and fresh_qst["settlementStatus"] == "NOT_SETTLED"
    assert fresh_qst["receiverValidationStatus"] == "SCHEMA_UNAVAILABLE"


def test_elm_receive_is_unique_and_transmission_is_gated(db, ch):  # noqa: F811
    _approve(db, ch, 3)
    first = {s["domain"]: s for s in svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3,
                                                                 actor_id=AUTHORIZER)["submissions"]}
    db.commit()

    # RECEIVE marks received + settlement DUE, per domain independent
    ahv = svc.transition_ch_elm_submission(db, ch.org.id, first["AHV"]["submissionId"], "RECEIVE",
                                           receipt_reference="RC-2026-AHV-1", actor_id=AUTHORIZER)
    db.commit()
    assert ahv["authorityAckStatus"] == "RECEIVED" and ahv["settlementStatus"] == "DUE"
    assert ahv["receiptReference"] == "RC-2026-AHV-1"
    filing = db.get(StatutoryFiling, ahv["statutoryFilingId"])
    assert filing.status == "FILED" and filing.submission_status == "RECEIVED" and filing.receipt_id == "RC-2026-AHV-1"

    qst = _qst_view(svc.list_ch_elm_submissions(db, ch.org.id))
    received = svc.transition_ch_elm_submission(db, ch.org.id, qst["submissionId"], "RECEIVE",
                                                receipt_reference="RC-2026-QST-1", actor_id=AUTHORIZER)
    db.commit()
    assert received["authorityAckStatus"] == "RECEIVED" and received["receiptReference"] == "RC-2026-QST-1"

    # the same envelope cannot settle twice
    with pytest.raises(BadRequestException, match="already RECEIVED"):
        svc.transition_ch_elm_submission(db, ch.org.id, qst["submissionId"], "RECEIVE", actor_id=AUTHORIZER)

    # rebuilt originals are reused even after receipt (still one RECEIVED per period)
    again = _qst_view(svc.build_ch_elm_submissions(db, ch.org.id, 2026, month=3, actor_id=AUTHORIZER)["submissions"])
    db.commit()
    assert again["submissionId"] == qst["submissionId"]
    received_qst = [s for s in svc.list_ch_elm_submissions(db, ch.org.id, domain="QST", period_key="2026-03")
                    if s["authorityAckStatus"] == "RECEIVED"]
    assert len(received_qst) == 1

    # a second original for the same (org, domain, period) is refused at settlement
    duplicate = ChElmSubmission(organization_id=ch.org.id, domain="QST", period_key="2026-03",
                                receiver_id="CANTON:CH-ZH", authority_ack_status="PENDING",
                                transport_status="NOT_SENT", settlement_status="NOT_SETTLED",
                                idempotency_key=hashlib.sha256(b"dup-qst-2026-03").hexdigest())
    db.add(duplicate)
    db.commit()
    with pytest.raises(BadRequestException, match="No duplicate settlement"):
        svc.transition_ch_elm_submission(db, ch.org.id, duplicate.id, "RECEIVE",
                                         receipt_reference="RC-X", actor_id=AUTHORIZER)

    # transmission stays a gated NO-OP: no network connection is ever opened
    with pytest.raises(BadRequestException, match="ELM transmission is disabled"):
        svc.transmit_ch_elm_submission(db, ch.org.id, qst["submissionId"], actor_id=AUTHORIZER)


# ── certification guard ─────────────────────────────────────────────────

def test_nothing_claims_a_swissdec_channel(db, ch):  # noqa: F811
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    targets = [root / "app/modules/payroll/switzerland_service.py",
               root / "app/modules/payroll/switzerland_schemas.py",
               root / "app/modules/payroll/engine/countries/switzerland.py",
               root / "app/modules/payroll/engine/countries/switzerland_content.py"]
    for path in targets:
        assert "Swissdec" not in path.read_text(encoding="utf-8"), f"{path.name} must not claim a Swissdec channel"