"""User-visible feedback when a credential write had to fail closed.

Portable secret storage never degrades to plaintext or to the host keychain
(see ``infrastructure/server_settings.py``). The save still reports the
failure, so the dialogs can tell the user to re-enter the password instead of
silently losing it. Presentation asks the application facade for the status
type; it does not import infrastructure.
"""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.server_io import PasswordSaveStatus


def warn_if_password_not_saved(parent: QWidget | None, status: object) -> bool:
    """Show a localized warning when ``status`` is a failed credential write.

    ``status`` is deliberately ``object``: callers also receive test doubles
    and mocked facades, which must not be treated as a real failure.
    """
    if not isinstance(status, PasswordSaveStatus) or status.saved:
        return False
    QMessageBox.warning(
        parent,
        tr("server_settings.password_not_saved_title"),
        tr("server_settings.password_not_saved", code=status.error_code or "unavailable"),
    )
    return True
