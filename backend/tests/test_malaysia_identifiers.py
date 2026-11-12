"""Malaysia identifier vault crypto (ZP-MY-ENG-001 Phase 2, spec §15, MY-029):
AES-GCM bound to its owner, versioned keyring with rotation, never-rotated
fingerprint key, generic errors that never contain a value, masks with no
character of the value."""
import json

import pytest

from app.modules.payroll import my_identifiers as mid

NRIC = "900101145678"           # synthetic: valid date + place code; MyKad has no check digit


@pytest.fixture
def keys(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "MY_IDENTIFIER_KEYRING", json.dumps({"1": "k" * 32}))
    monkeypatch.setattr(settings, "MY_IDENTIFIER_FINGERPRINT_KEY", "f" * 32)
    return settings


def _owner(identifier_type=mid.NRIC, vault_id=10, employee_id=7, org=3):
    return mid.vault_owner(org, employee_id, identifier_type, vault_id)


@pytest.mark.parametrize("identifier_type, raw, expected", [
    ("NRIC", "900101-14-5678", NRIC), ("NRIC", " 9001 0114 5678 ", NRIC),
    ("TIN", "sg 10234567890", "SG10234567890"), ("EPF_NO", "12345678", "12345678"),
    ("SOCSO_NO", "a1234567b", "A1234567B"), ("WORK_PASS_NO", "wp-123456", "WP123456"),
])
def test_normalise(identifier_type, raw, expected):
    assert mid.normalise(identifier_type, raw) == expected


@pytest.mark.parametrize("identifier_type, raw", [
    ("NRIC", "900101005678"), ("NRIC", "901301145678"), ("NRIC", "9001011456"), ("TIN", "12345678"),
    ("EPF_NO", "12"), ("PESEL", "44051401359"), ("NRIC", 900101145678),
])
def test_invalid_values_are_refused_without_echo(identifier_type, raw):
    with pytest.raises(mid.MyIdentifierError) as raised:
        mid.normalise(identifier_type, raw)
    assert str(raw) not in str(raised.value)


def test_round_trip_and_owner_binding(keys):
    ciphertext, version = mid.encrypt("900101-14-5678", _owner())
    assert version == 1 and NRIC not in ciphertext
    assert mid.decrypt(ciphertext, version, _owner()) == NRIC
    for other in (_owner(vault_id=11), _owner(employee_id=8), _owner(org=4), _owner(identifier_type=mid.TIN)):
        with pytest.raises(mid.MyIdentifierError) as raised:
            mid.decrypt(ciphertext, version, other)
        assert NRIC not in str(raised.value)
    assert mid.encrypt(NRIC, _owner())[0] != ciphertext                       # random nonce


def test_owner_needs_vault_employee_and_known_type():
    with pytest.raises(mid.MyIdentifierError):
        mid.vault_owner(3, 7, mid.NRIC, None)
    with pytest.raises(mid.MyIdentifierError):
        mid.vault_owner(3, None, mid.NRIC, 10)
    with pytest.raises(mid.MyIdentifierError):
        mid.vault_owner(3, 7, "PESEL", 10)
    assert mid.type_from_owner(_owner(identifier_type=mid.WORK_PASS_NO)) == "WORK_PASS_NO"


def test_rotation_moves_to_the_newest_key(keys):
    ciphertext, version = mid.encrypt(NRIC, _owner())
    keys.MY_IDENTIFIER_KEYRING = json.dumps({"1": "k" * 32, "2": "n" * 32})
    rotated, new_version = mid.reencrypt(ciphertext, version, _owner())
    assert new_version == 2 and mid.decrypt(rotated, 2, _owner()) == NRIC
    assert mid.decrypt(ciphertext, 1, _owner()) == NRIC                       # old key still readable
    with pytest.raises(mid.MyIdentifierError):
        mid.decrypt(ciphertext, 3, _owner())


def test_fingerprint_is_stable_per_type_and_needs_its_key(keys):
    a = mid.fingerprint(mid.NRIC, "900101-14-5678")
    assert a == mid.fingerprint(mid.NRIC, NRIC) and len(a) == 64 and NRIC not in a
    assert mid.fingerprint(mid.EPF_NO, "12345678") != mid.fingerprint(mid.SOCSO_NO, "12345678")
    keys.MY_IDENTIFIER_FINGERPRINT_KEY = ""
    with pytest.raises(mid.MyIdentifierError, match="not configured"):
        mid.fingerprint(mid.NRIC, NRIC)


@pytest.mark.parametrize("ring, message", [("", "not configured"), ("not json", "not valid JSON"),
                                           (json.dumps({"0": "k" * 32}), "start at 1"),
                                           (json.dumps({"1": "short"}), "32-byte")])
def test_bad_keyrings_are_refused(monkeypatch, ring, message):
    from app.config import settings

    monkeypatch.setattr(settings, "MY_IDENTIFIER_KEYRING", ring)
    with pytest.raises(mid.MyIdentifierError, match=message):
        mid.encrypt(NRIC, _owner())


def test_masks_carry_no_character_of_any_value():
    for identifier_type in mid.IDENTIFIER_TYPES:
        mask = mid.masked(identifier_type)
        assert mask and not any(ch.isalnum() for ch in mask)
