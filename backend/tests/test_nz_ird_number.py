"""New Zealand IRD-number boundary (ZP-NZ-ENG-001 Phase 2, nz_ird_number)."""
import base64
import json

import pytest

from app.modules.payroll import nz_ird_number as ird

KEY_1 = "a" * 32
KEY_2 = "b" * 32
FINGERPRINT_KEY = "f" * 32
VALID = "49091850"            # an Inland Revenue check-digit test number
OTHER_VALID = "136410132"


@pytest.fixture(autouse=True)
def keys(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "NZ_IRD_KEYRING", json.dumps({"1": KEY_1}))
    monkeypatch.setattr(settings, "NZ_IRD_FINGERPRINT_KEY", FINGERPRINT_KEY)
    return settings


OWNER = ird.vault_owner(1, ird.SUBJECT_EMPLOYEE, 42, 7)


def test_normalise_pads_and_strips():
    assert ird.normalise("49-091-850") == "049091850"
    assert ird.normalise("136 410 132") == "136410132"


@pytest.mark.parametrize("bad", ["136410133", "9125568", "", "abc", None, 49091850])
def test_invalid_numbers_are_refused(bad):
    with pytest.raises(ird.IrdNumberError):
        ird.normalise(bad)


def test_round_trip():
    ciphertext, version = ird.encrypt(VALID, OWNER)
    assert version == 1
    assert VALID not in ciphertext and "049091850" not in ciphertext
    assert ird.decrypt(ciphertext, version, OWNER) == "049091850"


def test_tampering_raises_the_domain_error_never_invalid_tag():
    ciphertext, version = ird.encrypt(VALID, OWNER)
    blob = bytearray(base64.urlsafe_b64decode(ciphertext))
    blob[-1] ^= 0x01
    with pytest.raises(ird.IrdNumberError):
        ird.decrypt(base64.urlsafe_b64encode(bytes(blob)).decode(), version, OWNER)


def test_ciphertext_moved_to_another_owner_never_decrypts():
    ciphertext, version = ird.encrypt(VALID, OWNER)
    for other in (ird.vault_owner(1, ird.SUBJECT_EMPLOYEE, 43, 7),        # another employee
                  ird.vault_owner(2, ird.SUBJECT_EMPLOYEE, 42, 7),        # another organisation
                  ird.vault_owner(1, ird.SUBJECT_EMPLOYEE, 42, 8),        # another vault row
                  ird.vault_owner(1, ird.SUBJECT_EMPLOYER, 42, 7)):       # an employer subject
        with pytest.raises(ird.IrdNumberError):
            ird.decrypt(ciphertext, version, other)


def test_owner_binding_is_mandatory():
    with pytest.raises(ird.IrdNumberError):
        ird.encrypt(VALID, "")
    with pytest.raises(ird.IrdNumberError):
        ird.vault_owner(1, ird.SUBJECT_EMPLOYEE, 42, None)
    with pytest.raises(ird.IrdNumberError):
        ird.vault_owner(1, ird.SUBJECT_EMPLOYEE, None, 7)
    with pytest.raises(ird.IrdNumberError):
        ird.vault_owner(1, "DEPENDANT", 42, 7)
    assert ird.vault_owner(1, ird.SUBJECT_EMPLOYER, None, 7) == "org=1/employer=org/vault=7"


def test_rotation_keeps_old_rows_readable_and_moves_them_to_the_newest_key(keys, monkeypatch):
    old_ciphertext, old_version = ird.encrypt(VALID, OWNER)
    old_fingerprint = ird.fingerprint(VALID)
    monkeypatch.setattr(keys, "NZ_IRD_KEYRING", json.dumps({"1": KEY_1, "2": KEY_2}))
    assert ird.decrypt(old_ciphertext, old_version, OWNER) == "049091850"
    new_ciphertext, new_version = ird.reencrypt(old_ciphertext, old_version, OWNER)
    assert new_version == 2 and ird.decrypt(new_ciphertext, new_version, OWNER) == "049091850"
    assert ird.fingerprint(VALID) == old_fingerprint                     # duplicate detection survives


def test_unknown_key_version_and_missing_keyring_refuse(keys, monkeypatch):
    ciphertext, _ = ird.encrypt(VALID, OWNER)
    with pytest.raises(ird.IrdNumberError):
        ird.decrypt(ciphertext, 9, OWNER)
    monkeypatch.setattr(keys, "NZ_IRD_KEYRING", "")
    with pytest.raises(ird.IrdNumberError, match="not configured"):
        ird.encrypt(VALID, OWNER)
    monkeypatch.setattr(keys, "NZ_IRD_KEYRING", "not json")
    with pytest.raises(ird.IrdNumberError):
        ird.encrypt(VALID, OWNER)
    monkeypatch.setattr(keys, "NZ_IRD_KEYRING", json.dumps({"1": "short"}))
    with pytest.raises(ird.IrdNumberError):
        ird.encrypt(VALID, OWNER)


def test_fingerprint_is_stable_keyed_and_format_independent(keys, monkeypatch):
    first = ird.fingerprint("49-091-850")
    assert first == ird.fingerprint("049091850") and len(first) == 64
    assert first != ird.fingerprint(OTHER_VALID)
    monkeypatch.setattr(keys, "NZ_IRD_FINGERPRINT_KEY", "g" * 32)
    assert ird.fingerprint(VALID) != first
    monkeypatch.setattr(keys, "NZ_IRD_FINGERPRINT_KEY", "")
    with pytest.raises(ird.IrdNumberError, match="not configured"):
        ird.fingerprint(VALID)


def test_masked_contains_no_digit():
    assert not any(ch.isdigit() for ch in ird.masked())


def test_error_messages_never_contain_the_number():
    for bad in ("136410133", "49091851"):
        try:
            ird.normalise(bad)
        except ird.IrdNumberError as exc:
            assert bad not in str(exc)
