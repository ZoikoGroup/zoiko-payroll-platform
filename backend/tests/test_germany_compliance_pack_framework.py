"""
tests/test_germany_compliance_pack_framework.py
------------------------------------------------------------
Phase 8CH — Germany 2026 Compliance Framework Parity.

Proves the platform's existing, generic, versioned compliance-pack
framework (JurisdictionPack model + upsert_jurisdiction_pack/
set_jurisdiction_pack_status/set_jurisdiction_pack_approver/
assign_pack_to_organizations/get_organizations_eligible_for_pack/
list_tax_configuration_audit + engine/tax_resolver.py's
resolve_tax_configuration) — already used by USA/UK for their own
top-level tax packs — works correctly and without modification for a
top-level Germany "Compliance Pack" (tax-year governance record,
e.g. "DE-PAYROLL-CY2026-V1"), per this project's explicit "reuse the
existing framework rather than duplicate it" architecture rule.

This is a NEW, separate concept from the narrow RV/ALV/GKV canonical-rate
opt-in Phase 8BJ already wired and tested in
test_germany_contribution_rate_effective_dating.py — that file proves an
org can opt a JurisdictionPack's canonical ContributionRate rows into its
own payroll calculation. This file proves the PACK ITSELF (identity,
version history, lifecycle, maker-checker, effective-date resolution,
audit trail, org eligibility/assignment) behaves correctly for country
"DE" exactly as it already does for every other country — with ZERO
backend code changes required (confirmed: no country allowlist excludes
"DE" anywhere in this code path — see docs/GERMANY_2026_8CH_COMPLIANCE_
FRAMEWORK_COMPLETION_REPORT.md).

No production database is touched, no migration was created (none was
needed — the schema already supports this), and no Germany registry's
own effective-dating/PUBLISHED-gate/audit behavior (health funds,
ceilings, PV, minijob/midijob, church tax, PAP, overtime, ELStAM, ELSTER)
is modified or exercised here — those remain independently tested
elsewhere and are asserted UNCHANGED by the full regression run this
phase's report cites separately, not by this file.

Phase 8CI adds section 8 below: a DB-level uniqueness-constraint proof and
a round-trip of the exact real metadata values
scripts/seed_germany_compliance_pack_2026.py uses to create the actual,
governed DE-PAYROLL-CY2026-V1 pack in an isolated local database (see
docs/GERMANY_2026_8CI_COMPLIANCE_PACK_POPULATION_REPORT.md).
"""

from datetime import date

import pytest

from app.core.exceptions import BadRequestException
from app.modules.payroll import service
from app.modules.payroll.engine.tax_resolver import get_jurisdiction_onboarding_block_reason, resolve_tax_configuration
from app.modules.payroll.models import CompanyComplianceDetails, JurisdictionPack, TaxConfigurationAudit
from app.modules.payroll.schemas import JurisdictionPackUpsert


def _upsert(db, pack_id, version, status, effective_from, effective_to=None, tax_year=None, actor_id=101, **extra):
    return service.upsert_jurisdiction_pack(
        db, JurisdictionPackUpsert(
            packId=pack_id, jurisdictionCountry="DE", packType="tax", version=version,
            status=status, effectiveFrom=effective_from, effectiveTo=effective_to,
            taxYear=tax_year or version, currency="EUR", **extra,
        ), actor_id=actor_id,
    )


def _approve_and_activate(db, pack, checker_id=202):
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=checker_id)
    return service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=checker_id)


# ══════════════════════════════════════════════════════════════════════════
# 1. Creation — the pack's full field surface round-trips correctly.
# ══════════════════════════════════════════════════════════════════════════

def test_create_de_compliance_pack_draft_round_trips_all_fields(db):
    pack = _upsert(
        db, "DE-PAYROLL-CY2026-V1", "1.0", "Draft", date(2026, 1, 1), date(2026, 12, 31),
        tax_year="2026",
        regulatoryAuthority="Bundesministerium der Finanzen (BMF)",
        complianceCategory="Statutory Payroll Tax & Social Insurance",
        complianceOwner="NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION",
        engineeringOwner="NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION",
        nextReviewDate=date(2026, 10, 1),
        sourceReferences="NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION",
        changeSummary="Initial Germany 2026 compliance pack (Phase 8CH).",
    )
    assert pack.pack_id == "DE-PAYROLL-CY2026-V1"
    assert pack.jurisdiction_country == "DE"
    assert pack.pack_type == "tax"
    assert pack.status == "Draft"
    assert pack.currency == "EUR"
    assert pack.tax_year == "2026"
    assert pack.effective_from == date(2026, 1, 1)
    assert pack.effective_to == date(2026, 12, 31)
    assert pack.regulatory_authority == "Bundesministerium der Finanzen (BMF)"
    assert pack.next_review_date == date(2026, 10, 1)


# ══════════════════════════════════════════════════════════════════════════
# 2. Maker-checker lifecycle — same generic gate USA/UK rely on.
# ══════════════════════════════════════════════════════════════════════════

def test_self_approval_blocked_before_activation(db):
    pack = _upsert(db, "DE-PAYROLL-CY2026-MC1", "1.0", "Draft", date(2026, 1, 1), actor_id=101)
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=101)


def test_distinct_approver_then_activation_succeeds(db):
    pack = _upsert(db, "DE-PAYROLL-CY2026-MC2", "1.0", "Draft", date(2026, 1, 1), actor_id=101)
    service.set_jurisdiction_pack_approver(db, pack.id, actor_id=202)
    activated = service.set_jurisdiction_pack_status(db, pack.id, "Active", actor_id=202)
    assert activated.status == "Active"
    assert activated.approved_by_id == 202


def test_approver_auto_advances_draft_to_approved(db):
    pack = _upsert(db, "DE-PAYROLL-CY2026-MC3", "1.0", "Draft", date(2026, 1, 1), actor_id=101)
    approved = service.set_jurisdiction_pack_approver(db, pack.id, actor_id=202)
    assert approved.status == "Approved"


# ══════════════════════════════════════════════════════════════════════════
# 3. Version/year history — 2025 historical, 2026 active, 2027 draft, none
#    overwriting another (per phase brief section 8).
# ══════════════════════════════════════════════════════════════════════════

def test_historical_current_and_future_years_coexist_without_overwrite(db):
    pack_2025 = _upsert(db, "DE-PAYROLL-CY2025-V1", "1.0", "Draft", date(2025, 1, 1), date(2025, 12, 31), tax_year="2025")
    pack_2026 = _upsert(db, "DE-PAYROLL-CY2026-V1", "1.0", "Draft", date(2026, 1, 1), date(2026, 12, 31), tax_year="2026")
    pack_2027 = _upsert(db, "DE-PAYROLL-CY2027-V1", "1.0", "Draft", date(2027, 1, 1), None, tax_year="2027")

    _approve_and_activate(db, pack_2025)
    _approve_and_activate(db, pack_2026)
    # 2027 stays Draft — a future year must not be forced Active to exist.
    service.set_jurisdiction_pack_approver(db, pack_2027.id, actor_id=202)

    # Retiring the historical year is the documented lifecycle action for
    # "no longer current" — its row and data are still fully preserved,
    # never deleted or overwritten.
    service.set_jurisdiction_pack_status(db, pack_2025.id, "Deprecated", actor_id=202)

    all_de = db.query(JurisdictionPack).filter(JurisdictionPack.jurisdiction_country == "DE", JurisdictionPack.pack_type == "tax").all()
    by_pack_id = {p.pack_id: p for p in all_de}
    assert by_pack_id["DE-PAYROLL-CY2025-V1"].status == "Deprecated"
    assert by_pack_id["DE-PAYROLL-CY2025-V1"].tax_year == "2025"
    assert by_pack_id["DE-PAYROLL-CY2026-V1"].status == "Active"
    assert by_pack_id["DE-PAYROLL-CY2026-V1"].tax_year == "2026"
    assert by_pack_id["DE-PAYROLL-CY2027-V1"].status == "Approved"
    assert by_pack_id["DE-PAYROLL-CY2027-V1"].tax_year == "2027"


def test_new_version_of_same_pack_id_chains_previous_version(db):
    v1 = _upsert(db, "DE-PAYROLL-CY2026-CHAIN", "1.0", "Draft", date(2026, 1, 1), date(2026, 6, 30))
    _approve_and_activate(db, v1)
    v1_1 = _upsert(db, "DE-PAYROLL-CY2026-CHAIN", "1.1", "Draft", date(2026, 7, 1), None)
    assert v1_1.previous_version_id == v1.id

    versions = service.get_jurisdiction_pack_versions(db, "DE-PAYROLL-CY2026-CHAIN")
    assert {v.version for v in versions} == {"1.0", "1.1"}


# ══════════════════════════════════════════════════════════════════════════
# 4. Effective-date resolution — boundary correctness across year edges.
# ══════════════════════════════════════════════════════════════════════════

def test_effective_date_resolution_across_year_boundaries(db):
    pack_2025 = _approve_and_activate(db, _upsert(db, "DE-PAYROLL-CY2025-V1-EDR", "1.0", "Draft", date(2025, 1, 1), date(2025, 12, 31)))
    pack_2026 = _approve_and_activate(db, _upsert(db, "DE-PAYROLL-CY2026-V1-EDR", "1.0", "Draft", date(2026, 1, 1), date(2026, 12, 31)))
    # 2027 deliberately left Draft — proves a not-yet-activated future year
    # never leaks into resolution even once its effective_from has passed.
    _upsert(db, "DE-PAYROLL-CY2027-V1-EDR", "1.0", "Draft", date(2027, 1, 1), None)

    _, _, pack = resolve_tax_configuration(db, "DE", state=None, tax_regime=None, payroll_date=date(2025, 12, 31))
    assert pack.id == pack_2025.id

    _, _, pack = resolve_tax_configuration(db, "DE", state=None, tax_regime=None, payroll_date=date(2026, 1, 1))
    assert pack.id == pack_2026.id

    _, _, pack = resolve_tax_configuration(db, "DE", state=None, tax_regime=None, payroll_date=date(2026, 12, 31))
    assert pack.id == pack_2026.id

    # 2027-06-01: no Active pack covers this date (2026 pack's effective_to
    # is 2026-12-31; the 2027 pack is still Draft) — must fail open (None),
    # never silently reuse an expired or not-yet-approved pack.
    _, _, pack = resolve_tax_configuration(db, "DE", state=None, tax_regime=None, payroll_date=date(2027, 6, 1))
    assert pack is None


def test_overlapping_active_de_packs_rejected(db):
    _approve_and_activate(db, _upsert(db, "DE-PAYROLL-CY2026-OVERLAP-A", "1.0", "Draft", date(2026, 1, 1), None))
    overlapping = _upsert(db, "DE-PAYROLL-CY2026-OVERLAP-B", "1.0", "Draft", date(2026, 6, 1), None)
    service.set_jurisdiction_pack_approver(db, overlapping.id, actor_id=202)
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_status(db, overlapping.id, "Active", actor_id=202)


# ══════════════════════════════════════════════════════════════════════════
# 5. Audit trail — the same central TaxConfigurationAudit every other
#    country's pack lifecycle writes to.
# ══════════════════════════════════════════════════════════════════════════

def test_de_pack_lifecycle_writes_to_central_audit_trail(db):
    pack = _upsert(db, "DE-PAYROLL-CY2026-AUDIT", "1.0", "Draft", date(2026, 1, 1), actor_id=101)
    _approve_and_activate(db, pack, checker_id=202)

    entries = service.list_tax_configuration_audit(db, jurisdiction_pack_id=pack.id)
    assert entries, "expected at least one audit row for this DE pack's lifecycle"
    assert all(e.entity_type == "jurisdiction_pack" for e in entries)
    actions = {e.action for e in entries}
    assert "status_change" in actions

    # Same table every country's pack audit lands in — no Germany-specific
    # shadow audit table was created.
    assert db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.jurisdiction_pack_id == pack.id).count() == len(entries)


# ══════════════════════════════════════════════════════════════════════════
# 6. Organization eligibility/assignment — same generic mechanism.
# ══════════════════════════════════════════════════════════════════════════

def test_de_organization_eligibility_and_assignment(db, organization):
    db.add(CompanyComplianceDetails(organization_id=organization.id, jurisdiction_country="DE"))
    db.commit()

    pack = _approve_and_activate(db, _upsert(db, "DE-PAYROLL-CY2026-ORG", "1.0", "Draft", date(2026, 1, 1), None))

    eligible = service.get_organizations_eligible_for_pack(db, pack.id)
    assert any(o["id"] == organization.id for o in eligible)

    service.assign_pack_to_organizations(db, pack.id, [organization.id], actor_id=202)
    assigned = service.get_pack_applicable_organizations(db, pack.id)
    assert any(o["id"] == organization.id for o in assigned)

    details = db.query(CompanyComplianceDetails).filter(CompanyComplianceDetails.organization_id == organization.id).first()
    assert details.active_pack_id == pack.id


# ══════════════════════════════════════════════════════════════════════════
# 7. Non-regression — the pre-existing DE onboarding exemption (Phase 8BK)
#    must be unaffected by a DE JurisdictionPack now existing, Active or
#    not. Germany's own registry/PAP-driven calculator remains the
#    authority for whether Germany payroll itself works — this generic
#    pack is a governance/visibility record layered alongside it, not a
#    replacement gate.
# ══════════════════════════════════════════════════════════════════════════

def test_onboarding_gate_unaffected_by_de_pack_existing_or_active(db):
    assert get_jurisdiction_onboarding_block_reason(db, "DE") is None
    _approve_and_activate(db, _upsert(db, "DE-PAYROLL-CY2026-GATE", "1.0", "Draft", date(2026, 1, 1), None))
    assert get_jurisdiction_onboarding_block_reason(db, "DE") is None


# ══════════════════════════════════════════════════════════════════════════
# 8. Phase 8CI — uniqueness (DB-level, not just service-level convention)
#    and the real DE-PAYROLL-CY2026-V1 metadata this phase's governed seed
#    script (scripts/seed_germany_compliance_pack_2026.py) actually writes,
#    proven against the real service functions rather than merely reading
#    the seed script's own source.
# ══════════════════════════════════════════════════════════════════════════

def test_pack_id_version_uniqueness_enforced_at_db_level(db):
    """A raw duplicate (pack_id, version) INSERT — bypassing
    upsert_jurisdiction_pack's own (pack_id, version) lookup-before-create
    logic entirely — must still be rejected by the real database
    constraint (uq_jurisdiction_pack_id_version, models.py:2170), so
    uniqueness holds even against a hypothetical future write path that
    forgets to use the service layer."""
    from sqlalchemy.exc import IntegrityError

    _upsert(db, "DE-PAYROLL-CY2026-UNIQ", "1.0", "Draft", date(2026, 1, 1), None)
    dup = JurisdictionPack(
        pack_id="DE-PAYROLL-CY2026-UNIQ", version="1.0",
        jurisdiction_country="DE", pack_type="tax", status="Draft",
        effective_from=date(2026, 1, 1),
    )
    db.add(dup)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_real_de_2026_pack_metadata_matches_governed_seed_values(db):
    """Round-trips the EXACT metadata values
    scripts/seed_germany_compliance_pack_2026.py uses for the real,
    governed DE-PAYROLL-CY2026-V1 pack — a regression guard proving those
    real values (not test placeholders) are valid, persistable, and
    resolvable through the full Draft -> Approved -> Active lifecycle.
    Values are the ones the seed script's own docstring discloses as
    sourced, not invented: 'Bundesministerium der Finanzen (BMF) /
    ITZBund' is the same authority seed_germany_source_evidence.py already
    cites for the PAP Lohnsteuer2026 artifact; compliance/engineering
    owner and next review date are explicitly
    'NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION' rather than
    invented, per this phase's explicit instruction."""
    pack = _upsert(
        db, "DE-PAYROLL-CY2026-V1", "1.0", "Draft", date(2026, 1, 1), date(2026, 12, 31),
        tax_year="2026", actor_id=901,
        regulatoryAuthority="Bundesministerium der Finanzen (BMF) / ITZBund",
        complianceCategory="Statutory Payroll Tax & Social Insurance",
        complianceOwner="NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION",
        engineeringOwner="NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION",
        nextReviewDate=None,
        sourceReferences=(
            "Zoiko_Payroll_Germany_2026_Statutory_Configuration_Pack_v1.0.docx "
            "(supplied Germany statutory document); see payroll_source_artifacts "
            "for the per-registry SourceArtifact evidence chain."
        ),
        changeSummary="Initial Germany 2026 top-level compliance pack (Phase 8CI).",
    )
    activated = _approve_and_activate(db, pack, checker_id=902)

    assert activated.pack_id == "DE-PAYROLL-CY2026-V1"
    assert activated.jurisdiction_country == "DE"
    assert activated.jurisdiction_state is None
    assert activated.pack_type == "tax"
    assert activated.tax_year == "2026"
    assert activated.currency == "EUR"
    assert activated.effective_from == date(2026, 1, 1)
    assert activated.effective_to == date(2026, 12, 31)
    assert activated.status == "Active"
    assert activated.regulatory_authority == "Bundesministerium der Finanzen (BMF) / ITZBund"
    assert activated.compliance_owner == "NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION"
    assert activated.engineering_owner == "NOT SPECIFIED IN PROVIDED GERMANY DOCUMENTATION"
    assert activated.next_review_date is None

    _, _, resolved_pack = resolve_tax_configuration(db, "DE", state=None, tax_regime=None, payroll_date=date(2026, 6, 15))
    assert resolved_pack.id == activated.id
