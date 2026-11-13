"""Belgium Block C test helpers: SYNTHETIC TEST ONLY filing content.

install_filing_content() re-patches belgium_service._be_pack_for (the same seam
the run-lifecycle tests use; the real Draft pack is never signed or activated)
with the synthetic pack plus signed schema-version rows, makes every signed
version "archived" with a synthetic XSD and registers a synthetic renderer.
Version names are made up ("TEST-A", "TEST-B"); nothing here is an official
schema."""
from tests._be_engine_helpers import START, build_pack, rate, slab

SYNTHETIC_XSD = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
  <xs:element name="testOnlyFiling">
    <xs:complexType>
      <xs:attribute name="form" type="xs:string" use="required"/>
      <xs:attribute name="hash" type="xs:string" use="required"/>
    </xs:complexType>
  </xs:element>
</xs:schema>"""


def synthetic_renderer(payload):
    import hashlib
    import json

    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()
    return f'<testOnlyFiling form="{payload.get("form")}" hash="{digest}"/>'.encode()


def broken_renderer(payload):
    return b"<testOnlyFiling/>"                         # misses required attributes -> XSD errors


ALL_FORMS = ("DIMONA", "DMFA", "FINPROF", "BELCOTAX")


def _real_archived_schema():
    from app.modules.payroll import belgium_filing as bf

    return bf.archived_schema


REAL_ARCHIVED_SCHEMA = _real_archived_schema()            # captured before any test patches it


def install_filing_content(monkeypatch, versions=None, archived=True, renderer=synthetic_renderer):
    """versions: {form: [(effective_from, effective_to, name), ...]}; default:
    one open TEST-A version from START for every form."""
    from app.modules.payroll import belgium_filing as bf
    from app.modules.payroll import belgium_service as be
    from app.modules.payroll.engine.countries import belgium_content as c
    from app.modules.payroll.engine.jurisdictions.belgium.pack import BePack

    versions = versions if versions is not None else {f: [(START, None, "TEST-A")] for f in ALL_FORMS}
    markers = {bf.SCHEMA_KEYS[f]: rate(bf.SCHEMA_KEYS[f], text=c.SLAB_ROWS) for f in versions}
    rows = [slab(bf.SCHEMA_KEYS[f], name=name, start=start, end=end)
            for f, windows in versions.items() for start, end, name in windows]
    rate_map, slabs = build_pack(rates_over=markers, slabs_over=rows)
    monkeypatch.setattr(be, "_be_pack_for", lambda db, org, on: BePack(rate_map, slabs, org, on))
    monkeypatch.setattr(bf, "archived_schema", lambda db, row: SYNTHETIC_XSD if archived else None)
    for form, windows in versions.items():
        for _s, _e, name in windows:
            if renderer is not None:
                monkeypatch.setitem(bf.RENDERERS, (form, name), renderer)


def accept(db, org, filing, approver, recorder, ref, submission_date=None):
    """VALIDATE -> APPROVE (approver) -> submission -> ACCEPTED (recorder)."""
    from app.modules.payroll import belgium_filing as bf

    bf.validate_be_filing(db, org, filing.id, recorder, submission_date)
    assert filing.status == "VALIDATED", filing.validation_note
    bf.approve_be_filing(db, org, filing.id, approver, on=submission_date)
    bf.record_be_filing_submission(db, org, filing.id, {"submissionRef": f"SUB-{ref}", "mandateRef": "TEST ONLY"},
                                   recorder, on=submission_date)
    bf.record_be_filing_response(db, org, filing.id, {"outcome": "ACCEPTED", "receiptRef": f"RCPT-{ref}"}, recorder)
    db.commit()
    return filing


def accept_dimona_in(db, org, employee_id, creator, approver):
    """Every employment line of the employee gets an ACCEPTED Dimona IN."""
    from app.modules.payroll import belgium_filing as bf

    rows = bf.build_be_dimona_events(db, org, employee_id, creator)
    db.commit()
    for row in rows:
        if (row.payload or {}).get("event") == "IN" and row.status != "ACCEPTED":
            accept(db, org, row, approver, creator, f"DIM{row.id}")
    return rows
