"""Builders for the Mexico Phase 7 CFDI tests. Everything is SYNTHETIC:
the builder and signer produce labelled non-SAT bytes, the PAC is the
test-only mock, the schema release / catalog rows are synthetic."""

import hashlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.modules.payroll.mexico_cfdi_builder import CfdiPayloadBuilder, CfdiSigner
from tests import _mx_run_helpers as rh
from tests._mx_mock_pac import MockPac, install


class SyntheticBuilder(CfdiPayloadBuilder):
    def build(self, document_input):
        return (f"<SYNTHETIC-NOT-A-CFDI payslip='{document_input['payslipItemId']}' "
                f"pay='{document_input['payDate']}' replaces='{document_input.get('replacesUuid')}'/>").encode()


class SyntheticSigner(CfdiSigner):
    def sign(self, payload, credential):
        return payload + b"<!--SYNTHETIC-SELLO " + hashlib.sha256(payload).hexdigest()[:16].encode() + b"-->", "SYN-CSD"


def patch_seams(monkeypatch, tmp_path):
    from app.modules.payroll import mexico_cfdi_builder as B

    monkeypatch.setattr(B, "_BUILDER", SyntheticBuilder())
    monkeypatch.setattr(B, "_SIGNER", SyntheticSigner())
    monkeypatch.setenv("UPLOAD_BASE_DIR", str(tmp_path / "uploads"))
    monkeypatch.setenv("PAYROLL_STORAGE_BACKEND", "local")


def schema_release(db, status="Active"):
    from app.modules.payroll.models import PayrollMxCfdiCatalogEntry, PayrollMxCfdiSchemaRelease

    rel = PayrollMxCfdiSchemaRelease(cfdi_version="4.0", complement_version="1.2", revision="SYNTHETIC", status=status)
    db.add(rel)
    db.flush()
    db.add(PayrollMxCfdiCatalogEntry(schema_release_id=rel.id, catalog_name="c_MotivoCancelacion", code="SYN1",
                                     description="SYNTHETIC — with related UUID", attributes={"requiresRelatedUuid": True}))
    db.add(PayrollMxCfdiCatalogEntry(schema_release_id=rel.id, catalog_name="c_MotivoCancelacion", code="SYN2",
                                     description="SYNTHETIC — no related UUID", attributes={"requiresRelatedUuid": False}))
    db.commit()
    return rel


def employer_ready(db, w, *, environment="SANDBOX", stamp_test="NOT_TESTED", csd=True):
    from app.modules.payroll.models import PayrollMxCredentialRef, PayrollMxEmployerProfile

    root = w.registration.employer_profile_id
    for p in db.query(PayrollMxEmployerProfile).filter(
            (PayrollMxEmployerProfile.id == root) | (PayrollMxEmployerProfile.previous_version_id == root)):
        p.pac_provider, p.pac_environment, p.stamp_test_status = "MOCK", environment, stamp_test
    if csd:
        db.add(PayrollMxCredentialRef(organization_id=w.org.id, employer_profile_id=root, kind="CSD",
                                      secret_ref="gcp-sm://projects/zoiko-test-project/secrets/mx-csd/versions/1",
                                      fingerprint_sha256="0" * 64, status="ACTIVE",
                                      valid_to=datetime.now(timezone.utc) + timedelta(days=300)))
    db.commit()


def committed_world(db, monkeypatch, tmp_path, *, release=True, code="MXCFDI", **employer):
    w = rh.world(db, monkeypatch, code=code)
    rh.generate(db, w)
    rh.advance(db, w)
    rh.advance(db, w)                                   # Approved + committed (Phase 6)
    db.refresh(w.run)
    patch_seams(monkeypatch, tmp_path)
    rel = schema_release(db) if release else None
    employer_ready(db, w, **employer)
    return SimpleNamespace(**vars(w), release=rel)


def mock(monkeypatch, **script):
    return install(monkeypatch, MockPac(**script))


def docs(db, run):
    from app.modules.payroll.models import PayrollMxCfdiDocument

    return db.query(PayrollMxCfdiDocument).filter(PayrollMxCfdiDocument.payroll_run_id == run.id).all()


def events(db, doc):
    from app.modules.payroll.models import PayrollMxCfdiEvent

    return [e.event_type for e in db.query(PayrollMxCfdiEvent).filter(PayrollMxCfdiEvent.document_id == doc.id)
            .order_by(PayrollMxCfdiEvent.id)]


def process(db, w):
    from app.modules.payroll import mexico_cfdi_service as S

    return S.process_outbox(db, w.org.id, w.users[0].id)
