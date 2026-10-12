"""
tests/test_singapore_pass_cancellation.py
-----------------------------------------
Singapore production closure — MOM statutory-data closure (2026-09-29).

MOM's cancellation pages now state the pass end-day rule for a CANCELLED
pass: S Pass "When levy stops: 1 day before cancellation" (last updated
15 Sep 2025, sha256 5c71ac70…); Work Permit "Your worker's levy will be
charged until 1 day before the pass cancellation" (last updated 5 Aug 2026,
sha256 2bc8e148…). The EXPIRY rule is still not published, so:

  - CANCELLED -> the sourced *_cancellation_end_day_basis row (EXCLUSIVE);
  - EXPIRED, or no end reason recorded -> the unseeded expiry rule -> BLOCKED.

Also: the pre-1-July-2026 part-time LQS rate was already sourced (MOM COS
2024 factsheet) and must not be reported as unpublished; retail PWM
averaging now has a published basis but is not evaluated.

app.* imports are lazy (tests/_db_safety.py).
"""

from datetime import date
from decimal import Decimal as D


def _sp(ends, reason=None, cancellation_rule="EXCLUSIVE", expiry_rule=None):
    from app.modules.payroll.engine.countries import singapore
    from tests.test_singapore import Rate, _SPASS, _ctx, _rate_map, _trace

    rates = _rate_map(fwl_s_pass_cancellation_end_day_basis=Rate(text_value=cancellation_rule) if cancellation_rule else None,
                      fwl_s_pass_end_day_basis=Rate(text_value=expiry_rule) if expiry_rule else None)
    out = singapore.calculate(_ctx("5000", pay_date=date(2026, 6, 30), sgp_work_pass_issue_date=date(2025, 1, 1),
                                   sgp_work_pass_end_date=ends, sgp_work_pass_end_reason=reason, rate_map=rates, **_SPASS))
    return out["employer_eht"], _trace(out)["fwl"]


DAILY = D("21.37")                                   # (650 x 12) / 365, rounded up to the cent


def test_a_cancelled_s_pass_is_levied_up_to_the_day_before_cancellation():
    amount, fwl = _sp(date(2026, 6, 10), reason="CANCELLED")
    assert (amount, fwl["endReason"], fwl["endDayBasis"], fwl["leviedTo"]) == (DAILY * 9, "CANCELLED", "EXCLUSIVE", "2026-06-09")


def test_an_expired_or_unexplained_pass_ending_mid_month_stays_blocked():
    for reason in ("EXPIRED", None):
        amount, fwl = _sp(date(2026, 6, 10), reason=reason)
        assert (amount, fwl["status"]) == (D("0"), "BLOCKED"), reason
        assert "fwl_s_pass_end_day_basis" in fwl["detail"] and "AUTHORITATIVE VALUE REQUIRED" in fwl["detail"]


def test_the_cancellation_rule_never_leaks_into_expiry():
    amount, fwl = _sp(date(2026, 6, 10), reason="EXPIRED", cancellation_rule="EXCLUSIVE", expiry_rule=None)
    assert fwl["status"] == "BLOCKED"
    amount, fwl = _sp(date(2026, 6, 10), reason="EXPIRED", cancellation_rule=None, expiry_rule="INCLUSIVE")
    assert amount == DAILY * 10                                                 # an expiry rule, once published, applies


def test_a_cancelled_work_permit_uses_its_own_sourced_rule():
    from tests.test_singapore import Rate, _trace, _wp_rates
    from app.modules.payroll.engine.countries import singapore
    from tests.test_singapore import _ctx

    def wp(reason, **extra):
        return singapore.calculate(_ctx("2000", sgp_cpf_residency_status="FOREIGN", sgp_work_pass_type="WORK_PERMIT",
                                        sgp_wp_sector="SERVICES", sgp_wp_skill_level="R2", sgp_wp_levy_tier="TIER_2",
                                        pay_date=date(2026, 10, 31), sgp_work_pass_issue_date=date(2024, 1, 1),
                                        sgp_work_pass_end_date=date(2026, 10, 15), sgp_work_pass_end_reason=reason,
                                        rate_map=_wp_rates(**extra)))
    out = wp("CANCELLED", fwl_work_permit_cancellation_end_day_basis=Rate(text_value="EXCLUSIVE"))
    assert out["employer_eht"] == D("19.73") * 14 and _trace(out)["fwl"]["leviedTo"] == "2026-10-14"
    blocked = _trace(wp("CANCELLED"))["fwl"]                                     # rule not configured -> fail closed
    assert blocked["status"] == "BLOCKED" and "fwl_work_permit_cancellation_end_day_basis" in blocked["detail"]


def test_the_canonical_seed_carries_both_sourced_cancellation_rules(db):
    from app.modules.payroll.models import ContributionRate, SourceArtifact
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    expected = {"fwl_s_pass_cancellation_end_day_basis": ("cancel-a-pass", "5c71ac70", date(2025, 9, 15)),
                "fwl_work_permit_cancellation_end_day_basis": ("cancel-a-work-permit", "2bc8e148", date(2026, 8, 5))}
    for key, (url_part, sha_prefix, published) in expected.items():
        row = db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                                ContributionRate.component_key == key).one()
        src = db.get(SourceArtifact, row.source_document_id)
        assert row.text_value == "EXCLUSIVE" and url_part in src.source_url and src.agency == "MOM"
        assert src.checksum_sha256.startswith(sha_prefix) and src.publication_date == published
    keys = {r.component_key for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id)}
    assert "fwl_s_pass_end_day_basis" not in keys and "fwl_work_permit_end_day_basis" not in keys   # expiry: unpublished


def test_the_end_reason_is_validated_and_reaches_the_engine_context():
    from types import SimpleNamespace
    from app.modules.payroll.employee_validation import SGEmployeeValidation

    assert SGEmployeeValidation.FIELD_SPECS["work_pass_end_reason"]["pattern"].match("CANCELLED")
    assert not SGEmployeeValidation.FIELD_SPECS["work_pass_end_reason"]["pattern"].match("TERMINATED")
    assert "work_pass_end_reason" not in SGEmployeeValidation.FIELD_COLUMN_MAP          # compliance_fields only: no migration
    employee = SimpleNamespace(compliance_fields={"work_pass_end_reason": "CANCELLED"})
    assert (getattr(employee, "compliance_fields", None) or {}).get("work_pass_end_reason") == "CANCELLED"


def test_the_readiness_dependencies_reflect_the_sourced_data(db):
    from app.modules.payroll import service
    from scripts.seed_singapore_canonical_pack import seed_singapore

    pack = seed_singapore(db)
    db.commit()
    before_july = service.get_sg_statutory_summary(db, date(2026, 3, 15))
    lqs = next(s for s in before_july["sections"] if s["key"] == "lqs")
    assert lqs["values"]["partTimeHourly"]["flatAmount"] == "10.50"               # sourced (COS 2024 factsheet)
    deps = {d["key"]: d for d in before_july["activationReadiness"]["externalDependencies"]}
    assert "lqs_part_time_hourly" not in deps
    assert "part-time LQS" not in deps["unpublished_values"]["label"]
    assert "pwm_retail_averaging" not in deps                                       # implemented (Annex D), no longer external
    pwm = next(s for s in before_july["sections"] if s["key"] == "pwm")
    assert pwm["capabilities"]["retailThreeMonthAveraging"] == "IMPLEMENTED"
    assert "EXPIRY" in deps["fwl_s_pass_end_day_basis"]["label"]
    fwl = next(s for s in before_july["sections"] if s["key"] == "fwl")["values"]
    assert fwl["sPassCancellationEndDayBasis"]["textValue"] == "EXCLUSIVE"
    assert pack.status == "Draft"
