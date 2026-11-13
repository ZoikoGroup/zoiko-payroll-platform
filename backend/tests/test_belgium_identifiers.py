"""Belgium (ZP-BE-ENG-001) Block A1: the identifier boundary (be_identifiers).

NISS / BIS / ONSS numbers are encrypted at rest with an owner binding, masked
everywhere, fingerprinted for duplicates on their own key, and refused when no
key is configured (no fallback). Every identifier value below is SYNTHETIC
TEST ONLY data with the right digit count — never a real person's number."""
import json

import pytest

KEYRING = json.dumps({"1": "k" * 32})
KEYRING_ROTATED = json.dumps({"1": "k" * 32, "2": "r" * 32})
FINGERPRINT_KEY = "f" * 32
NISS = "00.00.00-000.00"  # privacy-scan: allow (synthetic, digits only, TEST ONLY)
ONSS = "0000000-00"  # privacy-scan: allow (synthetic, TEST ONLY)


@pytest.fixture
def keys(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", KEYRING)
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", FINGERPRINT_KEY)
    from app.modules.payroll import be_identifiers

    return be_identifiers


def _owner(bid, identifier_type="NISS", subject=7, vault=11, org=1):
    subject_type = bid.SUBJECT_EMPLOYER if identifier_type == "ONSS" else bid.SUBJECT_EMPLOYEE
    return bid.vault_owner(org, subject_type, subject, identifier_type, vault)


@pytest.mark.parametrize("identifier_type, raw, expected", [("NISS", NISS, "00000000000"),
                                                            ("BIS", "00 00 00 000 00", "00000000000"),
                                                            ("ONSS", ONSS, "000000000")])
def test_normalise_strips_separators_and_checks_the_format_only(keys, identifier_type, raw, expected):
    assert keys.normalise(identifier_type, raw) == expected


@pytest.mark.parametrize("identifier_type, raw", [("NISS", "0000000000"), ("NISS", "000000000000"),
                                                  ("NISS", "0000000000A"), ("BIS", ""), ("ONSS", "0000"),
                                                  ("ONSS", "AB00000"), ("PESEL", "00000000000")])
def test_normalise_rejects_malformed_values_without_echoing_them(keys, identifier_type, raw):
    with pytest.raises(keys.BeIdentifierError) as raised:
        keys.normalise(identifier_type, raw)
    if raw:
        assert raw not in str(raised.value)


def test_no_check_digit_is_applied_yet(keys):
    """G-16: the NISS check-digit rule is unverified, so any 11 digits pass the
    FORMAT check (the resolver/specialist decides later)."""
    assert keys.normalise("NISS", "12345678901") == "12345678901"


def test_encrypt_decrypt_round_trip_bound_to_its_owner(keys):
    owner = _owner(keys)
    ciphertext, version = keys.encrypt(NISS, owner)
    assert version == 1 and "00000000000" not in ciphertext
    assert keys.decrypt(ciphertext, version, owner) == "00000000000"
    for other in (_owner(keys, subject=8), _owner(keys, vault=12), _owner(keys, org=2),
                  _owner(keys, identifier_type="BIS")):
        with pytest.raises(keys.BeIdentifierError):
            keys.decrypt(ciphertext, version, other)


def test_rotation_reencrypts_under_the_newest_key(keys, monkeypatch):
    from app.config import settings

    owner = _owner(keys)
    ciphertext, _ = keys.encrypt(NISS, owner)
    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", KEYRING_ROTATED)
    rotated, version = keys.reencrypt(ciphertext, 1, owner)
    assert version == 2 and keys.decrypt(rotated, 2, owner) == "00000000000"


def test_every_operation_refuses_without_keys(monkeypatch):
    from app.config import settings
    from app.modules.payroll import be_identifiers as bid

    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", "")
    monkeypatch.setattr(settings, "BE_IDENTIFIER_FINGERPRINT_KEY", "")
    owner = bid.vault_owner(1, bid.SUBJECT_EMPLOYEE, 7, "NISS", 11)
    with pytest.raises(bid.BeIdentifierError, match="BE_IDENTIFIER_KEYRING is not configured"):
        bid.encrypt(NISS, owner)
    with pytest.raises(bid.BeIdentifierError, match="BE_IDENTIFIER_FINGERPRINT_KEY is not configured"):
        bid.fingerprint("NISS", NISS)


def test_no_fallback_to_another_key(monkeypatch):
    """With the Belgian keyring empty, the Poland keyring or the platform secret
    is never used."""
    from app.config import settings
    from app.modules.payroll import be_identifiers as bid

    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", "")
    monkeypatch.setattr(settings, "PL_IDENTIFIER_KEYRING", KEYRING)
    with pytest.raises(bid.BeIdentifierError):
        bid.encrypt(NISS, bid.vault_owner(1, bid.SUBJECT_EMPLOYEE, 7, "NISS", 11))


@pytest.mark.parametrize("bad", ['not json', '{}', '{"0": "' + "k" * 32 + '"}', '{"1": "short"}'])
def test_a_bad_keyring_refuses(monkeypatch, bad):
    from app.config import settings
    from app.modules.payroll import be_identifiers as bid

    monkeypatch.setattr(settings, "BE_IDENTIFIER_KEYRING", bad)
    with pytest.raises(bid.BeIdentifierError):
        bid.encrypt(NISS, bid.vault_owner(1, bid.SUBJECT_EMPLOYEE, 7, "NISS", 11))


def test_fingerprints_are_stable_typed_and_carry_no_digits(keys):
    one = keys.fingerprint("NISS", NISS)
    assert one == keys.fingerprint("NISS", "00000000000") and len(one) == 64
    assert one != keys.fingerprint("BIS", NISS)
    assert "00000000000" not in one


def test_owner_binding_rules(keys):
    with pytest.raises(keys.BeIdentifierError):
        keys.vault_owner(1, keys.SUBJECT_EMPLOYEE, None, "NISS", 1)       # an employee identifier needs its employee
    with pytest.raises(keys.BeIdentifierError):
        keys.vault_owner(1, keys.SUBJECT_EMPLOYER, None, "NISS", 1)       # NISS is never an employer identifier
    with pytest.raises(keys.BeIdentifierError):
        keys.vault_owner(1, keys.SUBJECT_EMPLOYEE, 7, "ONSS", 1)          # ONSS is employer-only
    with pytest.raises(keys.BeIdentifierError):
        keys.vault_owner(1, keys.SUBJECT_EMPLOYEE, 7, "NISS", None)       # bound to a vault row


def test_masks_carry_no_digit(keys):
    for identifier_type in keys.IDENTIFIER_TYPES:
        assert not any(ch.isdigit() for ch in keys.masked(identifier_type))
