"""Completion W5-4: a SEPARACION earning classification is refused at
approval (gap register A13), and refusals that are not calculations are worded
"Mexico action refused" (OOS-11) while keeping the same error type, handler and
status code. SYNTHETIC data."""

import ast
from pathlib import Path

import pytest

from tests.test_mexico_router import BASE, SA_A, SA_B, _http

PAYROLL = Path(__file__).resolve().parents[1] / "app" / "modules" / "payroll"
ACTION_MODULES = ("mexico_transfer_service", "mexico_pilot_service", "mexico_filing_service", "mexico_journal_service",
                  "mexico_payment_service", "mexico_authority_lifecycle", "mexico_cfdi_service", "mexico_pac",
                  "mexico_imss_service")


def test_a_separacion_classification_is_refused_at_approval_and_audited(db, organization):
    from app.modules.payroll.models import PayrollMxEarningClassification as C, TaxConfigurationAudit

    payload = {"organizationId": organization.id, "earningCode": "SEP", "label": "SYNTHETIC separation",
               "effectiveFrom": "2026-01-01", "isrTreatment": "TAXABLE", "sbcTreatment": "VARIABLE",
               "infonavitIncluded": False, "isnDefaultIncluded": False, "ptuWageBaseIncluded": False,
               "cfdiNodeType": "SEPARACION"}
    with _http(db, SA_A) as c:
        created = c.post(f"{BASE}/earning-classifications", json=payload)
    assert created.status_code == 200 and created.json()["status"] == "DRAFT", created.text
    with _http(db, SA_B) as c:
        refused = c.post(f"{BASE}/earning-classifications/{created.json()['id']}/approve")
    assert refused.status_code == 400 and "SEPARACION classification is never approved" in refused.text
    db.expire_all()
    assert db.get(C, created.json()["id"]).status == "DRAFT"
    audit = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "mx_earning_classification")
             .order_by(TaxConfigurationAudit.id.desc()).first())
    assert audit is not None and "SEPARACION" in str(audit.reason or audit.new_value)


def test_an_action_refusal_keeps_its_type_and_handling_but_not_the_calculation_wording():
    from app.modules.payroll.engine.countries.mexico import MXBlock, MXRefuse
    from app.modules.payroll.engine.countries.shared import MissingComplianceConfigurationError

    e = MXRefuse("MX_FOUR_EYES_REQUIRED", "a second Super Admin is needed")
    assert isinstance(e, MXBlock) and isinstance(e, MissingComplianceConfigurationError)
    assert str(e) == "Mexico action refused (MX_FOUR_EYES_REQUIRED): a second Super Admin is needed"
    assert (e.key, e.reason, e.reasons) == ("MX_FOUR_EYES_REQUIRED", "a second Super Admin is needed",
                                            [("MX_FOUR_EYES_REQUIRED", "a second Super Admin is needed")])
    assert str(MXBlock("MX_X", "y")).startswith("Mexico calculation blocked")


@pytest.mark.parametrize("module", ACTION_MODULES)
def test_non_calculation_services_raise_action_refusals_only(module):
    tree = ast.parse((PAYROLL / f"{module}.py").read_text(encoding="utf-8"))
    raised = [n.exc.func.id for n in ast.walk(tree) if isinstance(n, ast.Raise) and isinstance(n.exc, ast.Call)
              and isinstance(n.exc.func, ast.Name)]
    assert "MXBlock" not in raised and "MexicoCalculationBlockedError" not in raised


def test_a_four_eyes_refusal_reads_as_an_action_over_http(db):
    with _http(db, SA_A) as c:
        proposed = c.post(f"{BASE}/onboarding-pause", json={"action": "PAUSE", "reason": "SYNTHETIC"})
        assert proposed.status_code == 200, proposed.text
        refused = c.post(f"{BASE}/onboarding-pause/{proposed.json()['id']}/approve")
    assert refused.status_code == 400
    assert "Mexico action refused (MX_FOUR_EYES_REQUIRED)" in refused.text and "calculation" not in refused.text
