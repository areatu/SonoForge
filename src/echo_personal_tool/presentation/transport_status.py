"""Transport status line shared by the server dialogs.

The server-profile list, the settings form and the Orthanc loader all show the
same one-line verdict on a profile's transport security. It lives in its own
module so that none of the dialogs has to import another one for it (issue 328).
"""

from __future__ import annotations

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.server_io import (
    ServerSettings,
    describe_insecure_transport_modes,
    evaluate_server_settings,
)


def format_transport_status_text(settings: ServerSettings) -> tuple[str, bool]:
    """Return ``(status_text, is_insecure_or_blocked)`` for ``settings``."""
    if not isinstance(settings, ServerSettings) or settings.use_mock:
        return ("", False)
    modes = describe_insecure_transport_modes(settings)
    profile = evaluate_server_settings(settings)
    if settings.needs_confirmation or profile.blocked:
        modes_str = ", ".join(modes) if modes else "; ".join(f.message for d in profile.blocked for f in d.findings)
        return (tr("server_settings.insecure_status_unconfirmed", modes=modes_str), True)
    if profile.insecure or modes:
        return (tr("server_settings.insecure_status_active", modes=", ".join(modes)), True)
    return (tr("server_settings.insecure_status_secure"), False)
