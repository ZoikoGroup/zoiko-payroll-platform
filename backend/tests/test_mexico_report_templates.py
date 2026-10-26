"""Mexico (ZP-MX-ENG-001) report templates and filing calendar — the 18 Draft
templates of plan v1.1 §5 (17 national + one ISN return per state in scope:
CDMX), idempotent, activation
refused; calendar entries only from rules whose source is VERIFIED."""

from datetime import date

import pytest


def _seed(db, manifest=None):
    from scripts.seed_statutory_report_templates import seed_mexico

    return seed_mexico(db, manifest={} if manifest is None else manifest)


def _mx_templates(db):
    from app.modules.payroll.models import ReportTemplate

    return {t.template_key: t for t in db.query(ReportTemplate).filter(ReportTemplate.jurisdiction_country == "MX")}


def test_all_mexico_templates_are_seeded_draft(db):
    _seed(db)
    templates = _mx_templates(db)
    assert len(templates) == 18                                  # plan v1.1 §5: 17 national + the CDMX ISN return
    assert {t.status for t in templates.values()} == {"Draft"}
    isn = [t for t in templates.values() if t.report_type == "MX_ISN_RETURN"]
    assert [(t.template_key, t.jurisdiction_state) for t in isn] == [("MX-ISN-RETURN-CDMX", "CDMX")]


def test_only_templates_with_data_today_have_components(db):
    from app.modules.payroll.models import ReportTemplateComponent

    _seed(db)
    with_components = set()
    for key, t in _mx_templates(db).items():
        if db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == t.id).count():
            with_components.add(key)
    assert with_components == {"MX-PAYROLL-REGISTER", "MX-EMPLOYER-COST", "MX-JOURNAL"}


def test_reseeding_is_idempotent(db):
    from app.modules.payroll.models import ReportTemplate, ReportTemplateComponentField

    _seed(db)
    first = (db.query(ReportTemplate).count(), db.query(ReportTemplateComponentField).count())
    _seed(db)
    assert (db.query(ReportTemplate).count(), db.query(ReportTemplateComponentField).count()) == first


def test_mexico_template_activation_is_refused(db):
    from app.core.exceptions import BadRequestException

    from app.modules.payroll import jurisdiction_hooks

    _seed(db)
    template = _mx_templates(db)["MX-PAYROLL-REGISTER"]
    assert "refused" in jurisdiction_hooks.call("MX", "template_activation_refusal", db, template, 1)


def test_no_calendar_entry_without_a_transcribed_verified_rule(db, monkeypatch):
    from app.modules.payroll.engine.countries import mexico_content as c

    monkeypatch.setattr(c, "MX_FILING_CALENDAR", ())              # W1-5 transcribed the real rules
    assert _seed(db)["calendar"] == []
    rule = c.FilingRule("MX_ISR_WITHHOLDING", "ISR {year}-{month:02d}", "MONTHLY", "SYNTHETIC", 17, None, None,
                        "S24", "SYNTHETIC")
    monkeypatch.setattr(c, "MX_FILING_CALENDAR", (rule,))
    assert _seed(db, manifest={})["calendar"] == []               # S24 not VERIFIED -> skipped


def test_a_verified_rule_seeds_one_entry_per_period(db, monkeypatch):
    from app.modules.payroll.engine.countries import mexico_content as c

    monthly = c.FilingRule("MX_ISR_WITHHOLDING", "ISR {year}-{month:02d}", "MONTHLY", "SYNTHETIC", 17, None, None,
                           "S24", "SYNTHETIC")
    bimonthly = c.FilingRule("MX_IMSS_BIMONTHLY", "IMSS {year}-{month:02d}", "BIMONTHLY", "SYNTHETIC", 17, None,
                             None, "S10", "SYNTHETIC")
    monkeypatch.setattr(c, "MX_FILING_CALENDAR", (monthly, bimonthly))
    entries = _seed(db, manifest={"S24": {}, "S10": {}})["calendar"]
    isr = sorted((e for e in entries if e.report_type == "MX_ISR_WITHHOLDING"), key=lambda e: e.period_key)
    assert len(isr) == 12 and str(isr[0].due_date) == "2026-02-17" and str(isr[-1].due_date) == "2027-01-17"
    assert len([e for e in entries if e.report_type == "MX_IMSS_BIMONTHLY"]) == 6


def test_an_archive_copy_never_seeds_a_due_date(db, monkeypatch, tmp_path):
    """Phase 11d: due dates are not Draft pack content - only a VERIFIED
    (directly downloaded) source seeds one; an archive copy is skipped."""
    import csv

    from scripts import seed_mexico_canonical_packs as packs

    row = {"code": "S24", "title": "SYNTHETIC", "issuer": "t", "url": "https://example.test/S24", "file": "S24.pdf",
           "sha256": "a" * 64, "bytes": "1", "retrieved_at": "", "content_type": "", "header_version": "",
           "text_layer": "", "status": "", "note": ""}
    counts = {}
    for status in ("ARCHIVE_COPY_VERIFIED", "VERIFIED"):
        path = tmp_path / f"{status}.csv"
        with open(path, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=list(row))
            writer.writeheader()
            writer.writerow({**row, "status": status})
        with open(path.parent / "VERIFICATION_LOG.csv", "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=packs.mexico_sources.LOG_COLUMNS)
            writer.writeheader()
            writer.writerow({"code": "S24", "file": "S24.pdf", "url": row["url"], "final_url": row["url"],
                             "downloaded_at": "2026-10-26T00:00:00Z", "downloader": "test@example.com",
                             "response_bytes": "1", "sha256": row["sha256"], "result": "MATCH"})
        monkeypatch.setattr(packs, "MANIFEST_PATH", path)
        counts[status] = len(packs.load_manifest(statuses=packs.mexico_sources.ACTIVATION_STATUSES))
    assert counts == {"ARCHIVE_COPY_VERIFIED": 0, "VERIFIED": 2}


def test_the_real_calendar_seeds_only_rules_whose_source_is_verified(db):
    """W1-5 / W2-5: ISR (S35 CFF Art. 6 I) and INFONAVIT (S27) rest on archive copies and are skipped; the CDMX ISN rule rests on S22, VERIFIED by a logged
    direct download, so its 12 monthly due dates (the 17th of the next month) seed."""
    from app.modules.payroll.engine.countries import mexico_content as c

    from app.modules.payroll import mexico_sources
    from scripts.seed_mexico_canonical_packs import load_manifest

    assert {r.report_type for r in c.MX_FILING_CALENDAR} == {"MX_ISR_WITHHOLDING", "MX_INFONAVIT", "MX_ISN_RETURN"}
    entries = _seed(db, manifest=load_manifest(statuses=mexico_sources.ACTIVATION_STATUSES))["calendar"]
    assert len(entries) == 12
    assert {e.jurisdiction_state for e in entries} == {"CDMX"} and {e.report_type for e in entries} == {"MX_ISN_RETURN"}
    assert {e.due_date.day for e in entries} == {17}
    assert min(e.due_date for e in entries) == date(2026, 2, 17) and max(e.due_date for e in entries) == date(2027, 1, 17)
