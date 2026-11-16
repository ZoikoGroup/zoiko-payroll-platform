"""Malaysia Super Admin console (ZP-MY-ENG-001 Phase 8a; gate G1): in-app
Draft seeding, the console's read side (national + territorial parameters,
schedules, holidays, earning classes), signing status, bulk signing with a
reviewed source, the statutory workbook export / preview / apply round trip,
and the generic canonical-row editor refusing Malaysian rows."""
from types import SimpleNamespace

import pytest

from app.core.exceptions import BadRequestException


@pytest.fixture
def console(db):
    from app.modules.auth.models import User, UserRole
    from app.modules.payroll import my_super_admin as msa
    from app.modules.payroll.models import SourceArtifact

    users = []
    for i in range(3):
        u = User(email=f"sa{i}.my@example.com", hashed_password="x", role=UserRole.SUPER_ADMIN, first_name="S",
                 last_name=str(i), is_active=True, is_verified=True)
        db.add(u)
        users.append(u)
    db.flush()
    reviewed = SourceArtifact(agency="MOHR", title="Minimum Wages Order 2024", checksum_sha256="a" * 64,
                              file_path="sources/mwo-2024.pdf", created_by_id=users[1].id, reviewer_id=users[2].id)
    db.add(reviewed)
    db.flush()
    out = msa.seed_draft(db, {"reason": "start Malaysia G1"}, users[0].id)
    db.commit()
    return SimpleNamespace(db=db, msa=msa, editor=users[0].id, source=reviewed.id, pack=out["packs"][0]["id"])


def test_seed_draft_once_with_a_planned_registry_row(console):
    from app.modules.billing.models import JurisdictionServiceRegistry

    c = console
    assert c.db.query(JurisdictionServiceRegistry).filter_by(country="MY").one().availability == "PLANNED"
    assert [p["status"] for p in c.msa.list_packs(c.db)] == ["Draft"]
    with pytest.raises(BadRequestException, match="already seeded"):
        c.msa.seed_draft(c.db, {"reason": "again"}, c.editor)


def test_configuration_groups_every_row(console):
    from app.modules.payroll.engine.countries import malaysia_content as content

    c = console
    conf = c.msa.configuration(c.db, c.pack)
    keys = {r["componentKey"] for r in conf["rates"]}
    assert keys == set(content.ALL_PARAMETER_KINDS) and conf["territories"] == list(content.TERRITORIES)
    territorial = [r for r in conf["rates"] if r["componentKey"].endswith("__SBH")]
    assert territorial and all(r["territory"] == "SABAH" for r in territorial)
    assert set(conf["schedules"]) == set(content.SCHEDULE_RULES) and all(v == [] for v in conf["schedules"].values())
    assert conf["holidays"] == [] and len(conf["earningClasses"]) == len(content.MALAYSIA_EARNING_CLASSES)
    assert all(r["signed"] is False for r in conf["rates"])                      # every seeded row is extracted


def test_signing_status_lists_what_blocks_activation(console):
    c = console
    status = c.msa.signing_status(c.db, c.pack)
    assert set(status["emptyTables"]) >= {"MY_EPF_SCHEDULE", "MY_PUBLIC_HOLIDAY"}
    assert "my_min_wage_monthly" in status["pendingRates"] and status["activationRefusal"]
    assert "my_ot_rate_days_divisor__PEN" in status["emptyValues"]


def test_bulk_signing_needs_a_reviewed_source_and_records_the_editor(console):
    from app.modules.payroll.models import ContributionRate

    c = console
    row = c.db.query(ContributionRate).filter_by(jurisdiction_pack_id=c.pack, component_key="my_min_wage_monthly",
                                                 organization_id=None).one()
    out = c.msa.sign_rows(c.db, [{"kind": "rate", "id": row.id}], c.editor, "signed from the order",
                          source_document_id=c.source)
    assert out["signed"] == 1 and not row.label.endswith("[PENDING G1]")
    assert c.editor in c.msa.signing_status(c.db, c.pack)["editors"]
    with pytest.raises(BadRequestException):
        c.msa.sign_rows(c.db, [], c.editor, "nothing")


def test_workbook_round_trip_preview_and_apply(console):
    c = console
    data = c.msa.workbook_export(c.db, c.pack)
    assert data[:2] == b"PK"                                                     # an .xlsx
    preview = c.msa.workbook_import(c.db, c.pack, data, c.editor, apply=False)
    assert preview["fatal"] == [] and preview["applied"] is False and preview["summary"]["INVALID"] == 0
    with pytest.raises(BadRequestException, match="reason"):
        c.msa.workbook_import(c.db, c.pack, data, c.editor, apply=True)
    with pytest.raises(BadRequestException, match="Upload"):
        c.msa.workbook_import(c.db, c.pack, b"", c.editor, apply=False)


def test_the_generic_row_editor_refuses_malaysian_rows():
    from app.modules.payroll import service

    with pytest.raises(BadRequestException, match="Compliance → Malaysia"):
        service._refuse_nz_generic_statutory_edit(SimpleNamespace(jurisdiction_country="MY"))
    service._refuse_nz_generic_statutory_edit(SimpleNamespace(jurisdiction_country="IN"))


def test_super_admin_routes_are_declared():
    from app.modules.super_admin.router import router

    paths = {(sorted(r.methods)[0], r.path) for r in router.routes if "/malaysia" in r.path}
    for method, path in (("GET", "/compliance/malaysia/packs"),
                         ("GET", "/compliance/malaysia/packs/{pack_row_id}/configuration"),
                         ("GET", "/compliance/malaysia/packs/{pack_row_id}/signing-status"),
                         ("PUT", "/compliance/malaysia/configuration/rows/{kind}/{row_id}"),
                         ("POST", "/compliance/malaysia/configuration/sign"),
                         ("POST", "/compliance/malaysia/packs/{pack_row_id}/tables/{rule_type}"),
                         ("POST", "/compliance/malaysia/seed-draft"),
                         ("GET", "/compliance/malaysia/decisions"),
                         ("GET", "/compliance/malaysia/packs/{pack_row_id}/workbook/export"),
                         ("POST", "/compliance/malaysia/packs/{pack_row_id}/workbook/preview"),
                         ("POST", "/compliance/malaysia/packs/{pack_row_id}/workbook/apply")):
        assert any(p.endswith(path) and m == method for m, p in paths), (method, path)
