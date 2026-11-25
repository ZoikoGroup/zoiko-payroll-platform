"""A pack with no statutory rows is described in plain words, never with a
developer file name (Belgium, Malaysia, Poland: wording only, same logic), and
Belgium's signing status says how many catalogue rows the pack holds so the
Readiness tab can show its calm notice. SYNTHETIC data only."""
from datetime import date

import pytest

from app.modules.payroll import jurisdiction_hooks
from app.modules.payroll.models import JurisdictionPack
from tests.test_belgium_super_admin import _c, seeded  # noqa: F401  (pytest fixture)


def _empty(db, country):
    pack = JurisdictionPack(pack_id=f"{country}-SYNTH-EMPTY", version="1.0", jurisdiction_country=country,
                            pack_type="tax", status="Draft", effective_from=date(2030, 1, 1),
                            effective_to=date(2030, 12, 31), tax_year="2030")
    db.add(pack)
    db.commit()
    return pack


@pytest.mark.parametrize("country, adjective", [("BE", "Belgian"), ("MY", "Malaysian"), ("PL", "Polish")])
def test_the_empty_pack_message_is_plain(db, country, adjective):
    hook = jurisdiction_hooks.get(country, "pack_activation_refusal")
    import inspect

    pack = _empty(db, country)
    message = hook(db, pack, None) if len(inspect.signature(hook).parameters) > 2 else hook(db, pack)
    assert message == f"This pack has no {adjective} statutory rows yet. Set up the catalogue and load values first."
    assert ".py" not in message and "seed" not in message.lower()


def test_signing_status_reports_the_catalogue(db, seeded):
    from app.modules.payroll import be_super_admin

    keys = len(_c().KEYS)
    assert be_super_admin.signing_status(db, _empty(db, "BE").id)["catalogue"] == {"rows": 0, "keys": keys}
    assert be_super_admin.signing_status(db, seeded.id)["catalogue"] == {"rows": keys, "keys": keys}
