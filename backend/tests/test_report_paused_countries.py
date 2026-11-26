"""
tests/test_report_paused_countries.py
-------------------------------------
scripts/report_paused_countries.py must be strictly read-only: it is meant
to be run against production data for review.

  * every SQL statement it issues is recorded: no INSERT / UPDATE / DELETE /
    DDL, and the session never commits;
  * make_read_only puts the transaction in a database-level read-only mode,
    so a write attempted by any helper is refused by the database itself.
"""

import re
from datetime import datetime

import pytest
from sqlalchemy import event, text

WRITE_RE = re.compile(r"^\s*(INSERT|UPDATE|DELETE|REPLACE|MERGE|CREATE|ALTER|DROP|TRUNCATE)\b", re.I)


def _seed(db, organization):
    from app.modules.billing.models import BillingCommercialAuditEvent, OrganizationJurisdiction

    db.add(OrganizationJurisdiction(organization_id=organization.id, country_code="IN", is_primary=True,
                                    status="ACTIVE", activated_at=datetime(2026, 1, 1)))
    db.add(OrganizationJurisdiction(organization_id=organization.id, country_code="US", is_primary=False,
                                    status="OVER_LIMIT", activated_at=datetime(2026, 2, 1)))
    db.add(BillingCommercialAuditEvent(organization_id=organization.id, event_type="JURISDICTION_LIMIT_RECONCILED",
                                       payload={"reason": "plan_changed", "limit_value": 1, "restored": [],
                                                "over_limit": ["US"]}))
    db.commit()


def test_report_issues_only_reads_and_never_commits(db, organization):
    from scripts.report_paused_countries import collect, make_read_only

    _seed(db, organization)
    statements, commits = [], []
    engine = db.get_bind()

    def _record(conn, cursor, statement, params, context, executemany):
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    event.listen(db, "after_commit", lambda session: commits.append(True))
    try:
        assert make_read_only(db) == "sqlite"
        rows = collect(db)
        db.rollback()
    finally:
        event.remove(engine, "before_cursor_execute", _record)
        db.execute(text("PRAGMA query_only = OFF"))

    assert [(r["country_code"], r["pause_reason"]) for r in rows] == [("US", "plan_changed")]
    assert statements, "the report ran no queries at all"
    writes = [s for s in statements if WRITE_RE.match(s)]
    assert writes == [] and commits == []
    # Everything it ran is a read (plus the read-only switch itself).
    assert all(re.match(r"^\s*(SELECT|WITH|PRAGMA query_only)", s, re.I) for s in statements), statements


def test_read_only_mode_makes_the_database_refuse_writes(db, organization):
    from scripts.report_paused_countries import make_read_only

    make_read_only(db)
    try:
        with pytest.raises(Exception, match="readonly|read-only|query_only"):
            db.execute(text("UPDATE organizations SET organization_name = 'x' WHERE id = :id"),
                       {"id": organization.id})
    finally:
        db.rollback()
        db.execute(text("PRAGMA query_only = OFF"))
