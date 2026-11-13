"""Belgium (ZP-BE-ENG-001) Block F1: F-G12-1 fixed — per-row four-eyes on content.

A Belgian content row (scalar or slab) is never edited and signed in one action
and never signed by a user who edited it in the current pack version; a re-edit
un-signs the row and its editor cannot re-sign. Bulk sign and activation keep
their rules; other countries' consoles are unchanged. SYNTHETIC values only."""
import pytest

from app.core.exceptions import BadRequestException
from tests.test_belgium_super_admin import (ACTIVATOR, EDITOR, SIGNER, _c, _rate, _update, _verified_source,
                                            seeded)  # noqa: F401  (pytest fixture)

OTHER = 777


def test_the_same_user_cannot_edit_and_sign_in_one_action(db, seeded):
    src = _verified_source(db)
    row = _rate(db, seeded, "be_wage_rmmmg")
    with pytest.raises(BadRequestException, match="never edited and signed in one action"):
        _update(db, "rate", row.id, EDITOR, flatAmount="10", reason="r", sourceDocumentId=src.id,
                specialistVerified=True)
    db.rollback()
    assert _rate(db, seeded, "be_wage_rmmmg").flat_amount is None                   # nothing applied


def test_the_editor_cannot_sign_but_a_different_user_can(db, seeded):
    c = _c()
    src = _verified_source(db)
    row = _rate(db, seeded, "be_wage_rmmmg")
    _update(db, "rate", row.id, EDITOR, flatAmount="10", reason="edit", sourceDocumentId=src.id)
    with pytest.raises(BadRequestException, match="you edited this row"):
        _update(db, "rate", row.id, EDITOR, reason="sign", sourceDocumentId=src.id, specialistVerified=True)
    db.rollback()
    view = _update(db, "rate", row.id, SIGNER, reason="sign", sourceDocumentId=src.id, specialistVerified=True)
    assert view["signed"] and c.PENDING_MARK not in _rate(db, seeded, "be_wage_rmmmg").label


def test_a_re_edit_unsigns_and_its_editor_cannot_re_sign(db, seeded):
    c = _c()
    src = _verified_source(db)
    row = _rate(db, seeded, "be_wage_rmmmg")
    _update(db, "rate", row.id, EDITOR, flatAmount="10", reason="edit", sourceDocumentId=src.id)
    _update(db, "rate", row.id, SIGNER, reason="sign", sourceDocumentId=src.id, specialistVerified=True)
    _update(db, "rate", row.id, OTHER, flatAmount="11", reason="re-edit", sourceDocumentId=src.id)
    assert c.PENDING_MARK in _rate(db, seeded, "be_wage_rmmmg").label                # un-signed
    with pytest.raises(BadRequestException, match="you edited this row"):
        _update(db, "rate", row.id, OTHER, reason="sign", sourceDocumentId=src.id, specialistVerified=True)
    db.rollback()
    view = _update(db, "rate", row.id, ACTIVATOR, reason="sign", sourceDocumentId=src.id, specialistVerified=True)
    assert view["signed"]


def test_slab_rows_are_added_pending_and_signed_by_someone_else(db, seeded):
    from app.modules.payroll import be_super_admin

    src = _verified_source(db)
    with pytest.raises(BadRequestException, match="always added PENDING"):
        be_super_admin.add_slab_row(db, seeded.id, "be_red_social_work_bonus",
                                    {"minAmount": "0", "ratePct": "1", "reason": "r", "sourceDocumentId": src.id,
                                     "specialistVerified": True}, EDITOR)
    view = be_super_admin.add_slab_row(db, seeded.id, "be_red_social_work_bonus",
                                       {"minAmount": "0", "ratePct": "1", "reason": "r", "sourceDocumentId": src.id},
                                       EDITOR)
    db.commit()
    assert view["signed"] is False
    with pytest.raises(BadRequestException, match="you edited this row"):
        _update(db, "slab", view["id"], EDITOR, reason="sign", sourceDocumentId=src.id, specialistVerified=True)
    db.rollback()
    assert _update(db, "slab", view["id"], SIGNER, reason="sign", sourceDocumentId=src.id,
                   specialistVerified=True)["signed"] is True


def test_earning_class_rows_follow_the_same_rule(db, seeded):
    from app.modules.payroll.models import TaxSlab

    src = _verified_source(db)
    cls = db.query(TaxSlab).filter(TaxSlab.jurisdiction_pack_id == seeded.id,
                                   TaxSlab.rule_type == "BE_EARNING_CLASS").first()
    with pytest.raises(BadRequestException, match="never edited and signed"):
        _update(db, "slab", cls.id, EDITOR, treatment="INCLUDED", reason="r", sourceDocumentId=src.id,
                specialistVerified=True)
    db.rollback()
    _update(db, "slab", cls.id, EDITOR, treatment="INCLUDED", reason="r", sourceDocumentId=src.id)
    assert _update(db, "slab", cls.id, SIGNER, reason="r", sourceDocumentId=src.id,
                   specialistVerified=True)["signed"] is True


def test_signing_alone_does_not_make_the_signer_an_editor(db, seeded):
    from app.modules.payroll import be_super_admin

    src = _verified_source(db)
    row = _rate(db, seeded, "be_wage_rmmmg")
    _update(db, "rate", row.id, EDITOR, flatAmount="10", reason="edit", sourceDocumentId=src.id)
    _update(db, "rate", row.id, SIGNER, reason="sign", sourceDocumentId=src.id, specialistVerified=True)
    assert be_super_admin.be_row_editors(db, "rate", row.id) == {EDITOR}


def test_activation_still_refuses_every_editor_and_signer(db, seeded):
    from app.modules.payroll import belgium_service

    src = _verified_source(db)
    row = _rate(db, seeded, "be_wage_rmmmg")
    _update(db, "rate", row.id, EDITOR, flatAmount="10", reason="edit", sourceDocumentId=src.id)
    _update(db, "rate", row.id, SIGNER, reason="sign", sourceDocumentId=src.id, specialistVerified=True)
    for actor in (EDITOR, SIGNER):
        assert "cannot also activate" in belgium_service.be_pack_activation_refusal(db, seeded, actor_id=actor)


def test_other_countries_consoles_are_unchanged():
    import inspect

    from app.modules.payroll import nz_super_admin, pl_super_admin

    for module in (pl_super_admin, nz_super_admin):
        source = inspect.getsource(module)
        assert "be_row_editors" not in source and "never edited and signed in one action" not in source
