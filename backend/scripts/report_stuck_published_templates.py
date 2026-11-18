"""DRY RUN, READ ONLY: report templates caught in the "Published trap", and what
the four-eyes change (migration d7a3f1c9e5b2, 2026-11-18) would answer for each.

    cd backend && python -m scripts.report_stuck_published_templates [--all-published]

MAKER-CHECKER CHANGE — requires ZP-PRIV review (Rugvedh) before merge.

Before the change, every status change overwrote updated_by_id, so a template
whose APPROVER also clicked Published ended with approved_by_id == updated_by_id
and Active was refused for everyone. For each such template this prints:
  - the content editor the migration WILL backfill (from the audit log only:
    the latest content change's actor; none when the seed wrote it), and
  - who could then activate it, in three groups:
      A. activatable after the fix (four-eyes passes and the country gate has no refusal now);
      B. still blocked by the COUNTRY activation gate (its hook's own reason; unchanged by this fix);
      C. still blocked by four-eyes (the approver is also the content editor): recovery = a new version.
Statuses are never changed: activation stays a manual, four-eyes step by a Super Admin.

It never writes: on PostgreSQL the whole run is one READ ONLY transaction, and
the session is rolled back at the end.
"""
import argparse
import sys
from collections import Counter

from sqlalchemy import inspect, text
from sqlalchemy.orm import defer

from app.database import SessionLocal
from app.modules.auth.models import User
from app.modules.payroll import jurisdiction_hooks, service
from app.modules.payroll.models import ReportTemplate


def _who(db, user_id):
    if user_id is None:
        return "none (seed / system)"
    u = db.get(User, user_id)
    return f"user #{user_id}" + (f" ({u.email})" if u is not None else "")


def classify(db, t) -> dict:
    """Dry-run answer for one template. Reads only."""
    editor, audit_id = service.report_template_content_editor_from_audit(db, t)
    probe = ReportTemplate(template_key=t.template_key, version=t.version, status=t.status,
                           jurisdiction_country=t.jurisdiction_country, approved_by_id=t.approved_by_id,
                           content_editor_id=editor)
    four_eyes = service.report_template_four_eyes_refusal(probe, "Active", None)
    opt_in = t.jurisdiction_country in service._APPROVER_NOT_ACTIVATOR_COUNTRIES
    may_activate = (f"any Super Admin except the approver {_who(db, t.approved_by_id)}" if opt_in
                    else "any Super Admin (this country lets the approver activate)")
    hook = None
    if not four_eyes and jurisdiction_hooks.has_module(t.jurisdiction_country):
        # The country gate as it stands today, for a hypothetical activator
        # other than the approver (actor None). Read-only by contract; on
        # PostgreSQL the READ ONLY transaction would refuse any write.
        try:
            hook = jurisdiction_hooks.call(t.jurisdiction_country, "template_activation_refusal", db, t, None)
        except Exception as exc:   # noqa: BLE001 — report it, never act on it
            hook = f"(the country gate could not be evaluated in a dry run: {type(exc).__name__}: {exc})"
    group = "C" if four_eyes else "B" if hook else "A"
    return {"group": group, "editor": editor, "auditId": audit_id, "fourEyes": four_eyes, "hook": hook,
            "mayActivate": may_activate}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--all-published", action="store_true", help="every Published template, not only trapped ones")
    args = parser.parse_args(argv)
    db = SessionLocal()
    try:
        if db.get_bind().dialect.name == "postgresql":
            db.execute(text("SET TRANSACTION READ ONLY"))
        migrated = "content_editor_id" in {c["name"] for c in inspect(db.get_bind()).get_columns(
            ReportTemplate.__tablename__)}
        q = db.query(ReportTemplate).filter(ReportTemplate.status == "Published")
        if not migrated:   # runs before migration d7a3f1c9e5b2 too
            q = q.options(defer(ReportTemplate.content_editor_id))
        if not args.all_published:
            q = q.filter(ReportTemplate.approved_by_id.isnot(None),
                         ReportTemplate.approved_by_id == ReportTemplate.updated_by_id)
        rows = q.order_by(ReportTemplate.jurisdiction_country, ReportTemplate.template_key, ReportTemplate.version).all()
        results = [(t, classify(db, t)) for t in rows]
        scope = "" if args.all_published else " with approved_by_id == updated_by_id (the Published trap)"
        print(f"DRY RUN — READ ONLY — nothing is changed. {len(rows)} Published template(s){scope}.")
        print("By country: " + ", ".join(f"{c} {n}" for c, n in sorted(Counter(t.jurisdiction_country
                                                                                for t, _ in results).items())))
        titles = {"A": "A. Activatable after the fix (manual four-eyes activation)",
                  "B": "B. Still blocked by the COUNTRY activation gate (unchanged by this fix)",
                  "C": "C. Still blocked by four-eyes (approver = content editor): recovery = new version"}
        for g in "ABC":
            group = [(t, r) for t, r in results if r["group"] == g]
            print(f"\n{titles[g]} — {len(group)}"
                  + (f" (by country: {', '.join(f'{c} {n}' for c, n in sorted(Counter(t.jurisdiction_country for t, _ in group).items()))})"
                     if group else ""))
            for t, r in group:
                src = f"audit #{r['auditId']}" if r["auditId"] else "no content-change row"
                print(f"- #{t.id} {t.jurisdiction_country} {t.template_key} v{t.version} [{t.report_type}]: "
                      f"approver {_who(db, t.approved_by_id)}; content editor to backfill {_who(db, r['editor'])} "
                      f"({src})" + (f"; stored now {t.content_editor_id}" if migrated else ""))
                if g == "A":
                    print(f"    -> may activate: {r['mayActivate']}")
                elif g == "B":
                    print(f"    -> country gate: {r['hook']}")
                else:
                    print(f"    -> {r['fourEyes']} Recovery: make a new version (Draft copy), a different Super Admin "
                          "approves it, publish, activate; supersede this one.")
        return 0
    finally:
        db.rollback()
        db.close()


if __name__ == "__main__":
    sys.exit(main())
