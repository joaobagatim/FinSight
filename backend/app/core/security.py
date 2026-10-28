"""Argon2id password hashing; credentials must never be logged."""

from pwdlib import PasswordHash
from pwdlib.exceptions import UnknownHashError
from pwdlib.hashers.argon2 import Argon2Hasher

_password_hash = PasswordHash((Argon2Hasher(memory_cost=19456, time_cost=2, parallelism=1),))


def hash_password(password: str) -> str:
    return _password_hash.hash(password)


def verify_password(password: str, encoded: str) -> bool:
    try:
        return _password_hash.verify(password, encoded)
    except (UnknownHashError, ValueError):
        return False
