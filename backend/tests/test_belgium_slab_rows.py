"""Belgium (ZP-BE-ENG-001) Phase 3B: governed slab rows of band / formula /
table keys — create, sign, retire (Draft only, before-image audited), four-eyes,
composite band dimensions, public holidays, BePack lookups, and the guards
(no eval/exec; non-BE slab behaviour unchanged).

SYNTHETIC data, in-memory SQLite. Every number written here is synthetic,
never Belgian statutory content."""
import ast
from datetime import date
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest

EDITOR, SIGNER, APPROVER = 601, 602, 603
PAYROLL = Path(__file__).resolve().parents[1] / "app" / "modules" / "payroll"


def _c():
    from app.modules.payroll.engine.countries import belgium_content

    return belgium_content


@pytest.fixture
def seeded(db):
    from scripts.seed_belgium_canonical_packs import seed_belgium

    pack = seed_belgium(db)["pack"]
    db.commit()
    return pack


@pytest.fixture
def source(db):
    from app.modules.payroll.models import SourceArtifact

    src = SourceArtifact(agency="Synthetic authority", title="Synthetic archived source", form_number="SYN-3B",
                         checksum_sha256="b" * 64, file_path="synthetic/3b.pdf", created_by_id=900, reviewer_id=901)
    db.add(src)
    db.commit()
    return src


def _rate(db, pack, key):
    from app.modules.payroll.models import ContributionRate

    return (db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id,
                                              ContributionRate.component_key == key).one())


def _add(db, pack, key, actor=EDITOR, **data):
    from app.modules.payroll import be_super_admin

    out = be_super_admin.add_slab_row(db, pack.id, key, data, actor)
    db.commit()
    return out


def _sign_codes(db, pack, src, ec="EC1,EC2", wc="WC1"):
    from app.modules.payroll import be_super_admin

    for key, value in (("be_onss_supported_employer_categories", ec), ("be_onss_supported_worker_codes", wc)):
        row_id = _rate(db, pack, key).id
        be_super_admin.update_row(db, "rate", row_id, {"textValue": value, "reason": "r",
                                                       "sourceDocumentId": src.id}, EDITOR)      # edit
        be_super_admin.update_row(db, "rate", row_id, {"reason": "r", "sourceDocumentId": src.id,
                                                       "specialistVerified": True}, SIGNER)      # sign (F1)
    db.commit()


def _sign_slab(db, row_id, src_id, actor=None):
    """F1: rows are added PENDING; another Super Admin signs them."""
    from app.modules.payroll import be_super_admin

    out = be_super_admin.update_row(db, "slab", row_id, {"reason": "r", "sourceDocumentId": src_id,
                                                         "specialistVerified": True}, actor or SIGNER)
    db.commit()
    return out


# ── composite dimension ────────────────────────────────────────────────────
@pytest.mark.parametrize("text, parsed", [("EC=1a;WC=495", {"EC": "1A", "WC": "495"}),
                                          ("WC=7 ; EC=B", {"EC": "B", "WC": "7"}), ("CHILDREN=2", {"CHILDREN": "2"}),
                                          ("", {}), (None, {})])
def test_dimension_parse(text, parsed):
    assert _c().parse_dimension(text) == parsed


@pytest.mark.parametrize("text", ["EC", "EC=", "=1", "XX=1", "EC=1;EC=2", "CHILDREN=two", "EC=TOO-LONG-CODE",
                                  "EC=1;;WC=2"])
def test_dimension_parse_rejects_malformed(text):
    with pytest.raises(ValueError):
        _c().parse_dimension(text)


def test_dimension_format_is_canonical_and_round_trips():
    c = _c()
    assert c.format_dimension(WC="495", EC="1a") == "EC=1A;WC=495"
    assert c.parse_dimension(c.format_dimension(CHILDREN=3)) == {"CHILDREN": "3"}
    assert c.SLAB_SPECS["be_onss_employer_base_rate"]["dimensions"] == ("EC", "WC")
    assert c.SLAB_SPECS["be_abs_maternity_multiple_weeks"]["dimensions"] == ("CHILDREN",)


# ── create / sign / validation ─────────────────────────────────────────────
def test_add_band_row_needs_source_reason_and_fields(db, seeded, source):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="source document"):
        _add(db, seeded, "be_red_social_work_bonus", reason="r", minAmount="0", ratePct="1")
    with pytest.raises(BadRequestException, match="reason"):
        _add(db, seeded, "be_red_social_work_bonus", sourceDocumentId=source.id, minAmount="0", ratePct="1")
    with pytest.raises(BadRequestException, match="needs: ratePct or flatAmount"):
        _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=source.id, minAmount="0")
    with pytest.raises(BadRequestException, match="only to Belgian band"):
        _add(db, seeded, "be_wage_rmmmg", reason="r", sourceDocumentId=source.id, minAmount="0", ratePct="1")
    with pytest.raises(BadRequestException, match="negative"):
        _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=source.id, minAmount="-1",
             ratePct="1")
    view = _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=source.id, minAmount="0",
                maxAmount="100", ratePct="1")
    assert view["ruleType"] == "BE_RED_SOCIAL_WORK_BONUS" and view["signed"] is False


def test_signing_needs_a_reviewed_source(db, seeded, source):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll.models import SourceArtifact

    unarchived = db.query(SourceArtifact).filter(SourceArtifact.form_number == "ZP-BE-ENG-001 S24").one()
    pending = _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=unarchived.id,
                   minAmount="0", ratePct="1")
    with pytest.raises(BadRequestException, match="reviewed by a Super Admin"):
        _sign_slab(db, pending["id"], unarchived.id)
    db.rollback()
    view = _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=source.id, minAmount="1",
                ratePct="1")
    assert view["signed"] is False
    assert _sign_slab(db, view["id"], source.id)["signed"] is True


def test_onss_employer_dimensions_need_the_signed_code_lists(db, seeded, source):
    from app.core.exceptions import BadRequestException

    row = dict(reason="r", sourceDocumentId=source.id, minAmount="0", ratePct="1")
    with pytest.raises(BadRequestException, match="exactly the dimensions EC, WC"):
        _add(db, seeded, "be_onss_employer_base_rate", **row)
    with pytest.raises(BadRequestException, match="not signed yet"):
        _add(db, seeded, "be_onss_employer_base_rate", dimension="EC=EC1;WC=WC1", **row)
    _sign_codes(db, seeded, source)
    with pytest.raises(BadRequestException, match="EC=EC9 is not in the signed"):
        _add(db, seeded, "be_onss_employer_base_rate", dimension="EC=EC9;WC=WC1", **row)
    with pytest.raises(BadRequestException, match="WC=WC9 is not in the signed"):
        _add(db, seeded, "be_onss_employer_base_rate", dimension="EC=EC1;WC=WC9", **row)
    with pytest.raises(BadRequestException, match="dimension"):
        _add(db, seeded, "be_onss_employer_base_rate", dimension="EC=EC1", **row)
    view = _add(db, seeded, "be_onss_employer_base_rate", dimension="wc=wc1;ec=ec1", **row)
    assert view["component"] == "EC=EC1;WC=WC1"


def test_code_list_keys_validate_their_format(db, seeded, source):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import be_super_admin

    row = _rate(db, seeded, "be_onss_supported_worker_codes")
    for bad in ("WC 1", "A,A", ","):
        with pytest.raises(BadRequestException, match="comma-separated list of codes"):
            be_super_admin.update_row(db, "rate", row.id, {"textValue": bad, "reason": "r",
                                                           "sourceDocumentId": source.id}, EDITOR)


def test_maternity_band_dimension(db, seeded, source):
    from app.core.exceptions import BadRequestException

    row = dict(reason="r", sourceDocumentId=source.id, minAmount="0", flatAmount="1")
    with pytest.raises(BadRequestException):
        _add(db, seeded, "be_abs_maternity_multiple_weeks", dimension="EC=1", **row)
    assert _add(db, seeded, "be_abs_maternity_multiple_weeks", dimension="CHILDREN=2", **row)["component"] == "CHILDREN=2"


def test_formula_rows_store_text_only(db, seeded, source):
    from app.modules.payroll.models import TaxSlab

    view = _add(db, seeded, "be_red_structural", reason="r", sourceDocumentId=source.id,
                formulaText="synthetic   formula text", name="Synthetic formula")
    row = db.get(TaxSlab, view["id"])
    assert row.formula_expression == "synthetic formula text" and row.rule_type == "BE_RED_STRUCTURAL"


def test_public_holiday_rows_stay_inside_the_pack_window(db, seeded, source):
    from app.core.exceptions import BadRequestException

    with pytest.raises(BadRequestException, match="outside the pack window"):
        _add(db, seeded, "be_public_holidays", reason="r", sourceDocumentId=source.id, date="2027-01-01",
             name="Synthetic day")
    view = _add(db, seeded, "be_public_holidays", reason="r", sourceDocumentId=source.id, date="2026-03-03",
                name="Synthetic day")
    assert view["effectiveFrom"] == view["effectiveTo"] == "2026-03-03"


# ── four-eyes, approval invalidation, retire ──────────────────────────────
def test_slab_editors_cannot_approve_and_edits_invalidate_approval(db, seeded, source):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import jurisdiction_hooks, service

    seeded.approved_by_id = APPROVER
    db.commit()
    _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=source.id, minAmount="0", ratePct="1")
    db.refresh(seeded)
    assert seeded.approved_by_id is None                          # shared _invalidate_pack_approval_on_edit
    assert EDITOR in jurisdiction_hooks.call("BE", "statutory_editors", db, seeded)
    with pytest.raises(BadRequestException):
        service.set_jurisdiction_pack_approver(db, seeded.id, actor_id=EDITOR)


def test_retire_is_draft_only_with_a_full_before_image(db, seeded, source):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import be_super_admin
    from app.modules.payroll.models import TaxConfigurationAudit, TaxSlab

    view = _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=source.id,
                minAmount="0", maxAmount="100", ratePct="1")
    view = _sign_slab(db, view["id"], source.id)
    with pytest.raises(BadRequestException, match="reason"):
        be_super_admin.retire_slab_row(db, view["id"], {}, EDITOR)
    out = be_super_admin.retire_slab_row(db, view["id"], {"reason": "duplicate"}, EDITOR)
    db.commit()
    assert out == {"id": view["id"], "retired": True} and db.get(TaxSlab, view["id"]) is None
    audit = (db.query(TaxConfigurationAudit).filter(TaxConfigurationAudit.entity_type == "be_statutory_slab",
                                                     TaxConfigurationAudit.entity_id == view["id"])
             .order_by(TaxConfigurationAudit.id.desc()).first())
    before = audit.old_value
    assert audit.new_value == {"action": "retired"} and audit.reason == "duplicate"
    for name in ("minAmount", "maxAmount", "ratePct", "flatAmount", "formulaExpression", "effectiveFrom",
                 "effectiveTo", "sourceDocumentId", "signed", "signedBy", "ruleType", "component"):
        assert name in before, name
    assert before["signed"] is True and before["signedBy"] == SIGNER and before["sourceDocumentId"] == source.id
    assert Decimal(before["ratePct"]) == Decimal("1") and Decimal(before["maxAmount"]) == Decimal("100")


def test_retire_is_refused_on_any_non_draft_pack(db, seeded, source):
    from app.core.exceptions import BadRequestException
    from app.modules.payroll import be_super_admin

    view = _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=source.id, minAmount="0",
                ratePct="1")
    for status in ("In Review", "Approved", "Active"):
        seeded.status = status
        db.commit()
        with pytest.raises(BadRequestException, match="only from a Draft"):
            be_super_admin.retire_slab_row(db, view["id"], {"reason": "x"}, EDITOR)


# ── activation ─────────────────────────────────────────────────────────────
def _sign_everything(db, pack, source_id):
    from app.modules.payroll.models import ContributionRate, TaxSlab

    c = _c()
    for r in db.query(ContributionRate).filter(ContributionRate.jurisdiction_pack_id == pack.id):
        r.text_value, r.source_document_id = "NOT_SUPPORTED", source_id
        r.label = r.label.replace(c.PENDING_MARK, "").strip()
    for s in db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == pack.id):
        s.rate_label = s.rate_label.replace(c.PENDING_MARK, "").strip()
        s.assessment_basis = "EXCLUDED"
    db.commit()


def test_activation_refused_while_a_band_key_has_no_signed_rows(db, seeded, source):
    from app.modules.payroll import belgium_service

    _sign_everything(db, seeded, source.id)
    marker = _rate(db, seeded, "be_red_social_work_bonus")
    marker.text_value = "SLAB_ROWS"
    db.commit()
    assert "be_red_social_work_bonus (slab rows missing or unsigned)" in \
        belgium_service.be_pack_activation_refusal(db, seeded, actor_id=APPROVER)
    _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=source.id, minAmount="0", ratePct="1")
    assert "be_red_social_work_bonus (slab rows missing or unsigned)" in \
        belgium_service.be_pack_activation_refusal(db, seeded, actor_id=APPROVER)   # added but unsigned
    added = _add(db, seeded, "be_red_social_work_bonus", reason="r", sourceDocumentId=source.id, minAmount="10",
                 ratePct="1")
    _sign_slab(db, added["id"], source.id)
    from app.modules.payroll.models import TaxSlab

    for s in db.query(TaxSlab).filter(TaxSlab.rule_type == "BE_RED_SOCIAL_WORK_BONUS"):
        s.rate_label = s.rate_label.replace(_c().PENDING_MARK, "").strip()
    db.commit()
    # content complete: what remains is the Block C2 golden gate (no authority example yet)
    assert "the authority examples do not replay exactly" in belgium_service.be_pack_activation_refusal(db, seeded, actor_id=APPROVER)


# ── BePack over slab rows ──────────────────────────────────────────────────
def _pack(rate_map, slabs, as_of=date(2026, 7, 1)):
    from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack

    return BePack(rate_map, slabs, 1, as_of)


def _blocked(code):
    from app.modules.payroll.engine.jurisdictions.belgium.errors import BECalculationBlockedError

    return pytest.raises(BECalculationBlockedError, match=code)


def _band_row(dim, rate, label="signed", start=None, end=None):
    return {"rule_type": "BE_ONSS_EMPLOYER_BASE_RATE", "filing_status": dim, "min_amount": "0", "rate_pct": rate,
            "rate_label": label, "effective_from": start, "effective_to": end}


_MARKER = {"be_onss_employer_base_rate": {"component_key": "be_onss_employer_base_rate", "label": "x",
                                          "text_value": "SLAB_ROWS"}}


def test_band_lookup_by_dimension_never_falls_back(db):
    rows = [_band_row("EC=EC1;WC=WC1", "10"), _band_row(None, "99")]
    pack = _pack(_MARKER, rows)
    assert [r["rate_pct"] for r in pack.band("be_onss_employer_base_rate", EC="ec1", WC="wc1")] == ["10"]
    with _blocked("BE_ROW_MISSING:be_onss_employer_base_rate"):
        pack.band("be_onss_employer_base_rate", EC="EC2", WC="WC1")       # no match: no dimensionless fallback
    with _blocked("BE_ROW_MISSING:be_onss_employer_base_rate"):
        pack.band("be_onss_employer_base_rate", EC="EC1")                # incomplete dimension
    with _blocked("BE_ROW_MISSING"):
        pack.band("be_wage_rmmmg")                                         # not a band key


def test_unsigned_slab_rows_block(db):
    with _blocked("BE_CONTENT_PENDING"):
        _pack(_MARKER, [_band_row("EC=EC1;WC=WC1", "10", label="x [PENDING G1]")]).band(
            "be_onss_employer_base_rate", EC="EC1", WC="WC1")


def test_band_row_dates_select_by_pay_date():
    rows = [_band_row("EC=EC1;WC=WC1", "10", end=date(2026, 6, 30)),
            _band_row("EC=EC1;WC=WC1", "11", start=date(2026, 7, 1))]
    assert _pack(_MARKER, rows, date(2026, 6, 30)).band("be_onss_employer_base_rate", EC="EC1", WC="WC1")[0][
        "rate_pct"] == "10"
    assert _pack(_MARKER, rows, date(2026, 7, 1)).band("be_onss_employer_base_rate", EC="EC1", WC="WC1")[0][
        "rate_pct"] == "11"


def _holiday(day, label="Synthetic day"):
    return {"rule_type": "BE_PUBLIC_HOLIDAY", "effective_from": day, "effective_to": day, "rate_label": label,
            "tax_formula": label}


def test_public_holidays_are_signed_only_and_block_when_pending_or_not_supported():
    marker = {"be_public_holidays": {"component_key": "be_public_holidays", "label": "x", "text_value": "SLAB_ROWS"}}
    days = [_holiday(date(2026, 3, 3)), _holiday(date(2026, 1, 2)), _holiday(date(2025, 12, 31))]
    assert _pack(marker, days).public_holidays(2026) == [(date(2026, 1, 2), "Synthetic day"),
                                                         (date(2026, 3, 3), "Synthetic day")]
    with _blocked("BE_CONTENT_PENDING"):
        _pack(marker, days + [_holiday(date(2026, 5, 5), "x [PENDING G1]")]).public_holidays(2026)
    with _blocked("BE_TABLE_EMPTY"):
        _pack(marker, days).public_holidays(2030)
    with _blocked("BE_FEATURE_BLOCKED"):
        _pack({"be_public_holidays": dict(marker["be_public_holidays"], text_value="NOT_SUPPORTED")},
              days).public_holidays(2026)
    with _blocked("BE_CONTENT_PENDING"):
        _pack({"be_public_holidays": dict(marker["be_public_holidays"], label="x [PENDING G1]")},
              days).public_holidays(2026)


# ── API surface ────────────────────────────────────────────────────────────
def test_configuration_carries_vocabularies_and_slab_specs(db, seeded):
    from app.modules.payroll import be_super_admin

    c = _c()
    config = be_super_admin.configuration(db, seeded.id)
    assert config["groupOrder"] == list(c.GROUPS)
    assert config["vocabulary"]["be_rounding_onss"] == {"mode": "choice", "choices": list(c.ROUNDING_RULES),
                                                       "notSupported": "NOT_SUPPORTED"}
    assert config["vocabulary"]["be_onss_supported_worker_codes"]["mode"] == "codes"
    assert config["slabSpecs"]["be_onss_employer_base_rate"]["dimensions"] == ["EC", "WC"]
    assert config["slabSpecs"]["be_public_holidays"]["ruleType"] == "BE_PUBLIC_HOLIDAY"


def test_joint_committees_are_parsed_by_the_backend(db):
    from app.modules.payroll import be_super_admin, service
    from app.modules.payroll.schemas import CollectiveAgreementUpsert

    service.upsert_collective_agreement(db, CollectiveAgreementUpsert(
        jurisdictionCountry="BE", agreementCode="BE-PC-124-A-1.0", name="Synthetic JC", agreementType="SECTOR",
        version="1.0"), actor_id=EDITOR)
    rows = be_super_admin.joint_committees(db)
    assert len(rows) == 1 and (rows[0]["jointCommittee"], rows[0]["subCommittee"], rows[0]["codeVersion"]) == \
        ("124", "A", "1.0") and rows[0]["codeValid"] is True


def test_new_routes_are_super_admin_only(db, seeded, source):
    from tests._mx_employer_helpers import SUPER_ADMIN, http, principal

    base = "/api/super-admin/compliance/belgium"
    with http(db, SUPER_ADMIN) as c:
        r = c.post(f"{base}/packs/{seeded.id}/slab-rows/be_red_structural",
                   json={"reason": "r", "sourceDocumentId": source.id, "formulaText": "x", "name": "Synthetic"})
        assert r.status_code == 200, r.text
        assert c.request("DELETE", f"{base}/configuration/slab-rows/{r.json()['id']}",
                         params={"reason": "dup"}).json()["retired"] is True
        assert c.get(f"{base}/joint-committees").status_code == 200
    with http(db, principal(1)) as c:
        assert c.get(f"{base}/joint-committees").status_code == 403


# ── guards ─────────────────────────────────────────────────────────────────
def test_no_belgian_file_calls_eval_or_exec():
    files = sorted(set(PAYROLL.glob("**/belgium*.py")) | set(PAYROLL.glob("be_*.py"))
                   | set((PAYROLL / "engine" / "jurisdictions" / "belgium").glob("*.py")))
    calls = []
    for path in files:
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in ("eval", "exec"):
                calls.append(f"{path.name}:{node.lineno} {node.func.id}")
    assert files and calls == []


def test_non_belgian_slab_selection_by_filing_status_is_unchanged():
    """An existing country's filing-status-tagged brackets still select by
    filing_status (US-style rows through the shared matcher)."""
    from app.modules.payroll.engine.countries.shared import _calculate_annual_tax

    def slab(status, rate):
        return SimpleNamespace(rule_type="MARGINAL_RATE", filing_status=status, min_amount=Decimal("0"),
                               max_amount=None, rate_pct=Decimal(rate), flat_amount=None, formula_expression=None,
                               adjustment_amount=None, sort_order=0, assessment_basis=None)

    slabs = [slab("SINGLE", "10"), slab("MFJ", "20")]
    assert _calculate_annual_tax(Decimal("1000"), slabs, "SINGLE") == Decimal("100")
    assert _calculate_annual_tax(Decimal("1000"), slabs, "MFJ") == Decimal("200")
