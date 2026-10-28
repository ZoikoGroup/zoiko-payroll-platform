"""Mexico final mile X5 (gap C15): the durable CFDI XML store contract, run
against the test-only local store. Write-once, hash checked on write and read,
retention refuses deletion while undecided; production has no store. SYNTHETIC."""

from datetime import date
from pathlib import Path

import pytest

from app.modules.payroll import mexico_xml_store as X
from tests._mx_local_xml_store import LocalXmlStore

KEY = "org/1/run/2/SYN-0001.xml"
XML = b'<?xml version="1.0"?><cfdi:Comprobante xmlns:cfdi="http://www.sat.gob.mx/cfd/4" Folio="SYN-0001"/>'


@pytest.fixture()
def store(tmp_path):
    return LocalXmlStore(tmp_path)


def _code(exc_info):
    return exc_info.value.key


def test_put_records_the_hash_and_get_returns_the_same_bytes(store):
    stored = store.put(KEY, XML, None)
    assert stored.sha256 == X.sha256(XML) and stored.size == len(XML) and stored.retention_until is None
    assert store.get(stored.ref) == XML and store.head(stored.ref) == stored


def test_write_once_same_bytes_is_idempotent_different_bytes_refused(store):
    first = store.put(KEY, XML, date(2031, 12, 31))
    assert store.put(KEY, XML, date(2031, 12, 31)) == first
    with pytest.raises(X.MXRefuse) as e:
        store.put(KEY, XML + b"<!-- edited -->", date(2031, 12, 31))
    assert _code(e) == "MX_CFDI_XML_WRITE_ONCE" and store.get(KEY) == XML


def test_a_tampered_file_is_refused_on_read(store, tmp_path):
    store.put(KEY, XML, None)
    (tmp_path / KEY).write_bytes(XML.replace(b"SYN-0001", b"SYN-9999"))
    with pytest.raises(X.MXRefuse) as e:
        store.get(KEY)
    assert _code(e) == "MX_CFDI_XML_INTEGRITY"


def test_retention_refuses_deletion_while_undecided_or_not_reached(store):
    store.put(KEY, XML, None)
    with pytest.raises(X.MXRefuse) as e:
        store.delete(KEY, date(2099, 1, 1))
    assert _code(e) == "MX_CFDI_XML_RETENTION_UNDECIDED"
    other = "org/1/run/2/SYN-0002.xml"
    store.put(other, XML, date(2031, 12, 31))
    with pytest.raises(X.MXRefuse) as e:
        store.delete(other, date(2031, 12, 30))
    assert _code(e) == "MX_CFDI_XML_RETAINED"
    store.delete(other, date(2031, 12, 31))
    assert store.head(other) is None


@pytest.mark.parametrize("key", ["../etc/passwd.xml", "org/1/run/2/../../x.xml", "org/x/run/2/a.xml",
                                 "org/1/run/2/ABCD010101HDFXYZ01 rfc.xml", "org/1/run/2/a.txt"])
def test_keys_are_checked(store, key):
    with pytest.raises(X.MXRefuse) as e:
        store.put(key, XML, None)
    assert _code(e) == "MX_CFDI_XML_KEY_INVALID"


def test_production_has_no_store_and_app_never_imports_the_local_one():
    assert X._STORE is None
    with pytest.raises(X.MXRefuse) as e:
        X.active_store()
    assert _code(e) == "MX_CFDI_STORAGE_NOT_DURABLE"
    app = Path(__file__).resolve().parents[1] / "app"
    assert not [p for p in app.rglob("*.py") if "_mx_local_xml_store" in p.read_text(encoding="utf-8")]
