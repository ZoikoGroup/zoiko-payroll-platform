"""
tests/_sg_evidence.py
---------------------
Phase 6.10 test helper: an ACCEPTED Singapore gate artifact (disposable test
data, never real evidence), stored exactly as the summary evaluates one —
creator on record, a DIFFERENT reviewer, a document reference and a SHA-256
(statutory_summary._artifact_status). Written as rows, so no file lands on
disk. Pack activation needs G1 accepted since Phase 6.10.

app.* imports are lazy (tests/_db_safety.py).
"""

SG_TEST_CREATOR, SG_TEST_REVIEWER = 9101, 9202


def accept_sg_gate(db, gate="G1"):
    from datetime import datetime

    from app.modules.payroll.models import SourceArtifact

    art = SourceArtifact(agency="Test evidence", title=f"Disposable {gate} test evidence", form_number=f"SG-GATE-{gate}",
                         checksum_sha256="e" * 64, file_path=f"test-only/{gate}.pdf", created_by_id=SG_TEST_CREATOR,
                         reviewer_id=SG_TEST_REVIEWER, reviewer_approved_at=datetime.utcnow())
    db.add(art)
    db.commit()
    db.refresh(art)
    return art
