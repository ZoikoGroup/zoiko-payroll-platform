"""
tests/test_hong_kong_control.py
-------------------------------
Hong Kong platform control records (production-readiness pass): the IRD
software-approval register, the IRD external-submission record (submission
modes, authorized signer, eTAX / control-list references), amendment types,
the IRD data-file lifecycle view, the eMPF configuration (no secrets, four-
eyes activation, certification evidence), the retention framework (blocked
until D-2 / D-3) and the production readiness center. Users 101 / 202 exist
in the PostgreSQL harness.
"""

from datetime import date, timedelta
from types import SimpleNamespace

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk, _employee, _item, _month, _profile, _specialist_verified  # noqa: F401
from tests.test_hong_kong_governance import SA_A, SA_B, _artifact, _http  # noqa: F401

SIGNED = {"authorizedSigner": "Director (test)"}


def _validated_ir56b(db, hk):
    from app.modules.payroll import hong_kong_service

    for m in (1, 2, 3):
        _month(db, hk.org, m)
    out = hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    case = hong_kong_service._case(db, hk.org.id, out["employees"][0]["caseId"])
    hong_kong_service.transition_ird_case(db, hk.org.id, case.id, "VALIDATED", MAKER.id)
    return case


def _approve_software(db, forms=("BIR56A", "IR56B"), expires=None):
    from app.modules.payroll import hong_kong_service

    hong_kong_service.transition_software_approval(db, "APPLICATION_PREPARED", {
        "reason": "TEST", "formsCovered": list(forms), "specificationVersion": "TEST-SPEC"}, SA_A.id)
    hong_kong_service.transition_software_approval(db, "APPLICATION_SUBMITTED", {
        "reason": "TEST", "applicationReference": "TEST-APP-1"}, SA_A.id)
    hong_kong_service.transition_software_approval(db, "TEST_DATA_SUBMITTED", {"reason": "TEST"}, SA_A.id)
    letter = _artifact(db, "HK-IRD-SOFTWARE-APPROVAL-TEST")
    return hong_kong_service.transition_software_approval(db, "APPROVAL_RECEIVED", {
        "reason": "TEST", "approvalReference": "TEST-APPROVAL", "approvalDocumentId": letter.id,
        "approvalReceivedOn": date.today().isoformat(), "expiresOn": expires}, SA_B.id)


def test_software_approval_register_lifecycle_and_evidence_rules(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service

    view = hong_kong_service.software_approval(db)
    assert view["status"] == "NOT_APPLIED" and view["dataFileSubmissionPermitted"] is False
    assert hong_kong_service.software_approval_refusal(db, "IR56B", date.today())
    with pytest.raises(BadRequestException, match="cannot move from NOT_APPLIED to APPROVAL_RECEIVED"):
        hong_kong_service.transition_software_approval(db, "APPROVAL_RECEIVED", {"reason": "x"}, SA_A.id)
    with pytest.raises(BadRequestException, match="formsCovered"):
        hong_kong_service.transition_software_approval(db, "APPLICATION_PREPARED", {"reason": "x", "formsCovered": ["IR56M"],
                                                                             "specificationVersion": "s"}, SA_A.id)
    with pytest.raises(BadRequestException, match="reason"):
        hong_kong_service.transition_software_approval(db, "APPLICATION_PREPARED", {"formsCovered": ["IR56B"]}, SA_A.id)
    hong_kong_service.transition_software_approval(db, "APPLICATION_PREPARED", {
        "reason": "TEST", "formsCovered": ["IR56B"], "specificationVersion": "TEST-SPEC"}, SA_A.id)
    hong_kong_service.transition_software_approval(db, "APPLICATION_SUBMITTED", {"reason": "TEST", "applicationReference": "A"}, SA_A.id)
    hong_kong_service.transition_software_approval(db, "TEST_DATA_SUBMITTED", {"reason": "TEST"}, SA_A.id)
    self_reviewed = _artifact(db, "HK-IRD-SOFTWARE-APPROVAL-TEST", uploader=101, reviewer=101)
    good = _artifact(db, "HK-IRD-SOFTWARE-APPROVAL-TEST")
    base = {"reason": "TEST", "approvalReference": "R", "approvalReceivedOn": date.today().isoformat()}
    with pytest.raises(BadRequestException, match="other than its uploader"):
        hong_kong_service.transition_software_approval(db, "APPROVAL_RECEIVED", {**base, "approvalDocumentId": self_reviewed.id}, SA_B.id)
    with pytest.raises(BadRequestException, match="other than the one who prepared"):
        hong_kong_service.transition_software_approval(db, "APPROVAL_RECEIVED", {**base, "approvalDocumentId": good.id}, SA_A.id)
    with pytest.raises(BadRequestException, match="future"):
        hong_kong_service.transition_software_approval(db, "APPROVAL_RECEIVED", {
            **base, "approvalReceivedOn": (date.today() + timedelta(days=1)).isoformat(), "approvalDocumentId": good.id}, SA_B.id)
    out = hong_kong_service.transition_software_approval(db, "APPROVAL_RECEIVED", {
        **base, "approvalDocumentId": good.id, "expiresOn": (date.today() + timedelta(days=30)).isoformat()}, SA_B.id)
    assert out["status"] == "APPROVAL_RECEIVED" and out["documentSha256"] == "0" * 64
    assert hong_kong_service.software_approval_refusal(db, "IR56B", date.today()) is None
    assert "does not cover BIR56A" in hong_kong_service.software_approval_refusal(db, "BIR56A", date.today())
    later = date.today() + timedelta(days=31)
    assert hong_kong_service.software_approval(db, later)["status"] == "APPROVAL_EXPIRED"         # expiry never ignored
    assert "APPROVAL_EXPIRED" in hong_kong_service.software_approval_refusal(db, "IR56B", later)
    hong_kong_service.transition_software_approval(db, "APPROVAL_REVOKED", {"reason": "TEST revoked"}, SA_A.id)
    assert hong_kong_service.software_approval_refusal(db, "IR56B", date.today())


def test_filing_records_how_the_employer_submitted_and_never_claims_ird_approval(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service

    case = _validated_ir56b(db, hk)
    assert hong_kong_service.xml_lifecycle_state(db, case) == "VALIDATED"          # internal validation != submittable
    file = lambda sub: hong_kong_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id,  # noqa: E731
                                                      filing_reference="F-1", submission=sub)
    with pytest.raises(BadRequestException, match="submission mode is required"):
        file(None)
    with pytest.raises(BadRequestException, match="authorized signer"):
        file({"submissionMode": "INTERNAL_PREPARATION_ONLY"})
    with pytest.raises(BadRequestException, match="eTAX transaction reference"):
        file({"submissionMode": "ONLINE_MODE", **SIGNED})
    with pytest.raises(BadRequestException, match="control list"):
        file({"submissionMode": "MIXED_MODE", **SIGNED})
    with pytest.raises(BadRequestException, match="IRD software approval is NOT_APPLIED"):
        file({"submissionMode": "ONLINE_MODE", "transactionReference": "T-1", **SIGNED})
    with pytest.raises(BadRequestException, match="future"):
        file({"submissionMode": "INTERNAL_PREPARATION_ONLY", "submittedOn": (date.today() + timedelta(days=2)).isoformat(), **SIGNED})
    _approve_software(db)
    assert hong_kong_service.xml_lifecycle_state(db, case) == "READY_FOR_EXTERNAL_SUBMISSION"
    file({"submissionMode": "ONLINE_MODE", "transactionReference": "T-1", **SIGNED})
    out = hong_kong_service.serialize_ird_case(case)
    assert (out["submissionMode"], out["transactionReference"], out["authorizedSigner"]) == ("ONLINE_MODE", "T-1", "Director (test)")
    assert out["xmlLifecycleState"] == "SUBMITTED_EXTERNALLY" and out["uploadedById"] == CHECKER.id
    assert out["amendmentType"] == "ORIGINAL"
    history = hong_kong_service.ird_case_history(db, hk.org.id, case.id)
    assert history[-1]["to"] == "FILED"
    with pytest.raises(BadRequestException, match="SUPPLEMENTARY returns are not supported"):
        hong_kong_service.amend_ird_case(db, hk.org.id, case.id, "TEST", MAKER.id, amendment_type="SUPPLEMENTARY")
    with pytest.raises(BadRequestException, match="REPLACEMENT or SUPPLEMENTARY"):
        hong_kong_service.amend_ird_case(db, hk.org.id, case.id, "TEST", MAKER.id, amendment_type="ADDITIONAL")
    amendment = hong_kong_service.amend_ird_case(db, hk.org.id, case.id, "TEST late bonus", MAKER.id)
    # Corrected lifecycle: the filed original stays in force (AMENDMENT_REQUIRED)
    # until its replacement is filed; it is superseded only then.
    assert amendment.amendment_type == "REPLACEMENT" and hong_kong_service.xml_lifecycle_state(db, case) == "AMENDMENT_REQUIRED"
    assert hong_kong_service.xml_lifecycle_state(db, amendment) == "DRAFT"


def test_ir56b_first_prepared_after_the_cover_was_filed_is_additional(db, hk):
    from app.modules.payroll import hong_kong_service
    from app.modules.payroll.models import HongKongIrdReportingCase

    out = hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)        # no payroll yet: cover only
    cover = db.get(HongKongIrdReportingCase, out["bir56aCaseId"])
    cover.status, cover.validation_errors = "FILED", []                                 # TEST: the cover is already filed
    db.commit()
    for m in (1, 2, 3):
        _month(db, hk.org, m)
    out = hong_kong_service.generate_annual_return(db, hk.org.id, "2025/26", MAKER.id)
    late = db.get(HongKongIrdReportingCase, out["employees"][0]["caseId"])
    assert late.form_type == "IR56B" and late.amendment_type == "ADDITIONAL"


def test_empf_configuration_holds_no_secrets_and_activates_four_eyes(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service

    assert hong_kong_service.empf_configurations(db)["active"] is None
    base = {"submissionMethod": "EMPF_PORTAL_MANUAL", "environment": "PRODUCTION", "reason": "TEST"}
    for bad in ({"endpointReference": "https://user:pw@empf.example"}, {"formatVersion": "password=abc"},
                {"endpointReference": "-----BEGIN PRIVATE KEY-----"}):
        with pytest.raises(BadRequestException, match="secret"):
            hong_kong_service.create_empf_configuration(db, {**base, **bad}, SA_A.id)
    with pytest.raises(BadRequestException, match="credentialStatus"):
        hong_kong_service.create_empf_configuration(db, {**base, "credentialStatus": "abc123"}, SA_A.id)
    with pytest.raises(BadRequestException, match="certification evidence"):
        hong_kong_service.create_empf_configuration(db, {**base, "submissionMethod": "EMPF_API"}, SA_A.id)
    v1 = hong_kong_service.create_empf_configuration(db, base, SA_A.id)
    assert v1["status"] == "DRAFT" and v1["certificationStatus"] == "NOT_CERTIFIED" and v1["version"] == 1
    with pytest.raises(BadRequestException, match="other than its maker"):
        hong_kong_service.activate_empf_configuration(db, v1["id"], SA_A.id, "TEST")
    hong_kong_service.activate_empf_configuration(db, v1["id"], SA_B.id, "TEST")
    evidence = _artifact(db, "HK-EMPF-CERTIFICATION-TEST")
    v2 = hong_kong_service.create_empf_configuration(db, {**base, "submissionMethod": "EMPF_API", "certificationEvidenceId": evidence.id,
                                                   "credentialStatus": "CONFIGURED_IN_SECRET_STORE"}, SA_A.id)
    assert v2["certificationStatus"] == "CERTIFIED" and v2["version"] == 2
    hong_kong_service.activate_empf_configuration(db, v2["id"], SA_B.id, "TEST")
    view = hong_kong_service.empf_configurations(db)
    assert view["active"]["version"] == 2 and [v["status"] for v in view["versions"]] == ["ACTIVE", "SUPERSEDED"]
    with pytest.raises(BadRequestException, match="only a DRAFT"):
        hong_kong_service.activate_empf_configuration(db, v1["id"], SA_B.id, "TEST")


def test_retention_is_blocked_until_the_owner_decides_and_then_four_eyes(db, hk):
    from app.modules.payroll import retention_service
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service

    view = retention_service.retention_policies(db, "HK")
    assert all(c["state"] == "BLOCKED_UNDECIDED" and not c["purgePermitted"] for c in view["categories"])
    assert "D-2" in retention_service.purge_refusal(db, "HK", "PAYROLL_RECORDS")
    proposal = {"recordCategory": "PAYROLL_RECORDS", "retentionYears": 7, "endOfRetention": "DELETE",
                "legalBasis": "TEST basis", "reason": "TEST"}
    with pytest.raises(BadRequestException, match="D-2"):
        retention_service.propose_retention_policy(db, "HK", proposal, SA_A.id)
    _artifact(db, "HK-DECISION-D-2")
    with pytest.raises(BadRequestException, match="D-3"):
        retention_service.propose_retention_policy(db, "HK", proposal, SA_A.id)
    _artifact(db, "HK-DECISION-D-3")
    with pytest.raises(BadRequestException, match="whole number"):
        retention_service.propose_retention_policy(db, "HK", {**proposal, "retentionYears": 0}, SA_A.id)
    draft = retention_service.propose_retention_policy(db, "HK", proposal, SA_A.id)
    assert retention_service.purge_refusal(db, "HK", "PAYROLL_RECORDS")                         # a DRAFT never permits a purge
    with pytest.raises(BadRequestException, match="other than its maker"):
        retention_service.approve_retention_policy(db, "HK", draft["id"], SA_A.id)
    retention_service.approve_retention_policy(db, "HK", draft["id"], SA_B.id)
    assert retention_service.purge_refusal(db, "HK", "PAYROLL_RECORDS") is None
    assert retention_service.purge_refusal(db, "HK", "MPF_RECORDS")                              # other categories stay blocked


def test_readiness_center_is_derived_and_not_production_ready(db, hk):
    from app.modules.payroll import hong_kong_service

    out = hong_kong_service.readiness_center(db)
    assert out["productionReady"] is False and out["classification"].startswith("NOT PRODUCTION READY")
    keys = {i["key"]: i for i in out["items"]}
    for k in ("GATE_G1", "GATE_G7", "ACTIVE_PACK", "GOLDEN", "IRD_SOFTWARE_APPROVAL", "EMPF_CONFIGURATION",
              "EMPF_CERTIFICATION", "RETENTION", "DECISION_D-2", "PROD_DB", "PROD_BACKUP_RESTORE", "PROD_MONITORING"):
        assert k in keys, k
    assert keys["GATE_G1"]["status"] == "BLOCKED" and keys["GATE_G1"]["blockerReason"]
    assert keys["IRD_SOFTWARE_APPROVAL"]["status"] == "BLOCKED" and keys["PROD_DB"]["status"] == "PENDING"
    assert keys["DECISION_D-14"]["status"] == "NOT_APPLICABLE"                      # shared-platform, not launch-blocking
    assert all(i["status"] in ("PASS", "FAIL", "PENDING", "BLOCKED", "NOT_APPLICABLE") and i["owner"] and i["nextAction"]
               for i in out["items"])
    assert sum(out["counts"].values()) == out["total"]


def test_control_routes_are_super_admin_only_and_refuse_secret_fields(db, hk):
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    base = "/api/super-admin/compliance/hong-kong"
    with _http(db, operator) as c:
        for path in ("/ird-software-approval", "/empf-configuration", "/retention-policies", "/readiness-center"):
            assert c.get(base + path).status_code == 403, path
    with _http(db, SA_A) as c:
        assert c.get(f"{base}/ird-software-approval").json()["status"] == "NOT_APPLIED"
        assert c.get(f"{base}/readiness-center").json()["productionReady"] is False
        res = c.post(f"{base}/empf-configuration", json={"submissionMethod": "EMPF_PORTAL_MANUAL", "environment": "TEST",
                                                         "reason": "TEST", "password": "x"})
        assert res.status_code == 422                                              # a secret field cannot even be sent
        res = c.post(f"{base}/empf-configuration", json={"submissionMethod": "EMPF_PORTAL_MANUAL", "environment": "TEST",
                                                         "reason": "TEST"})
        assert res.status_code == 200 and res.json()["status"] == "DRAFT"
        res = c.post(f"{base}/ird-software-approval/transition", json={"target": "APPLICATION_PREPARED", "reason": "TEST",
                                                                      "formsCovered": ["IR56B"], "specificationVersion": "S"})
        assert res.status_code == 200 and res.json()["status"] == "APPLICATION_PREPARED"
        res = c.post(f"{base}/retention-policies", json={"recordCategory": "PAYROLL_RECORDS", "retentionYears": 7,
                                                         "endOfRetention": "DELETE", "legalBasis": "x", "reason": "x"})
        assert res.status_code == 400 and "D-2" in res.text


def test_parallel_run_comparison_is_read_only_and_never_explains_a_variance(db, hk):
    from decimal import Decimal

    from scripts.hk_parallel_run_compare import compare

    item = _item(db, _month(db, hk.org, 5, year=2026), hk.emp)
    trace = item.hk_calculation_trace["result"]
    base = {"cycle": "1", "period": "2026-05", "employee_ref": hk.emp.employee_code, "category": "within MPF levels",
            "tolerance": "0.00"}
    rows = [
        {**base, "measure": "mpf_employee", "reference_value": trace["mpfEmployee"]},
        {**base, "measure": "mpf_employer", "reference_value": str(Decimal(trace["mpfEmployer"]) + 1)},
        {**base, "measure": "net_pay", "reference_value": str(Decimal(str(item.net_pay)) - 1), "classification": "EXPLAINED",
         "explanation": "TEST reviewer-confirmed reference error"},
        {**base, "measure": "income_tax_withheld", "reference_value": "0"},
        {**base, "measure": "final_wages", "reference_value": "100"},
        {**base, "employee_ref": "NOPE", "measure": "gross_paid", "reference_value": "1"},
        {**base, "measure": "gross_paid", "reference_value": ""},
    ]
    out = compare(db, hk.org.id, rows)
    assert [r["classification"] for r in out] == ["WITHIN_TOLERANCE", "UNEXPLAINED", "EXPLAINED", "WITHIN_TOLERANCE",
                                                  "MANUAL_REVIEW", "UNEXPLAINED", "UNEXPLAINED"]
    assert out[1]["variance"] == "-1.00" and out[1]["within_tolerance"] == "NO"
    assert out[4]["explanation"].startswith("compare from: termination statement")
    assert out[5]["zoiko_value"] == "EMPLOYEE_NOT_FOUND" and out[6]["within_tolerance"] == "NO_REFERENCE"
    assert not db.dirty and not db.new                                               # read-only


def test_one_version_through_the_whole_lifecycle_with_every_gate(db, hk):
    """Draft → In Review → QA → Approved → Active → Superseded, and Retired: every
    stage on one HK version, with its gate. PUBLISHED is an Active version whose
    window starts later (NEXT_PUBLISHED); an Active version is never edited in
    place; the replaced version stays readable and pinned for its own payroll."""
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hong_kong_service, service
    from app.modules.payroll.models import ContributionRate, JurisdictionPack

    old = hk.packs[1]
    before = _item(db, _month(db, hk.org, 5, year=2026), hk.emp)
    assert service.run_golden_test_certification(db, jurisdiction_country="HK", actor_id=SA_B.id).status == "PASS"
    draft = hong_kong_service.new_version(db, old.id, "1.1", "TEST lifecycle", SA_A.id)
    for status in ("In Review", "QA"):
        service.set_jurisdiction_pack_status(db, draft.id, status, actor_id=SA_A.id)
        assert db.get(JurisdictionPack, draft.id).status == status
    service.set_jurisdiction_pack_status(db, draft.id, "Approved", actor_id=SA_A.id)
    service.set_jurisdiction_pack_approver(db, draft.id, actor_id=SA_B.id)            # approver ≠ maker, last step
    with pytest.raises(BadRequestException, match="overlap"):                          # never two in force
        service.set_jurisdiction_pack_status(db, draft.id, "Active", actor_id=SA_A.id)
    db.rollback()
    service.set_jurisdiction_pack_status(db, old.id, "Superseded", actor_id=SA_A.id)    # governed rollover
    with pytest.raises(BadRequestException, match="G1"):                               # G1 evidence first
        service.set_jurisdiction_pack_status(db, draft.id, "Active", actor_id=SA_A.id)
    db.rollback()
    _artifact(db, "HK-GATE-G1")
    with pytest.raises(BadRequestException, match="not source-verified"):              # unverified rows never go Active
        service.set_jurisdiction_pack_status(db, draft.id, "Active", actor_id=SA_A.id)
    db.rollback()
    _specialist_verified(db, draft, SA_A.id)                                           # resets the approval
    service.set_jurisdiction_pack_approver(db, draft.id, actor_id=SA_B.id)
    with pytest.raises(BadRequestException, match="approved this pack cannot also activate"):
        service.set_jurisdiction_pack_status(db, draft.id, "Active", actor_id=SA_B.id)
    db.rollback()
    service.set_jurisdiction_pack_status(db, draft.id, "Active", actor_id=SA_A.id)      # activator ≠ approver
    assert db.get(JurisdictionPack, draft.id).status == "Active"
    states = {(v["packId"], v["version"]): v["versionState"] for v in hong_kong_service.versions(db, date(2026, 6, 1))}
    assert states[("HK-PAYROLL-2026", "1.1")] == "CURRENT_ACTIVE" and states[("HK-PAYROLL-2026", "1.0")] == "SUPERSEDED"
    rate = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == draft.id,
                                              ContributionRate.component_key == "mpf_employee_rate").one())
    with pytest.raises(BadRequestException, match="no\\s+longer editable"):            # immutable once Active
        hong_kong_service.update_row(db, "rate", rate.id, {"employeeRatePct": "0.06", "reason": "x",
                                                          "sourceDocumentId": _artifact(db, "HK-SRC").id}, SA_A.id)
    db.rollback()
    with pytest.raises(BadRequestException, match="cannot move directly"):             # no Active → Draft
        service.set_jurisdiction_pack_status(db, draft.id, "Draft", actor_id=SA_A.id)
    db.rollback()
    with pytest.raises(BadRequestException, match="final"):                            # Superseded is final
        service.set_jurisdiction_pack_status(db, old.id, "Active", actor_id=SA_A.id)
    db.rollback()
    assert db.get(JurisdictionPack, before.tax_policy_pack_id).id == old.id             # history keeps its pack
    service.set_jurisdiction_pack_status(db, hk.packs[0].id, "Retired", actor_id=SA_A.id)
    assert hong_kong_service.versions(db, date(2026, 6, 1))[0]["versionState"] == "RETIRED"
    with pytest.raises(BadRequestException, match="final"):
        service.set_jurisdiction_pack_status(db, hk.packs[0].id, "Active", actor_id=SA_A.id)


def test_monitoring_signals_count_overdue_obligations_without_employee_data(db, hk):
    from app.modules.payroll import hong_kong_service

    calm = hong_kong_service.monitoring_signals(db, date(2026, 1, 1))
    assert calm["alerts"] == 0 and {s["key"] for s in calm["signals"]} >= {"IRD_OVERDUE", "EMPF_PAST_CONTRIBUTION_DAY",
                                                                            "IR56G_DEADLINE_PASSED", "LEGAL_HOLDS_ACTIVE"}
    case = _validated_ir56b(db, hk)                                     # due 2026-05-01 (pack timing)
    late = hong_kong_service.monitoring_signals(db, case.due_date + timedelta(days=1))
    overdue = next(s for s in late["signals"] if s["key"] == "IRD_OVERDUE")
    assert overdue["value"] >= 1 and overdue["alert"] is True and late["alerts"] >= 1
    assert all(set(s) == {"key", "label", "value", "threshold", "alert"} for s in late["signals"])   # counts only
    hong_kong_service.transition_ird_case(db, hk.org.id, case.id, "FILED", CHECKER.id, filing_reference="F-M",
                                   submission={"submissionMode": "INTERNAL_PREPARATION_ONLY", **SIGNED})
    after = hong_kong_service.monitoring_signals(db, case.due_date + timedelta(days=1))
    assert next(s for s in after["signals"] if s["key"] == "IRD_OVERDUE")["value"] == overdue["value"] - 1
