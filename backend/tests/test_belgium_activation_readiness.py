"""Belgium (ZP-BE-ENG-001): the activation readiness report (read-only, Super Admin).

The verdict is always the governed activation gate's own; every blocking reason per row is reported with who clears
it; the source state matches the signing rule; engine gaps / missing vocabularies / open questions / quarterly rate
files are listed as payroll blockers; the report writes nothing; only a Super Admin reads it. SYNTHETIC data only —
the rows are 'signed' directly in the throwaway test database, never through any real pack."""
import hashlib
import io
import zipfile

import pytest

from tests.test_belgium_super_admin import seeded  # noqa: F401  (pytest fixture)


def _report(db, pack):
    from app.modules.payroll.belgium_activation_readiness import be_activation_readiness

    return be_activation_readiness(db, pack.id)


def _gate(db, pack):
    from app.modules.payroll.belgium_service import be_pack_activation_refusal

    return be_pack_activation_refusal(db, pack)


def _archived_reviewed_source(db, form="SYN-RDY-1"):
    from app.modules.payroll.models import SourceArtifact

    src = SourceArtifact(agency="Synthetic", title="SYNTHETIC TEST ONLY source", form_number=form,
                         checksum_sha256=hashlib.sha256(form.encode()).hexdigest(), file_path="synthetic/x.pdf",
                         created_by_id=900, reviewer_id=901)
    db.add(src)
    db.commit()
    return src


def _sign_everything(db, pack, src):
    """Make every catalogue row and slab row look signed, filled and sourced (test database only)."""
    from app.modules.payroll.engine.countries import belgium_content as c
    from app.modules.payroll.models import ContributionRate, TaxSlab

    for r in db.query(ContributionRate).filter_by(jurisdiction_pack_id=pack.id):
        r.label = (r.label or "").replace(c.PENDING_MARK, "").strip() or r.component_key
        r.text_value = c.NOT_SUPPORTED
        r.source_document_id = src.id
    for s in db.query(TaxSlab).filter_by(jurisdiction_pack_id=pack.id):
        s.rate_label = (s.rate_label or "").replace(c.PENDING_MARK, "").strip() or "signed"
        if s.rule_type == c.EARNING_CLASS_RULE:
            s.assessment_basis = "EXCLUDED"
    db.commit()


def test_a_fresh_draft_pack_reports_every_row_and_the_gate_verdict(db, seeded):
    from app.modules.payroll.engine.countries import belgium_content as c

    report = _report(db, seeded)
    assert report["verdict"]["canActivate"] is False
    assert report["verdict"]["gateRefusal"] == _gate(db, seeded)                     # the gate's own words
    assert report["verdict"]["blockingRows"] == report["verdict"]["catalogueRows"] == len(c.KEYS)
    for row in (r for r in report["rows"] if r["blocks"]):
        assert "UNSIGNED" in row["blocks"]                                          # nothing is signed yet
        assert {x["by"] for x in row["clearedBy"]} >= {"SECOND_SUPER_ADMIN"}
    by_key = {r["key"]: r for r in report["rows"]}
    assert "EMPTY" in by_key["be_onss_employee_rate"]["blocks"]                       # every reason, not the first
    assert [p["code"] for p in by_key["be_bssc_pending"]["payrollBlockers"]][:1] == ["M-BSSC"]
    assert any(p["code"] == "NO_VOCABULARY" for p in by_key["be_wht_period_strategy"]["payrollBlockers"])
    assert any(p["code"] == "SOURCE_NOT_ARCHIVED" for p in by_key["be_wht_annex3_amendment_2026"]["payrollBlockers"])
    assert {q["state"] for q in report["afterActivation"]["rateFiles"]} == {"NO_FILE"}
    assert [q["quarter"] for q in report["afterActivation"]["rateFiles"]] == ["20261", "20262", "20263", "20264"]
    assert {d["state"] for d in report["afterActivation"]["decisions"]} == {"OPEN"}
    assert "readiness" in report["afterActivation"]["releaseGates"]                 # gates stay on the Overview


def test_the_verdict_always_follows_the_activation_gate(db, seeded):
    _sign_everything(db, seeded, _archived_reviewed_source(db))
    report = _report(db, seeded)
    assert report["verdict"]["blockingRows"] == 0                                    # no row blocks any more
    gate = _gate(db, seeded)                                                         # golden still refuses
    assert report["verdict"]["canActivate"] is (gate is None)
    assert report["verdict"]["gateRefusal"] == gate
    golden = next(c for c in report["conditions"] if c["code"] == "GOLDEN_CERTIFICATION")
    assert golden["blocking"] is (gate is not None)


def test_an_unsigned_row_with_an_unreviewed_source_needs_a_source_reviewer_first(db, seeded):
    from app.modules.payroll.models import ContributionRate, SourceArtifact

    loose = SourceArtifact(agency="Synthetic", title="SYNTHETIC unreviewed", form_number="SYN-RDY-2",
                           checksum_sha256="b" * 64, file_path="synthetic/y.pdf", created_by_id=900)
    db.add(loose)
    db.commit()
    row = db.query(ContributionRate).filter_by(jurisdiction_pack_id=seeded.id,
                                               component_key="be_onss_employee_rate").one()
    row.employee_rate_pct, row.source_document_id = 1, loose.id
    db.commit()
    entry = next(r for r in _report(db, seeded)["rows"] if r["key"] == "be_onss_employee_rate")
    assert entry["blocks"] == ["UNSIGNED"]                                           # filled and sourced now
    assert entry["source"] == {"id": loose.id, "reference": "SYN-RDY-2", "state": "ARCHIVED_NOT_REVIEWED",
                               "signable": False}
    assert any(c["by"] == "SOURCE_REVIEWER" for c in entry["clearedBy"])


def test_rate_file_states_are_reported_per_quarter(db, seeded, tmp_path):
    from app.modules.payroll import belgium_onss_rates as r
    from app.modules.payroll.models import SourceArtifact

    xml = ('<?xml version="1.0" encoding="UTF-8"?><ContributionRateFile><Header><FileType>x</FileType><Quarter>20263'
           '</Quarter><FormCreationDate>2026-09-15</FormCreationDate><FormCreationHour>11:00:00.000</FormCreationHour>'
           '</Header><ContributionRate><EmployerClass>000</EmployerClass><ContributionWorkerCode>495'
           '</ContributionWorkerCode><ContributionType>0</ContributionType><PersonalRate>1</PersonalRate><EmployerRate>2'
           '</EmployerRate><SalaryModerationRate>0</SalaryModerationRate><TotalRate>3</TotalRate><IsFlatRate>false'
           '</IsFlatRate></ContributionRate></ContributionRateFile>').encode()
    comb = ('<?xml version="1.0" encoding="UTF-8"?><WorKerAndContributionCombFile><Header><FileType>x</FileType>'
            '<Quarter>20263</Quarter><FormCreationDate>2026-09-15</FormCreationDate><FormCreationHour>11:00:00.000'
            '</FormCreationHour></Header></WorKerAndContributionCombFile>').encode()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("NOSSContributionRate_T.xml", xml)
        z.writestr("NOSSWorkerAndContributionComb_T.xml", comb)
    path = tmp_path / "rate.zip"
    path.write_bytes(buf.getvalue())
    src = SourceArtifact(agency="Synthetic", title="SYNTHETIC rate file", form_number="SYN-RDY-RATE",
                         checksum_sha256=hashlib.sha256(buf.getvalue()).hexdigest(), file_path=str(path))
    db.add(src)
    db.commit()
    f = r.be_onss_register_rate_file(db, seeded.id, {"sourceDocumentId": src.id, "effectiveFrom": "2026-07-01",
                                                     "effectiveTo": "2026-09-30", "reason": "TEST ONLY"}, 801)
    db.commit()
    quarters = {q["quarter"]: q for q in _report(db, seeded)["afterActivation"]["rateFiles"]}
    assert quarters["20263"]["state"] == "NOT_ATTESTED" and quarters["20263"]["fileId"] == f.id
    assert quarters["20264"]["state"] == "NO_FILE"


def test_the_report_writes_nothing(db, seeded):
    from sqlalchemy import event

    writes = []

    def watch(_conn, _cursor, statement, *_a, **_k):
        if statement.lstrip().split(" ", 1)[0].upper() in ("INSERT", "UPDATE", "DELETE"):
            writes.append(statement[:80])

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", watch)
    try:
        _report(db, seeded)
    finally:
        event.remove(engine, "before_cursor_execute", watch)
    assert writes == []


def test_only_a_super_admin_reads_it(db, seeded):
    from tests._mx_employer_helpers import SUPER_ADMIN, http, make_org, principal

    url = f"/api/super-admin/compliance/belgium/packs/{seeded.id}/activation-readiness"
    with http(db, SUPER_ADMIN) as client:
        res = client.get(url)
        assert res.status_code == 200 and res.json()["pack"]["packId"] == "BE-PAYROLL-2026"
        assert client.get("/api/super-admin/compliance/belgium/packs/999999/activation-readiness").status_code == 404
    org = make_org(db, name="Readiness BV", code="BERDY", admins=1, country="BE")
    with http(db, principal(org.org.id, org.users[0].id)) as client:
        assert client.get(url).status_code in (401, 403, 404)
