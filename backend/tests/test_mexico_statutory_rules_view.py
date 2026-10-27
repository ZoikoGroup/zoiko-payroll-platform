"""Super Admin read-only views of the Mexico content that is not stored as
pack rows (completion W5-1): special pay, termination, PTU, annual adjustment,
filing calendar, working time, ISN inclusion and the annual ISR tariff — each
with its quoted source wording, the manifest row of the cited file and the
[PENDING G1] marker; and one state ISN pack's rows with their sources."""

from datetime import date
from decimal import Decimal

import pytest

from tests.test_mexico_router import BASE, ORG_ADMIN, SA_A, _http


def _view(db, on=None):
    from app.modules.payroll import mexico_service

    return mexico_service.statutory_rules_view(db, on=on)


def test_every_rule_citation_compare_checks_is_shown(db):
    """The view and `verify_mexico_sources.py compare` cover the same rules:
    nothing the release checks is hidden from the Super Admin."""
    from app.modules.payroll.engine.countries import mexico_content as c
    from scripts import verify_mexico_sources as v

    shown = {(x["cite"], x["ref"]) for f in _view(db, on=date(2026, 6, 1))["families"]
             for i in f["items"] for x in i["citations"]}
    checked = {(src, ref) for _label, src, ref in v._rule_citations(c)}
    assert checked and checked <= shown


def test_every_item_is_read_only_pending_g1_and_sourced(db):
    body = _view(db, on=date(2026, 6, 1))
    assert body["editable"] is False and "compare" in body["editVia"]
    items = [i for f in body["families"] for i in f["items"]]
    assert items and all(i["pendingG1"] for i in items)
    assert all(x["ref"] and x["cite"] for i in items for x in i["citations"])
    assert body["manifestAvailable"] is True
    statuses = {x["status"] for i in items for x in i["citations"]}
    assert "NOT_IN_MANIFEST" not in statuses                       # every cited file is a manifest row
    assert {f["family"] for f in body["families"]} == {
        "annualIsr", "filingCalendar", "specialPay", "isnInclusion", "termination", "ptu", "annualAdjustment",
        "ordinaryExemptions", "workingTime"}


def test_year_keyed_families_follow_the_selected_date(db):
    y2026 = {f["family"]: f for f in _view(db, on=date(2026, 6, 1))["families"]}
    y2025 = {f["family"]: f for f in _view(db, on=date(2025, 6, 1))["families"]}
    assert len(y2026["annualIsr"]["items"]) == 11 and y2026["annualIsr"]["items"][0]["lower"] == "0.01"
    assert y2025["annualIsr"]["items"] == [] and y2025["annualIsr"]["awaitingTranscription"] is True
    assert "D-16" in y2026["workingTime"]["note"]                  # no official holidays transcribed


def test_without_a_pack_and_without_a_date_nothing_uses_the_server_date(db):
    body = _view(db)
    assert body["pack"] is None and body["on"] is None and body["onSource"] is None
    assert next(f for f in body["families"] if f["family"] == "annualIsr")["items"] == []


def test_open_decisions_are_listed_undecided(db):
    decisions = {d["decision"]: d for d in _view(db, on=date(2026, 6, 1))["decisions"]}
    for key in ("D-07", "D-08", "D-09", "D-12", "D-13", "D-07b", "D-14", "D-18", "D-19"):
        assert decisions[key]["decided"] is False


def test_statutory_rules_route_is_super_admin_only(db):
    with _http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}/statutory-rules").status_code == 403
        assert c.get(f"{BASE}/isn-content", params={"pack_id": 1}).status_code == 403
    with _http(db, SA_A) as c:
        r = c.get(f"{BASE}/statutory-rules", params={"on": "2026-03-01"})
    assert r.status_code == 200 and r.json()["on"] == "2026-03-01" and r.json()["onSource"] == "query"


@pytest.fixture()
def isn_seeded(db, monkeypatch):
    """SYNTHETIC: one CDMX ISN row (9%) from a SYNTHETIC verified source."""
    from app.modules.payroll.engine.countries import mexico_content as c
    from scripts.seed_mexico_canonical_packs import seed_mexico

    for table in ("MX_ISR_TARIFFS", "MX_MIN_WAGES", "MX_ZLFN_MUNICIPALITIES", "MX_CEAV_SCHEDULE", "MX_WORKWEEK",
                  "MX_VACATION_DAYS", "MX_SCALAR_CONTENT"):
        monkeypatch.setattr(c, table, ())
    isn = {state: () for state in c.MX_ISN_CONTENT}
    isn["CDMX"] = (c.ScalarRow("mx_isn_rate_pct", None, "9", None, None, None, None, "S6", "SYNTHETIC"),)
    monkeypatch.setattr(c, "MX_ISN_CONTENT", isn)
    manifest = {"S6": {"code": "S6", "title": "SYNTHETIC", "issuer": "t", "url": "https://example.test/S6",
                       "file": "S6.pdf", "sha256": "d" * 64, "bytes": "1", "retrieved_at": "2026-10-15T00:00:00Z",
                       "content_type": "application/pdf", "header_version": "t", "text_layer": "yes",
                       "status": "VERIFIED", "note": ""}}
    seed_mexico(db, manifest=manifest)
    db.commit()


def test_a_state_isn_pack_shows_its_rows_with_sources(db, isn_seeded):
    with _http(db, SA_A) as c:
        states = c.get(f"{BASE}/isn-states").json()
        cdmx = next(s for s in states if s["code"] == "CDMX")["packs"][0]
        body = c.get(f"{BASE}/isn-content", params={"pack_id": cdmx["id"]}).json()
        national = c.get(f"{BASE}/packs").json()[0]
        wrong = c.get(f"{BASE}/isn-content", params={"pack_id": national["id"]})
        missing = c.get(f"{BASE}/isn-content")
    assert body["pack"]["state"] == "CDMX" and body["editable"] is False and body["onSource"] == "packEffectiveFrom"
    (row,) = body["rates"]
    assert row["key"] == "mx_isn_rate_pct" and Decimal(row["employerRatePct"]) == 9 and row["pendingG1"] is True
    assert row["source"]["sha256"] == "d" * 64
    assert wrong.status_code == 404 and missing.status_code == 422      # the national pack is not a state pack


def test_every_concept_has_a_readable_label():
    from app.modules.payroll import mexico_service as S
    from app.modules.payroll.engine.countries import mexico_content as c

    concepts = (set(c.MX_SPECIAL_PAY_RULES) | {k[1] for k in c.MX_SPECIAL_PAY_ISN_INCLUSION}
                | {o.kind for o in c.MX_ORDINARY_EXEMPTION_RULES.values()})
    assert concepts and concepts <= set(S._CONCEPT_LABELS)


def test_no_mexico_template_is_described_as_an_unfilled_shell():
    """W5-1: the component-less templates say which generator builds them."""
    from scripts import seed_statutory_report_templates as seed

    for key, t in seed._mx_templates().items():
        assert "Draft shell" not in t["description"], key
        if not t["components"]:
            assert t["description"].startswith("No components:"), key
