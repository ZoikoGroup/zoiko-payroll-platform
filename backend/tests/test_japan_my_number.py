"""Japan My Number helper (ZP-JP-ENG-001 Phase 2).

Pure tests: no database, no routes. The number is only ever plaintext inside
``validate`` / ``encrypt`` / ``decrypt`` / ``fingerprint`` and never appears in
an exception, a repr or a log line.
"""
import json
import logging

import pytest

from app.config import settings
from app.modules.payroll import japan_my_number as mn

WEIGHTS = (6, 5, 4, 3, 2, 7, 6, 5, 4, 3, 2)
KEY1 = "a" * 32
KEY2 = "b" * 32
FINGERPRINT_KEY = "f" * 32


def _number(body="12345678901"):
    total = sum(int(digit) * weight for digit, weight in zip(body, WEIGHTS))
    check = 11 - (total % 11)
    return body + str(0 if check >= 10 else check)


def _keyring(monkeypatch, versions, fingerprint_key=FINGERPRINT_KEY):
    monkeypatch.setattr(settings, "JP_MY_NUMBER_KEYRING",
                        json.dumps({str(v): key for v, key in versions.items()}))
    monkeypatch.setattr(settings, "JP_MY_NUMBER_FINGERPRINT_KEY", fingerprint_key)


def test_check_digit_accepted_and_rejected(monkeypatch):
    _keyring(monkeypatch, {1: KEY1})
    valid = _number()
    assert mn.validate(valid) == valid
    wrong = valid[:-1] + str((int(valid[-1]) + 1) % 10)
    with pytest.raises(mn.MyNumberError):
        mn.validate(wrong)
    for bad in ("12345678901", "1234567890123", "12345678901a", ""):
        with pytest.raises(mn.MyNumberError):
            mn.validate(bad)


def test_round_trip_for_each_key_version(monkeypatch):
    number = _number()
    for version, key in ((1, KEY1), (2, KEY2)):
        _keyring(monkeypatch, {version: key})
        ciphertext, used = mn.encrypt(number)
        assert used == version
        _keyring(monkeypatch, {1: KEY1, 2: KEY2})
        assert mn.decrypt(ciphertext, used) == number


def test_old_key_rows_still_decrypt_after_rotation(monkeypatch):
    number = _number()
    _keyring(monkeypatch, {1: KEY1})
    old_ciphertext, old_version = mn.encrypt(number)
    _keyring(monkeypatch, {1: KEY1, 2: KEY2})
    assert old_version == 1
    assert mn.decrypt(old_ciphertext, old_version) == number
    new_ciphertext, new_version = mn.encrypt(number)
    assert new_version == 2
    assert mn.decrypt(new_ciphertext, 2) == number


def test_fingerprint_is_stable_and_discriminating(monkeypatch):
    _keyring(monkeypatch, {1: KEY1})
    number = _number()
    first = mn.fingerprint(number)
    assert first == mn.fingerprint(number)
    assert len(first) == 64
    assert first != mn.fingerprint(_number("10987654321"))


def test_empty_keyring_refuses(monkeypatch):
    _keyring(monkeypatch, {}, fingerprint_key="")
    with pytest.raises(mn.MyNumberError):
        mn.encrypt(_number())
    with pytest.raises(mn.MyNumberError):
        mn.fingerprint(_number())
    with pytest.raises(mn.MyNumberError):
        mn.decrypt("anything", 1)


def test_ciphertext_cannot_be_decrypted_with_the_wrong_version(monkeypatch):
    number = _number()
    _keyring(monkeypatch, {1: KEY1, 2: KEY2})
    ciphertext, version = mn.encrypt(number)
    with pytest.raises(mn.MyNumberError):
        mn.decrypt(ciphertext, 3 if version != 3 else 1)


def test_no_number_in_exceptions_repr_or_logs(monkeypatch, caplog):
    _keyring(monkeypatch, {1: KEY1})
    number = _number()
    wrong = number[:-1] + str((int(number[-1]) + 1) % 10)
    with caplog.at_level(logging.DEBUG):
        with pytest.raises(mn.MyNumberError) as excinfo:
            mn.validate(wrong)
        assert number not in str(excinfo.value)
        ciphertext, version = mn.encrypt(number)
        assert number not in repr((ciphertext, version))
        assert number not in ciphertext
        assert mn.decrypt(ciphertext, version) == number
        assert number not in caplog.text
    assert "123456789018" not in caplog.text


def test_masked_is_the_only_ui_form():
    assert mn.masked() == "\u2022\u2022\u2022\u2022 \u2022\u2022\u2022\u2022 \u2022\u2022\u2022\u2022"


def test_tampered_ciphertext_raises_my_number_error(monkeypatch):
    import base64

    _keyring(monkeypatch, {1: KEY1})
    ciphertext, version = mn.encrypt(_number())
    raw = bytearray(base64.urlsafe_b64decode(ciphertext))
    raw[-1] ^= 1
    with pytest.raises(mn.MyNumberError):
        mn.decrypt(base64.urlsafe_b64encode(bytes(raw)).decode(), version)


def test_wrong_key_under_an_existing_version_raises_my_number_error(monkeypatch):
    _keyring(monkeypatch, {1: KEY1})
    ciphertext, version = mn.encrypt(_number())
    _keyring(monkeypatch, {1: KEY2})   # same version number, different key
    with pytest.raises(mn.MyNumberError):
        mn.decrypt(ciphertext, version)


def test_fingerprint_survives_keyring_rotation(monkeypatch):
    number = _number()
    _keyring(monkeypatch, {1: KEY1})
    before = mn.fingerprint(number)
    _keyring(monkeypatch, {1: KEY1, 2: KEY2})
    assert mn.fingerprint(number) == before


def test_fingerprint_needs_its_own_key(monkeypatch):
    _keyring(monkeypatch, {1: KEY1}, fingerprint_key="")
    with pytest.raises(mn.MyNumberError):
        mn.fingerprint(_number())
    assert mn.decrypt(*mn.encrypt(_number())) == _number()   # encryption itself unaffected
