"""Application facade for the portable master-password store (#621).

Presentation talks only to this facade; the crypto lives in
``infrastructure/master_password.py``. All failures surface as stable,
non-sensitive error codes — never the password, key, path or token.
"""

from __future__ import annotations

from echo_personal_tool.infrastructure.master_password import (
    MasterPasswordError,
)
from echo_personal_tool.infrastructure.master_password import (
    change_master_password as _change,
)
from echo_personal_tool.infrastructure.master_password import (
    lock_master_password as _lock,
)
from echo_personal_tool.infrastructure.master_password import (
    master_password_enabled as _enabled,
)
from echo_personal_tool.infrastructure.master_password import (
    set_master_password as _set,
)
from echo_personal_tool.infrastructure.master_password import (
    unlock_master_password as _unlock,
)


def master_password_enabled() -> bool:
    """Whether the portable root is protected by a master password."""
    return _enabled()


def set_master_password(password: str) -> str | None:
    """Enable master-password mode (migrates an existing device.key).

    Returns a stable error code, or None on success.
    """
    try:
        _set(password)
    except MasterPasswordError as exc:
        return exc.code
    return None


def change_master_password(old_password: str, new_password: str) -> str | None:
    """Change the master password (re-wraps the device secret).

    Returns "wrong_password" when the old password does not verify,
    another stable error code on failure, or None on success.
    """
    try:
        if not _change(old_password, new_password):
            return "wrong_password"
    except MasterPasswordError as exc:
        return exc.code
    return None


def unlock_master_password(password: str) -> str | None:
    """Unlock the session with the master password.

    Returns None on success, "wrong_password" on a bad password, or another
    stable error code when the store itself is unusable.
    """
    try:
        if not _unlock(password):
            return "wrong_password"
    except MasterPasswordError as exc:
        return exc.code
    return None


def lock_master_password() -> None:
    """Drop the in-memory device secret (session lock)."""
    _lock()
