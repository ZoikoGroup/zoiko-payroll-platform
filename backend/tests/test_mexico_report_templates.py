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
    assert len(templates) == 26          # plan v1.1 §5: 17 national + the CDMX ISN return; final mile X3: + 8
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
    # W4-1 (Phase 12a): the six template-engine reports are filled; the rest wait for W4-2's dedicated generators
    assert with_components == {"MX-PAYROLL-REGISTER", "MX-EMPLOYER-COST", "MX-JOURNAL", "MX-SUBSIDY", "MX-IMSS-BRANCH",
                               "MX-INFONAVIT", "MX-AGUINALDO", "MX-FINIQUITO", "MX-ANNUAL-ISR-ADJ"}


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
    """W1-5 / W2-5 / A18: ISR (S35 CFF Art. 6 I), INFONAVIT (S27) and IMSS / IMSS RCV (S10) rest on archive copies and are skipped; the CDMX ISN rule rests on S22, VERIFIED by a logged
    direct download, so its 12 monthly due dates (the 17th of the next month) seed."""
    from app.modules.payroll.engine.countries import mexico_content as c

    from app.modules.payroll import mexico_sources
    from scripts.seed_mexico_canonical_packs import load_manifest

    assert {r.report_type for r in c.MX_FILING_CALENDAR} == {"MX_ISR_WITHHOLDING", "MX_INFONAVIT", "MX_ISN_RETURN",
                                                             "MX_IMSS", "MX_IMSS_RCV"}
    entries = _seed(db, manifest=load_manifest(statuses=mexico_sources.ACTIVATION_STATUSES))["calendar"]
    assert len(entries) == 12
    assert {e.jurisdiction_state for e in entries} == {"CDMX"} and {e.report_type for e in entries} == {"MX_ISN_RETURN"}
    assert {e.due_date.day for e in entries} == {17}
    assert min(e.due_date for e in entries) == date(2026, 2, 17) and max(e.due_date for e in entries) == date(2027, 1, 17)


# ── W4-1 (Phase 12a): snapshot-bound templates ───────────────────────────────

def _json_fields(db):
    from app.modules.payroll.models import ReportTemplateComponent, ReportTemplateComponentField

    out = []
    for key, t in _mx_templates(db).items():
        for comp in db.query(ReportTemplateComponent).filter(ReportTemplateComponent.report_template_id == t.id):
            for f in db.query(ReportTemplateComponentField).filter(ReportTemplateComponentField.component_id == comp.id):
                if f.data_source_kind == "PAYSLIP_ITEM_JSON":
                    out.append((key, comp.component_key, f))
    return out


def test_every_mexico_snapshot_path_is_in_the_mexico_catalog(db):
    from app.modules.payroll import service

    _seed(db)
    fields = _json_fields(db)
    assert len(fields) > 60
    for key, _comp, f in fields:
        assert f.source_column in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG["MX"], (key, f.source_column)
    # no other country's path uses the keyed selector, so the shared resolver's old route is untouched for them
    for country, paths in service._PAYSLIP_ITEM_JSON_FIELD_CATALOG.items():
        if country != "MX":
            assert not any("[" in p for p in paths), country


def test_the_keyed_selector_picks_sums_and_misses():
    from app.modules.payroll import service

    blob = {"imss": [{"branch": "IV", "side": "employer", "amount": "10.50"},
                     {"branch": "IV", "side": "employee", "amount": "3.75"},
                     {"branch": "CEAV", "side": "employer", "amount": "7"}]}
    walk = service._report_json_path_value
    assert walk(blob, ["imss[branch=IV,side=employer]", "amount"]) == "10.50"
    assert walk(blob, ["imss[branch=IV]", "amount"]) == "14.25"                 # several match: summed
    assert walk(blob, ["imss[branch=RETIRO]", "amount"]) is None                # none match
    assert walk(blob, ["nothing[branch=IV]", "amount"]) is None
    assert walk({"imss": [{"branch": "IV", "label": "x"}, {"branch": "IV", "label": "y"}]},
                ["imss[branch=IV]", "label"]) is None                           # text never summed


def _snapshots_of_each_run_type(db, monkeypatch):
    """Real committed snapshots: an ordinary run, an aguinaldo run, a finiquito
    and a run applying an annual adjustment (synthetic rules, as their own tests)."""
    from datetime import date as _date

    from tests import _mx_authority_helpers as ah
    from tests import test_mexico_annual_adjustment as A
    from tests import test_mexico_benefits as B
    from tests import test_mexico_termination as T

    def snap(run):
        (item,) = ah.rh.mx_items(db, run)
        return item.mx_calculation_snapshot

    out = {}
    w = ah.committed_world(db, monkeypatch, code="MXRPT1")
    out["ordinary"] = snap(w.run)
    B._rules(monkeypatch)
    out["aguinaldo"] = snap(B._aguinaldo(db, ah.committed_world(db, monkeypatch, code="MXRPT2")))
    T._rules(monkeypatch)
    wt = ah.committed_world(db, monkeypatch, code="MXRPT3")
    out["finiquito"] = snap(T._finiquito(db, wt, T._approved(db, wt)["id"]))
    A._rules(monkeypatch)
    wa = A._world(db, monkeypatch, "MXRPT4")
    A._approved(db, wa)
    A._extend_content_to(db)
    jan = A._jan_run(db, wa)
    A._S().apply_to_run(db, wa.org.id, {**A._key(wa), "run_id": jan.id}, wa.users[0].id)
    from app.modules.payroll import service

    service.generate_payslips_for_run(db, jan, wa.org.id, [wa.employee.id])
    out["annual"] = snap(jan)
    return out


_RUN_TYPE_OF = {"MX-AGUINALDO": "aguinaldo", "MX-FINIQUITO": "finiquito", "MX-ANNUAL-ISR-ADJ": "annual"}


def test_every_path_resolves_on_a_real_snapshot_of_its_run_type(db, monkeypatch):
    """Plain paths must resolve. A keyed path must reach an existing list; it may
    match nothing when this case has no such item (e.g. no seniority premium in a
    synthetic finiquito) — that is the documented None, never a 0."""
    from app.modules.payroll import service

    snaps = _snapshots_of_each_run_type(db, monkeypatch)
    _seed(db)
    resolved_selectors = 0
    for key, _comp, f in _json_fields(db):
        snap = snaps[_RUN_TYPE_OF.get(key, "ordinary")]
        column, _, path = f.source_column.partition(".")
        segments = [s for s in path.split(".") if s]
        if "[" not in path:
            assert service._report_json_walk(snap, segments), (key, f.source_column)
            continue
        listname = next(s for s in segments if "[" in s).split("[")[0]
        parent = service._report_json_walk(snap, segments[:next(i for i, s in enumerate(segments) if "[" in s)])
        assert parent and isinstance(parent[0].get(listname), list), (key, f.source_column)
        resolved_selectors += bool(service._report_json_walk(snap, segments))
    assert resolved_selectors >= 20                     # IMSS branches, aguinaldo, vacation, indemnity …


def _publish(db, template):
    from app.modules.auth.models import User, UserRole
    from app.modules.payroll import service

    approver = User(email=f"mx-approver-{template.id}@example.com", hashed_password="x", role=UserRole.PAYROLL_ADMIN,
                    first_name="T", last_name="U")
    db.add(approver)
    db.commit()
    service.set_report_template_approver(db, template.id, actor_id=approver.id)
    return service.set_report_template_status(db, template.id, "Published", actor_id=None)


def test_employer_cost_and_register_return_the_engines_own_figures(db, monkeypatch):
    from decimal import Decimal

    from app.modules.payroll import service
    from tests import _mx_authority_helpers as ah

    w = ah.committed_world(db, monkeypatch, code="MXRPT5")
    (item,) = ah.rh.mx_items(db, w.run)
    res = item.mx_calculation_snapshot["result"]
    _seed(db)
    for key in ("MX-EMPLOYER-COST", "MX-PAYROLL-REGISTER"):      # Published (Mexico activation is W4-3's gate)
        _publish(db, _mx_templates(db)[key])
    cost = service.generate_report_from_template(db, w.org.id, _mx_templates(db)["MX-EMPLOYER-COST"].id, w.run.id,
                                                 reporting_period=w.run.period_label, actor_id=None)
    totals = cost.rendered_data["employer"]                                    # run-level (SUM_RUN) fields
    for field, path in (("imss_employer", "imss_employer"), ("infonavit_employer", "infonavit_employer"),
                        ("employer_total", "employer_total"), ("gross_pay", "gross")):
        assert totals[field] == float(Decimal(res[path])), field
    assert totals["isn"] == float(Decimal(res["isn"]["amount"]))
    assert totals["employer_total"] > 0                                        # no longer the always-0 columns
    register = service.generate_report_from_template(db, w.org.id, _mx_templates(db)["MX-PAYROLL-REGISTER"].id,
                                                     w.run.id, reporting_period=w.run.period_label, actor_id=None)
    (row,) = register.rendered_data["employees"]
    assert row["values"]["isr"] == float(Decimal(res["isr_withheld"]))
    assert row["values"]["imss_employee"] == float(Decimal(res["imss_employee"]))
    assert row["values"]["subsidy_applied"] == float(Decimal(res["subsidy"]["applied"]))


# ── W4-3a (Phase 12c, plan E6): the activation gate ─────────────────────────

def _signed(monkeypatch, unsigned=()):
    from app.modules.payroll import mexico_service

    monkeypatch.setattr(mexico_service, "gate_states", lambda db: [
        {"gate": f"G{i}", "state": "OPEN" if f"G{i}" in unsigned else "SIGNED"} for i in range(1, 9)])


def _active_pack(db, pack_id, state=None):
    from app.modules.payroll.models import JurisdictionPack

    db.add(JurisdictionPack(pack_id=pack_id, jurisdiction_country="MX", jurisdiction_state=state, version="1.0",
                            pack_type="tax", status="Active", effective_from=date(2026, 1, 1),
                            effective_to=date(2026, 12, 31)))
    db.commit()


def _refusal(db, template):
    from app.modules.payroll import jurisdiction_hooks

    return jurisdiction_hooks.call("MX", "template_activation_refusal", db, template, 1)


def test_activation_needs_signed_gates_active_content_and_proven_fields(db, monkeypatch):
    from tests import _mx_authority_helpers as ah

    _seed(db)
    register = _mx_templates(db)["MX-PAYROLL-REGISTER"]
    why = _refusal(db, register)                                       # today: nothing signed, no Active pack
    assert "G1" in why and "MX-PAYROLL-2026 is not Active" in why
    assert "no committed Mexican ordinary/correction payslip" in why
    ah.committed_world(db, monkeypatch, code="MXGATE1")                 # a real committed payslip proves the fields
    assert "no committed Mexican" not in _refusal(db, register)
    _signed(monkeypatch, unsigned=("G3",))
    _active_pack(db, "MX-PAYROLL-2026")
    why = _refusal(db, register)
    assert "G3" in why and "G1" not in why and "MX-PAYROLL-2026" not in why
    _signed(monkeypatch)
    assert _refusal(db, register) is None


def test_an_isn_return_also_needs_its_state_pack_and_g4(db, monkeypatch):
    _seed(db)
    isn = _mx_templates(db)["MX-ISN-RETURN-CDMX"]
    _signed(monkeypatch, unsigned=("G4",))
    _active_pack(db, "MX-PAYROLL-2026")
    why = _refusal(db, isn)
    assert "G4" in why and "MX-ISN-CDMX-2026 is not Active" in why
    _signed(monkeypatch)
    _active_pack(db, "MX-ISN-CDMX-2026", "CDMX")
    assert _refusal(db, isn) is None                                   # a dedicated report: no field proof needed
