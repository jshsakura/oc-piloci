from __future__ import annotations

from piloci.auth.password import hash_password, needs_rehash, verify_password


def test_hash_returns_string():
    result = hash_password("SomePassword1!")
    assert isinstance(result, str)
    assert result.startswith("$argon2")


def test_verify_correct_password():
    plaintext = "CorrectHorseBatteryStaple1"
    hashed = hash_password(plaintext)
    assert verify_password(plaintext, hashed) is True


def test_verify_wrong_password_returns_false():
    hashed = hash_password("CorrectPassword1!")
    assert verify_password("WrongPassword99!", hashed) is False


def test_verify_empty_password_returns_false():
    hashed = hash_password("ValidPassword1!")
    assert verify_password("", hashed) is False


def test_verify_invalid_hash_returns_false():
    assert verify_password("any-password", "not-a-valid-hash") is False


def test_needs_rehash_current_params_returns_false():
    hashed = hash_password("SomePassword1!")
    assert needs_rehash(hashed) is False


def test_needs_rehash_old_hash_returns_true():
    """A hash produced with different parameters should need rehash."""
    from argon2 import PasswordHasher

    old_ph = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1)
    old_hash = old_ph.hash("SomePassword1!")
    assert needs_rehash(old_hash) is True
