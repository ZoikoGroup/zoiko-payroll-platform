"""Belgium (ZP-BE-ENG-001) Block F3: the source inbox register.

Files are hashed, listed in a manifest, and recorded as source artifacts; only a
file marked official is archived (checksum + file), others are UNVERIFIED.
Idempotent by checksum. SYNTHETIC files in a temporary directory."""
import hashlib


def _inbox(tmp_path):
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "README.md").write_text("read me", encoding="utf-8")
    (inbox / "annex3_2026.pdf").write_bytes(b"%PDF-1.4 TEST ONLY official")
    (inbox / "annex3_2026.pdf.meta.txt").write_text("list-id: A1\nofficial: yes\nretrieved: 2026-11-13\n",
                                                    encoding="utf-8")
    (inbox / "blog_copy.html").write_bytes(b"<html>TEST ONLY secondary</html>")
    return inbox


def test_files_are_hashed_and_listed_without_readme_or_meta(tmp_path):
    from scripts.be_source_inbox import be_inbox_files, be_write_manifest

    files = be_inbox_files(_inbox(tmp_path))
    assert [f["name"] for f in files] == ["annex3_2026.pdf", "blog_copy.html"]
    official = files[0]
    assert official["sha256"] == hashlib.sha256(b"%PDF-1.4 TEST ONLY official").hexdigest()
    assert (official["listId"], official["official"], official["retrieved"]) == ("A1", True, "2026-11-13")
    assert files[1]["official"] is False and files[1]["listId"] is None
    manifest = tmp_path / "manifest.md"
    be_write_manifest(files, manifest)
    text = manifest.read_text(encoding="utf-8")
    assert "2 document(s)" in text and official["sha256"] in text


def test_only_official_files_are_archived_and_registration_is_idempotent(db, tmp_path):
    from app.modules.payroll.models import SourceArtifact
    from scripts.be_source_inbox import be_inbox_files, be_register_sources

    files = be_inbox_files(_inbox(tmp_path))
    rows = be_register_sources(db, files)
    db.commit()
    official, secondary = rows
    assert official.checksum_sha256 == files[0]["sha256"] and official.file_path
    assert "[UNVERIFIED" not in official.title and official.reviewer_id is None      # still needs a reviewer
    assert secondary.file_path is None and "[UNVERIFIED]" in secondary.title         # never usable to sign
    again = be_register_sources(db, files)
    assert [r.id for r in again] == [official.id, secondary.id]
    assert db.query(SourceArtifact).filter(SourceArtifact.form_number.like("ZP-BE-SRC-%")).count() == 2

