"""Scratch SQLite world for the Recibo de nómina v2.0 browser check.

Usage (from backend/):  PAYROLL_DATABASE_URL=sqlite:///<scratchpad>/recibo.db \
                        RECIBO_FILES=<scratchpad>/recibo-files  python <this file>

Four SYNTHETIC Mexican organisations built with the same helpers the tests use
(synthetic builder and signer, the test-only mock PAC, a local XML store):
  MXBRD  draft      — committed run, no CFDI
  MXBRS  stamped    — CFDI stamped by the mock PAC, stamped XML stored
  MXBRC  cancelled  — stamped, then marked CANCELLED with a replacement UUID (SYNTHETIC)
  MXBRP  pilot      — evaluation organisation with a pilot grant (watermarked)
Users are @example.com; the password exists only in this scratch database.
Refuses any database that is not a SQLite file under the scratchpad."""
import os
import sys
from pathlib import Path

url = os.environ.get("PAYROLL_DATABASE_URL", "")
assert url.startswith("sqlite:///") and "scratchpad" in url, f"refusing non-scratch database: {url!r}"
FILES = Path(os.environ["RECIBO_FILES"])
assert "scratchpad" in str(FILES), FILES
BACKEND = Path(__file__).resolve().parents[4] / "backend"
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

from _pytest.monkeypatch import MonkeyPatch  # noqa: E402

from app.core.security import hash_password  # noqa: E402
from app.database import SessionLocal, engine, initialize_database  # noqa: E402

assert "sqlite" in str(engine.url) and "scratchpad" in str(engine.url), engine.url
initialize_database()

PASSWORD = "ReciboCheck!2026"
mp = MonkeyPatch()
db = SessionLocal()

from tests import _mx_cfdi_helpers as ch  # noqa: E402
from tests import _mx_run_helpers as rh  # noqa: E402
from tests import test_mexico_pilot as tp  # noqa: E402
from tests.test_mexico_cfdi_builder import _ready_world  # noqa: E402

from app.modules.payroll import mexico_cfdi_service as S  # noqa: E402

out = {}
for code in ("MXBRD", "MXBRS", "MXBRC"):
    w = _ready_world(db, mp, FILES, code)
    if code != "MXBRD":
        ch.mock(mp)
        S.generate(db, w.run, w.users[0].id)
        ch.process(db, w)
        (doc,) = ch.docs(db, w.run)
        db.refresh(doc)
        assert doc.status == "STAMPED", doc.status
        if code == "MXBRC":
            doc.status, doc.replaced_by_uuid = "CANCELLED", "SYN00000-0000-4000-8000-0000000000C1"
            db.commit()
    out[code] = w
w = tp._pilot_world(db, mp, "MXBRP")
tp.ah.commit(db, w, w.run)
out["MXBRP"] = w

for code, w in out.items():
    for u in w.users:
        u.hashed_password = hash_password(PASSWORD)
        u.is_active, u.is_verified = True, True
    (item,) = rh.mx_items(db, w.run)
    print(code, "login", w.users[0].email, "payslip", item.id, "employee", item.employee_id)
db.commit()
