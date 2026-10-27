"""Mexico (ZP-MX-ENG-001) Super Admin API over HTTP — auth, explicit
organisation scoping, read-only date-selected content (never the server
date), ISN states, activation readiness, classifications and CFDI releases.
In-memory SQLite; every content row is SYNTHETIC."""

from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

BASE = "/api/super-admin/compliance/mexico"
SA_A = SimpleNamespace(id=961, organization_id=None, role="super_admin", is_active=True)
SA_B = SimpleNamespace(id=962, organization_id=None, role="super_admin", is_active=True)
ORG_ADMIN = SimpleNamespace(id=963, organization_id=1, role="org_admin", is_active=True)


@contextmanager
def _http(db, principal):
    from tests.test_hong_kong_governance import _http as hk_http

    with hk_http(db, principal) as client:
        yield client


@pytest.fixture()
def seeded(db, monkeypatch):
    """Draft MX packs seeded from SYNTHETIC content: a January and a
    February version of the daily UMA row (values 1 and 2)."""
    from app.modules.payroll.engine.countries import mexico_content as c
    from scripts.seed_mexico_canonical_packs import seed_mexico

    for table in ("MX_ISR_TARIFFS", "MX_MIN_WAGES", "MX_ZLFN_MUNICIPALITIES", "MX_CEAV_SCHEDULE", "MX_WORKWEEK",
                  "MX_VACATION_DAYS"):                         # synthetic UMA rows only (Batches 1-2 filled these)
        monkeypatch.setattr(c, table, ())
    monkeypatch.setattr(c, "MX_ISN_CONTENT", {state: () for state in c.MX_ISN_CONTENT})   # W1-2 filled CDMX
    monkeypatch.setattr(c, "MX_SCALAR_CONTENT", (
        c.ScalarRow("mx_uma_daily", None, None, "1", None, date(2026, 1, 1), date(2026, 1, 31), "S6", "SYNTHETIC"),
        c.ScalarRow("mx_uma_daily", None, None, "2", None, date(2026, 2, 1), date(2026, 12, 31), "S6", "SYNTHETIC"),
    ))
    manifest = {"S6": {"code": "S6", "title": "SYNTHETIC", "issuer": "t", "url": "https://example.test/S6",
                       "file": "S6.pdf", "sha256": "c" * 64, "bytes": "1", "retrieved_at": "2026-10-15T00:00:00Z",
                       "content_type": "application/pdf", "header_version": "t", "text_layer": "yes",
                       "status": "VERIFIED", "note": ""}}
    out = seed_mexico(db, manifest=manifest)
    db.commit()
    return out


@pytest.mark.parametrize("path", ["/readiness", "/organizations", "/packs", "/isr-tariffs", "/isn-states",
                                  "/earning-classifications", "/cfdi-catalogs"])
def test_every_route_is_super_admin_only(db, path):
    with _http(db, ORG_ADMIN) as c:
        assert c.get(f"{BASE}{path}").status_code == 403


def test_super_admin_never_lists_mexican_employees(db):
    # ZP-PRIV: worker-level data needs a live JIT support grant; the route is
    # retired for platform principals in the route registry.
    with _http(db, SA_A) as c:
        assert c.get(f"{BASE}/employees").status_code == 403
        assert c.get(f"{BASE}/employees", params={"org_id": 99999}).status_code == 403


def test_content_defaults_to_the_pack_effective_from_never_today(db, seeded):
    with _http(db, SA_A) as c:
        body = c.get(f"{BASE}/uma-min-wage").json()["uma"]
    assert (body["on"], body["onSource"], body["editable"]) == ("2026-01-01", "packEffectiveFrom", False)
    assert [Decimal(r["amount"]) for r in body["rates"]] == [Decimal("1")]
    assert body["rates"][0]["pendingG1"] is True and body["rates"][0]["source"]["sha256"] == "c" * 64


def test_an_explicit_date_selects_the_row_in_force(db, seeded):
    with _http(db, SA_A) as c:
        jan = c.get(f"{BASE}/uma-min-wage", params={"on": "2026-01-31"}).json()["uma"]
        feb = c.get(f"{BASE}/uma-min-wage", params={"on": "2026-02-01"}).json()["uma"]
    assert [Decimal(r["amount"]) for r in jan["rates"]] == [Decimal("1")] and jan["onSource"] == "query"
    assert [Decimal(r["amount"]) for r in feb["rates"]] == [Decimal("2")]


@pytest.mark.parametrize("path", ["/isr-tariffs", "/imss-branches", "/ceav-schedule", "/infonavit",
                                  "/benefits-workweek"])
def test_empty_families_say_awaiting_transcription(db, seeded, path):
    with _http(db, SA_A) as c:
        body = c.get(f"{BASE}{path}").json()
    assert body["awaitingTranscription"] is True and body["rates"] == [] and body["slabs"] == []


def test_without_any_pack_content_is_awaiting_transcription(db):
    with _http(db, SA_A) as c:
        body = c.get(f"{BASE}/isr-tariffs").json()
    assert body["pack"] is None and body["awaitingTranscription"] is True


def test_isn_states_lists_all_32_entities_and_blocks_unsupported_ones(db, seeded):
    with _http(db, SA_A) as c:
        states = c.get(f"{BASE}/isn-states").json()
    assert len(states) == 32 and len({s["code"] for s in states}) == 32
    cdmx = next(s for s in states if s["code"] == "CDMX")
    assert cdmx["inScope"] and [p["packId"] for p in cdmx["packs"]] == ["MX-ISN-CDMX-2026"]
    assert cdmx["readiness"]["program"] == "OTHER_STATE_PAYROLL"
    assert {s["payroll"] for s in states} == {"BLOCKED"}          # nothing Active anywhere
    assert sum(1 for s in states if s["packs"]) == 1


def test_activation_readiness_lists_every_gate(db, seeded):
    pack_id = seeded["national"].id
    with _http(db, SA_A) as c:
        body = c.get(f"{BASE}/packs/{pack_id}/activation-readiness").json()
        assert c.get(f"{BASE}/packs/999999/activation-readiness").status_code == 404
    assert [ch["key"] for ch in body["checks"]] == ["content", "evidence", "sources_verified", "g1_review", "golden"]
    assert body["activatable"] is False


def test_packs_lists_national_then_state(db, seeded):
    with _http(db, SA_A) as c:
        packs = c.get(f"{BASE}/packs").json()
    assert [(p["packId"], p["state"]) for p in packs] == [("MX-PAYROLL-2026", None), ("MX-ISN-CDMX-2026", "CDMX")]


def test_classification_four_eyes_over_http(db, organization):
    payload = {"organizationId": organization.id, "earningCode": "BONO", "label": "SYNTHETIC bonus",
               "effectiveFrom": "2026-01-01", "isrTreatment": "TAXABLE", "sbcTreatment": "VARIABLE",
               "infonavitIncluded": True, "isnDefaultIncluded": True, "ptuWageBaseIncluded": False,
               "cfdiNodeType": "PERCEPCION"}
    with _http(db, SA_A) as c:
        created = c.post(f"{BASE}/earning-classifications", json=payload).json()
        assert created["status"] == "DRAFT"
        assert c.post(f"{BASE}/earning-classifications/{created['id']}/approve").status_code == 400
        missing = dict(payload, earningCode="X")
        del missing["infonavitIncluded"]
        assert c.post(f"{BASE}/earning-classifications", json=missing).status_code == 422   # no axis defaults
    with _http(db, SA_B) as c:
        assert c.post(f"{BASE}/earning-classifications/{created['id']}/approve").json()["status"] == "ACTIVE"
        rows = c.get(f"{BASE}/earning-classifications", params={"org_id": organization.id, "on": "2026-03-01"}).json()
    assert [r["earningCode"] for r in rows] == ["BONO"]


def test_cfdi_release_activation_is_refused_over_http(db):
    with _http(db, SA_A) as c:
        rel = c.post(f"{BASE}/cfdi-catalogs", json={"cfdiVersion": "4.0", "complementVersion": "1.2"}).json()
        assert c.put(f"{BASE}/cfdi-catalogs/{rel['id']}/submit").json()["status"] == "In Review"
    with _http(db, SA_B) as c:
        assert c.put(f"{BASE}/cfdi-catalogs/{rel['id']}/approve").json()["status"] == "Approved"
        refused = c.put(f"{BASE}/cfdi-catalogs/{rel['id']}/activate")
    assert refused.status_code == 400 and "Phase 7" in refused.text
