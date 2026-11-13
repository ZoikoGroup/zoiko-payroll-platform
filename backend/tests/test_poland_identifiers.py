"""Poland identifier vault crypto (ZP-PL-ENG-001 Phase 2, spec §13, PL-025)."""
import json

import pytest

from app.modules.payroll import pl_identifiers as pid

PESEL = "44051401359"
NIP = "5261040828"
# ISO 13616 / bank-published example account (not a real account).
NRS_IBAN = "PL61109010140000071219812874"  # privacy-scan: allow
NRS_DIGITS = NRS_IBAN[2:]
DE_IBAN = "DE89370400440532013000"  # privacy-scan: allow
KEY_1 = "a" * 32
KEY_2 = "b" * 64            # hex form
FP_KEY = "c" * 32


@pytest.fixture
def keys(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "PL_IDENTIFIER_KEYRING", json.dumps({"1": KEY_1}))
    monkeypatch.setattr(settings, "PL_IDENTIFIER_FINGERPRINT_KEY", FP_KEY)
    return settings


def _owner(identifier_type=pid.PESEL, subject=pid.SUBJECT_EMPLOYEE, subject_id=11, vault_id=1, org=7):
    return pid.vault_owner(org, subject, subject_id, identifier_type, vault_id)


def test_dormant_without_keys_refuses_everything():
    with pytest.raises(pid.PlIdentifierError, match="KEYRING is not configured"):
        pid.encrypt(PESEL, _owner())
    with pytest.raises(pid.PlIdentifierError, match="FINGERPRINT_KEY is not configured"):
        pid.fingerprint(pid.PESEL, PESEL)


@pytest.mark.parametrize("identifier_type, raw, canonical", [
    (pid.PESEL, "440514 01359", PESEL), (pid.NIP, "526-104-08-28", NIP),
    (pid.NRS, NRS_IBAN, NRS_DIGITS), (pid.NRS, NRS_DIGITS, NRS_DIGITS),
    (pid.NRS, " ".join(NRS_IBAN[i:i + 4] for i in range(0, 28, 4)).lower(), NRS_DIGITS),
])
def test_normalise(identifier_type, raw, canonical):
    assert pid.normalise(identifier_type, raw) == canonical


@pytest.mark.parametrize("identifier_type, raw", [
    (pid.PESEL, "44051401358"), (pid.NIP, "5261040827"), (pid.NRS, NRS_DIGITS[:-1] + "5"),
    (pid.NRS, DE_IBAN), ("REGON", "123456785"), (pid.PESEL, 44051401359),
])
def test_normalise_rejects_without_echoing(identifier_type, raw):
    with pytest.raises(pid.PlIdentifierError) as raised:
        pid.normalise(identifier_type, raw)
    assert str(raw) not in str(raised.value)


@pytest.mark.parametrize("identifier_type, value, subject, subject_id", [
    (pid.PESEL, PESEL, pid.SUBJECT_EMPLOYEE, 11), (pid.NIP, NIP, pid.SUBJECT_EMPLOYEE, 11),
    (pid.NRS, NRS_IBAN, pid.SUBJECT_EMPLOYER, None),
])
def test_round_trip_and_no_plaintext_in_ciphertext(keys, identifier_type, value, subject, subject_id):
    owner = _owner(identifier_type, subject, subject_id)
    ciphertext, version = pid.encrypt(value, owner)
    assert version == 1
    assert pid.normalise(identifier_type, value) not in ciphertext
    assert pid.decrypt(ciphertext, version, owner) == pid.normalise(identifier_type, value)


def test_ciphertext_is_bound_to_its_owner(keys):
    ciphertext, version = pid.encrypt(PESEL, _owner())
    for other in (_owner(vault_id=2), _owner(subject_id=12), _owner(org=8), _owner(identifier_type=pid.NIP)):
        with pytest.raises(pid.PlIdentifierError, match="could not be decrypted"):
            pid.decrypt(ciphertext, version, other)


def test_owner_binding_rules():
    with pytest.raises(pid.PlIdentifierError):
        pid.vault_owner(7, pid.SUBJECT_EMPLOYEE, 11, pid.PESEL, None)          # no vault id
    with pytest.raises(pid.PlIdentifierError):
        pid.vault_owner(7, pid.SUBJECT_EMPLOYEE, None, pid.PESEL, 1)          # employee needed
    with pytest.raises(pid.PlIdentifierError):
        pid.vault_owner(7, pid.SUBJECT_EMPLOYER, None, pid.PESEL, 1)          # employer has no PESEL
    with pytest.raises(pid.PlIdentifierError):
        pid.vault_owner(7, pid.SUBJECT_EMPLOYEE, 11, pid.NRS, 1)              # NRS is employer-only


def test_encrypt_refuses_an_invalid_value_for_the_owner_type(keys):
    with pytest.raises(pid.PlIdentifierError, match="PESEL is not valid"):
        pid.encrypt(NIP, _owner(pid.PESEL))


def test_rotation_keeps_old_rows_readable(keys, monkeypatch):
    owner = _owner()
    old, v1 = pid.encrypt(PESEL, owner)
    monkeypatch.setattr(keys, "PL_IDENTIFIER_KEYRING", json.dumps({"1": KEY_1, "2": KEY_2}))
    assert pid.decrypt(old, v1, owner) == PESEL
    new, v2 = pid.reencrypt(old, v1, owner)
    assert v2 == 2 and pid.decrypt(new, v2, owner) == PESEL


def test_tampering_and_unknown_version_fail_generically(keys):
    owner = _owner()
    ciphertext, version = pid.encrypt(PESEL, owner)
    with pytest.raises(pid.PlIdentifierError, match="not in the keyring"):
        pid.decrypt(ciphertext, 9, owner)
    with pytest.raises(pid.PlIdentifierError, match="could not be decrypted"):
        pid.decrypt(ciphertext[:-4] + "AAAA", version, owner)


@pytest.mark.parametrize("bad", ["not json", "[]", "{}", '{"0": "' + "a" * 32 + '"}', '{"1": "short"}'])
def test_bad_keyrings_are_refused(monkeypatch, bad):
    from app.config import settings

    monkeypatch.setattr(settings, "PL_IDENTIFIER_KEYRING", bad)
    with pytest.raises(pid.PlIdentifierError) as raised:
        pid.encrypt(PESEL, _owner())
    assert "a" * 32 not in str(raised.value)


def test_fingerprint_is_stable_typed_and_keyed(keys, monkeypatch):
    first = pid.fingerprint(pid.PESEL, PESEL)
    assert first == pid.fingerprint(pid.PESEL, "440514-01359")                 # normalised
    assert len(first) == 64 and PESEL not in first
    monkeypatch.setattr(keys, "PL_IDENTIFIER_KEYRING", json.dumps({"1": KEY_1, "2": KEY_2}))
    assert pid.fingerprint(pid.PESEL, PESEL) == first                          # rotation-proof
    monkeypatch.setattr(keys, "PL_IDENTIFIER_FINGERPRINT_KEY", "d" * 32)
    assert pid.fingerprint(pid.PESEL, PESEL) != first                          # keyed


def test_masked_never_contains_a_digit():
    for identifier_type in pid.IDENTIFIER_TYPES:
        assert not any(ch.isdigit() for ch in pid.masked(identifier_type))
