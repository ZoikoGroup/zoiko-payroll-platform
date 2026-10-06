"""
tests/test_hong_kong_configuration.py
-------------------------------------
Hong Kong statutory configuration administration (Super Admin control plane):
domain grouping, full configuration coverage, version states, "why is this
version selected", version compare, the governed row edit (source + reason,
editable packs only, approval invalidated, audited), the generic-editor
refusal for HK, new versions (the rollback path) and historical isolation.
Users 101 / 202 exist in the PostgreSQL harness.
"""

import csv
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

from tests.test_hong_kong_e2e import MAKER, CHECKER, hk, _employee, _item, _month, _profile  # noqa: F401
from tests.test_hong_kong_governance import SA_A, SA_B, _artifact, _http  # noqa: F401

BACKEND = Path(__file__).resolve().parents[1]
MATRIX = BACKEND.parent / "docs" / "HONG_KONG_RELEASE_EVIDENCE" / "CONFIGURATION" / "HK_CONFIGURATION_MASTER_MATRIX.csv"


def test_every_hk_configuration_row_is_governed_documented_sourced_consumed_and_exposed(db, hk):
    """Coverage test: FOR EVERY HK configuration row — documented? source? version?
    consumer? exposed in Super Admin? effective date? valid lifecycle?"""
    from app.modules.payroll import hk_configuration

    documented = set()
    if MATRIX.is_file():
        documented = {r["KEY"].split(":")[0] for r in csv.DictReader(open(MATRIX, encoding="utf8"))}
    failures = []
    for pack in hk.packs:
        out = hk_configuration.domains(db, pack.id)
        assert out["unmapped"] == [], out["unmapped"]                                   # exposed in a domain tab
        for domain in out["domains"]:
            for r in domain["rows"]:
                where = f"{pack.pack_id}:{r['key']}:{r['label']}"
                if r["key"] != "HK_EARNING_CLASS" and documented and r["key"] not in documented:
                    failures.append(("undocumented", where))
                if not r["source"]:
                    failures.append(("no source artifact", where))
                elif not r["source"]["sha256"] and r["key"] != "eo_week_start_day":   # the only SOURCE_HASH_REQUIRED rows
                    failures.append(("no source hash", where))
                if not r["effectiveFrom"] or not r["effectiveTo"]:
                    failures.append(("no effective window", where))
                consumer = r["consumer"].split(";")[0].split(" (")[0]
                if not (BACKEND / consumer).is_file():
                    failures.append(("consumer missing", where, consumer))
        assert out["pack"]["versionState"] in ("CURRENT_ACTIVE", "PAST_ACTIVE", "NEXT_PUBLISHED", "DRAFT", "FUTURE_DRAFT")
    assert failures == []
    week = [r for r in hk_configuration.domains(db, hk.packs[0].id)["domains"][2]["rows"] if r["key"] == "eo_week_start_day"]
    assert week and week[0]["status"] == "SOURCE_HASH_REQUIRED"                          # never shown as certified


def test_values_are_shown_in_their_statutory_units(db, hk):
    from app.modules.payroll import hk_configuration

    rows = {r["key"]: r for d in hk_configuration.domains(db, hk.packs[0].id)["domains"] for r in d["rows"]}
    assert rows["mpf_employee_rate"]["value"] == "employee 5%" and rows["mpf_employer_rate"]["value"] == "employer 5%"
    assert rows["mpf_min_relevant_income_monthly"]["value"] == "7,100.00" and rows["mpf_min_relevant_income_monthly"]["unit"] == "HKD"
    holidays = [r for d in hk_configuration.domains(db, hk.packs[0].id)["domains"] for r in d["rows"]
                if r["key"] == "HK_STATUTORY_HOLIDAY"]
    assert holidays and all(len(h["value"]) == 10 and h["value"][4] == "-" for h in holidays)   # actual dates
    tax = next(d for d in hk_configuration.domains(db, hk.packs[0].id)["domains"] if d["key"] == "salaries_tax")
    assert tax["notice"].startswith("Informational calculation only")


def test_version_states_and_why_a_version_is_selected(db, hk):
    from app.modules.payroll import hk_configuration

    states = {v["packId"]: v["versionState"] for v in hk_configuration.versions(db, on=date(2026, 10, 1))}
    assert states == {"HK-PAYROLL-2025": "PAST_ACTIVE", "HK-PAYROLL-2026": "CURRENT_ACTIVE"}
    assert {v["packId"]: v["versionState"] for v in hk_configuration.versions(db, on=date(2026, 1, 1))}["HK-PAYROLL-2026"] == "NEXT_PUBLISHED"
    why = hk_configuration.explain_resolution(db, date(2025, 6, 1))
    assert why["pack"]["packId"] == "HK-PAYROLL-2025" and why["yearOfAssessment"] == "2025/26"
    assert {t["reportType"]: t["yearKey"] for t in why["templates"]}["HK_EMPF_REMITTANCE"] == "2025"
    none = hk_configuration.explain_resolution(db, date(2031, 1, 1))
    assert none["pack"] is None and "blocked" in none["outcome"]


def test_compare_two_years_shows_the_statutory_changes(db, hk):
    from app.modules.payroll import hk_configuration

    diff = hk_configuration.compare(db, hk.packs[0].id, hk.packs[1].id)
    changed = {c["key"]: c for c in diff["changed"]}
    assert changed["hk_allowance_basic"]["changes"]["value"] == {"from": "132,000.00", "to": "145,000.00"}
    assert any(r["key"] == "HK_STATUTORY_HOLIDAY" for r in diff["added"])                 # 2027 calendar entries
    # a row spanning its own pack's year is not a "change" (found in the generated version register)
    assert all(not ({"effectiveFrom", "effectiveTo"} & set(c["changes"])) or c["key"].startswith("smw_")
               for c in diff["changed"]), [c for c in diff["changed"] if "effectiveFrom" in c["changes"]]
    same = hk_configuration.compare(db, hk.packs[0].id, hk.packs[0].id)
    assert same["added"] == same["removed"] == same["changed"] == [] and same["unchanged"] > 100


def test_governed_edit_rules_and_the_generic_editor_refusal(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_configuration, service
    from app.modules.payroll.models import ContributionRate, JurisdictionPack, TaxConfigurationAudit
    from app.modules.payroll.schemas import CanonicalContributionRateUpsert

    active_rate = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == hk.packs[1].id,
                                                     ContributionRate.component_key == "mpf_employee_rate").one())
    src = _artifact(db, "HK-SOURCE-TEST")
    with pytest.raises(BadRequestException, match="no\\s+longer editable"):                # Active: never in place
        hk_configuration.update_row(db, "rate", active_rate.id, {"employeeRatePct": "0.06", "reason": "x",
                                                                 "sourceDocumentId": src.id}, SA_A.id)
    db.rollback()
    draft = hk_configuration.new_version(db, hk.packs[1].id, "1.1", "test change", SA_A.id)
    assert draft.status == "Draft" and db.get(JurisdictionPack, hk.packs[1].id).status == "Active"
    rate = (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == draft.id,
                                              ContributionRate.component_key == "mpf_employee_rate").one())
    with pytest.raises(BadRequestException, match="change reason"):
        hk_configuration.update_row(db, "rate", rate.id, {"employeeRatePct": "0.06", "sourceDocumentId": src.id}, SA_A.id)
    with pytest.raises(BadRequestException, match="source document"):
        hk_configuration.update_row(db, "rate", rate.id, {"employeeRatePct": "0.06", "reason": "x"}, SA_A.id)
    with pytest.raises(BadRequestException, match="cannot be before"):
        hk_configuration.update_row(db, "rate", rate.id, {"effectiveFrom": "2027-01-01", "effectiveTo": "2026-12-31",
                                                          "reason": "x", "sourceDocumentId": src.id}, SA_A.id)
    with pytest.raises(BadRequestException, match="not editable here"):
        hk_configuration.update_row(db, "rate", rate.id, {"componentKey": "x", "reason": "x", "sourceDocumentId": src.id}, SA_A.id)
    service.set_jurisdiction_pack_approver(db, draft.id, actor_id=SA_B.id)
    out = hk_configuration.update_row(db, "rate", rate.id, {"employeeRatePct": "0.06", "reason": "TEST value",
                                                            "sourceDocumentId": src.id}, SA_A.id)
    assert out["value"] == "employee 6%" and out["source"]["id"] == src.id
    assert db.get(JurisdictionPack, draft.id).approved_by_id is None                          # edit invalidates approval
    audit = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "hk_statutory_rate")
             .order_by(TaxConfigurationAudit.id.desc()).first())
    assert audit.reason == "TEST value" and audit.new_value["employeeRatePct"] == "0.06" and audit.actor_id == SA_A.id
    with pytest.raises(BadRequestException, match="Statutory Configuration"):                   # generic editor refused for HK
        service.upsert_canonical_contribution_rate(db, CanonicalContributionRateUpsert(
            id=rate.id, jurisdictionPackId=draft.id, jurisdictionCountry="HK", componentKey="mpf_employee_rate",
            label="x", employeeSharePct="0.07"), actor_id=SA_A.id)


def test_new_version_is_a_full_draft_copy_and_never_reaches_payroll(db, hk):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import hk_configuration
    from app.modules.payroll.models import ContributionRate, TaxSlab

    before = _item(db, _month(db, hk.org, 5, year=2026), hk.emp)
    draft = hk_configuration.new_version(db, hk.packs[1].id, "2.0", "rollback rehearsal", SA_A.id)
    for model in (ContributionRate, TaxSlab):
        n_src = db.query(model).filter(model.jurisdiction_pack_id == hk.packs[1].id, model.organization_id.is_(None)).count()
        n_new = db.query(model).filter(model.jurisdiction_pack_id == draft.id, model.organization_id.is_(None)).count()
        assert n_src == n_new and n_new > 0
    with pytest.raises(BadRequestException, match="already exists"):
        hk_configuration.new_version(db, hk.packs[1].id, "2.0", "again", SA_A.id)
    with pytest.raises(BadRequestException, match="reason"):
        hk_configuration.new_version(db, hk.packs[1].id, "2.1", "", SA_A.id)
    after = _item(db, _month(db, hk.org, 5, year=2026), hk.emp)
    assert after.tax_policy_pack_id == before.tax_policy_pack_id == hk.packs[1].id            # a Draft is never selected


def test_configuration_routes_over_http(db, hk):
    from app.modules.payroll import hk_configuration

    draft = hk_configuration.new_version(db, hk.packs[1].id, "1.5", "http test", SA_A.id)
    src = _artifact(db, "HK-SOURCE-HTTP")
    operator = SimpleNamespace(id=MAKER.id, organization_id=hk.org.id, role="payroll_admin", is_active=True)
    base = "/api/super-admin/compliance/hong-kong/configuration"
    with _http(db, operator) as c:
        assert c.get(f"{base}/versions").status_code == 403
    with _http(db, SA_A) as c:
        assert len(c.get(f"{base}/versions").json()) == 3
        doms = c.get(f"{base}/packs/{draft.id}").json()
        assert doms["pack"]["editable"] is True and len(doms["domains"]) == 10
        rate = next(r for d in doms["domains"] for r in d["rows"] if r["key"] == "smw_hourly_rate")
        res = c.put(f"{base}/rows/rate/{rate['id']}", json={"flatAmount": "43.10", "reason": "x", "sourceDocumentId": src.id,
                                                            "label": "not allowed"})
        assert res.status_code == 422                                                         # extra fields refused
        res = c.put(f"{base}/rows/rate/{rate['id']}", json={"flatAmount": "43.10", "reason": "TEST", "sourceDocumentId": src.id})
        assert res.status_code == 200, res.text
        assert c.get(f"{base}/resolution", params={"on": "2026-06-01"}).json()["pack"]["version"] == "1.0"
        assert c.get(f"{base}/compare", params={"from": hk.packs[1].id, "to": draft.id}).json()["changed"]
        assert c.post(f"{base}/packs/{draft.id}/new-version", json={"version": "1.6", "reason": "r"}).status_code == 200
        assert c.get(f"{base}/packs/999999").status_code == 404
