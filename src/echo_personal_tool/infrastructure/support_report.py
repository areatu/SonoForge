"""Prefilled "report a problem" links (Q-13).

The button in Settings opens the project's GitHub bug form with the fields a
supporter can fill in reliably by hand already filled in: the operating system
dropdown, the application version and a non-PHI environment block.

Privacy rules, matching ``infrastructure/diagnostics.py``:

* only the allowlisted runtime summary (``logging_setup.system_info_text``) is
  put into the link — never preferences, server settings, study paths, patient
  data or measurement values;
* log *text* is never put into the URL.  Logs travel as a local sanitized ZIP
  that the user attaches to the issue themselves, so nothing leaves the
  machine without an explicit action;
* the link is capped well below browser URL limits and long fields are trimmed
  (least useful first) rather than silently producing a broken URL.
"""

from __future__ import annotations

import os
import platform
from datetime import datetime
from pathlib import Path
from urllib.parse import quote, urlencode

from echo_personal_tool import __version__

#: ``issues/new`` accepts issue-form prefill parameters: ``template``,
#: ``title``, ``labels`` plus one parameter per form field ``id``.
ISSUE_BASE_URL = "https://github.com/areatu/SonoForge/issues/new"
BUG_TEMPLATE = "bug_report.yml"
DEFAULT_ISSUE_TITLE = "[Bug]: "
DEFAULT_LABELS = ("bug",)

#: Values of the "Operating system" dropdown in ``.github/ISSUE_TEMPLATE/bug_report.yml``.
#: A prefill that does not match an option verbatim is dropped by GitHub, so the
#: mapping has to stay in sync with the template.
OS_OPTIONS = (
    "Windows 10",
    "Windows 11",
    "macOS (Intel)",
    "macOS (Apple Silicon)",
    "Linux (Ubuntu/Debian)",
    "Linux (other)",
)

#: Windows 11 reports itself as ``10`` to Python; the build number tells them apart.
_WINDOWS_11_BUILD = 22000

#: Per-field and per-URL caps. Browsers and GitHub reject very long query
#: strings, and a report that cannot be opened is worse than a trimmed one.
MAX_FIELD_CHARS = 1600
MAX_URL_CHARS = 7000
TRIM_MARK = " …[trimmed]"

#: Trim order: the least useful field for a first triage goes first.
_TRIM_ORDER = ("logs", "additional", "steps", "expected", "description")

#: The description is the reporter's own sentence: never trim it away entirely.
_MIN_KEPT_CHARS = 120


def windows_build() -> int | None:
    """Return the Windows build number, or ``None`` off Windows."""
    getter = getattr(os, "getwindowsversion", None)
    if getter is None:
        return None
    try:
        return int(getter().build)
    except Exception:  # noqa: BLE001 - never fail a report because of a probe
        return None


def linux_distribution_id() -> str:
    """Return the lowercased ``ID``/``ID_LIKE`` of the running Linux distro."""
    try:
        text = Path("/etc/os-release").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    values: list[str] = []
    for line in text.splitlines():
        key, _, value = line.partition("=")
        if key.strip() in {"ID", "ID_LIKE"}:
            values.extend(part.strip().strip('"').lower() for part in value.split())
    return " ".join(values)


def detect_os_option(
    *,
    system: str | None = None,
    machine: str | None = None,
    build: int | None = None,
    distro_id: str | None = None,
) -> str:
    """Map the running platform onto a bug-form dropdown option.

    Returns ``""`` when the platform cannot be classified: an unknown value
    would be dropped by GitHub anyway, and an empty dropdown lets the user pick
    the right entry instead of shipping a wrong one.
    """
    system = (system if system is not None else platform.system()).lower()
    machine = (machine if machine is not None else platform.machine()).lower()

    if system.startswith("win") or system == "windows":
        resolved_build = build if build is not None else windows_build()
        if resolved_build is None:
            # Not running on Windows (a test or an exotic platform): do not guess.
            return ""
        return "Windows 11" if resolved_build >= _WINDOWS_11_BUILD else "Windows 10"

    if system == "darwin":
        return "macOS (Apple Silicon)" if machine in {"arm64", "aarch64"} else "macOS (Intel)"

    if system == "linux":
        distro = (distro_id if distro_id is not None else linux_distribution_id()).lower()
        if any(name in distro for name in ("ubuntu", "debian", "mint", "pop", "elementary", "kali", "raspbian")):
            return "Linux (Ubuntu/Debian)"
        return "Linux (other)"

    return ""


def environment_text(app: object | None = None, *, bundle_name: str = "") -> str:
    """Return the allowlisted environment block for the issue body.

    ``bundle_name`` is only a file name (no directory): it tells the maintainer
    which archive to expect as an attachment.
    """
    from echo_personal_tool.infrastructure.logging_setup import system_info_text

    lines = [system_info_text(app)]  # type: ignore[arg-type]
    if bundle_name:
        lines.append(f"Diagnostic bundle: {Path(bundle_name).name} (attached to this issue)")
    else:
        lines.append("Diagnostic bundle: not created")
    return "\n".join(lines)


def build_issue_url(
    *,
    title: str = DEFAULT_ISSUE_TITLE,
    description: str = "",
    steps: str = "",
    expected: str = "",
    os_option: str | None = None,
    version: str | None = None,
    logs: str = "",
    additional: str = "",
    labels: tuple[str, ...] = DEFAULT_LABELS,
    template: str = BUG_TEMPLATE,
    base_url: str = ISSUE_BASE_URL,
) -> str:
    """Build a prefilled GitHub issue-form URL.

    Empty fields are omitted so GitHub shows its own placeholders, and the
    result is trimmed to :data:`MAX_URL_CHARS`.
    """
    resolved_os = detect_os_option() if os_option is None else os_option
    resolved_version = __version__ if version is None else version

    fields: dict[str, str] = {
        "description": description,
        "steps": steps,
        "expected": expected,
        "os": resolved_os,
        "version": resolved_version,
        "logs": logs,
        "additional": additional,
    }

    params: dict[str, str] = {"template": template, "title": title}
    if labels:
        params["labels"] = ",".join(labels)
    for key, value in fields.items():
        cleaned = str(value or "").strip()
        if cleaned:
            params[key] = cleaned[:MAX_FIELD_CHARS]

    url = base_url + "?" + urlencode(params, quote_via=quote)
    return _trim_to_limit(url, params, base_url)


def _trim_to_limit(url: str, params: dict[str, str], base_url: str) -> str:
    """Shorten the most disposable fields until the URL fits.

    A field that cannot shrink any further is dropped; the description keeps a
    floor, because a report without the user's own sentence is useless.
    """
    working = dict(params)
    for key in _TRIM_ORDER:
        if len(url) <= MAX_URL_CHARS:
            break
        value = working.get(key, "")
        floor = _MIN_KEPT_CHARS if key == "description" else 0
        while len(value) > floor and len(url) > MAX_URL_CHARS:
            # Percent-encoding expands text (up to ~9x for Cyrillic), so cut in
            # character steps and re-measure instead of guessing a byte budget.
            cut = max(32, (len(url) - MAX_URL_CHARS) // 3)
            value = value[: max(floor, len(value) - cut)]
            if value:
                working[key] = value + TRIM_MARK
            else:
                working.pop(key, None)
            url = base_url + "?" + urlencode(working, quote_via=quote)
    return url


def default_bundle_path(*, now: datetime | None = None, base_dir: Path | None = None) -> Path:
    """Suggest where to write the diagnostic ZIP.

    Downloads, then Desktop, then the home directory: the first one that exists
    wins, because the user has to find the file again to attach it.
    """
    stamp = (now or datetime.now().astimezone()).strftime("%Y%m%d-%H%M%S")
    name = f"SonoForge-diagnostics-{stamp}.zip"
    if base_dir is not None:
        return Path(base_dir) / name

    try:
        from PySide6.QtCore import QStandardPaths

        for location in (
            QStandardPaths.StandardLocation.DownloadLocation,
            QStandardPaths.StandardLocation.DesktopLocation,
            QStandardPaths.StandardLocation.HomeLocation,
        ):
            candidate = QStandardPaths.writableLocation(location)
            if candidate and Path(candidate).is_dir():
                return Path(candidate) / name
    except ImportError:
        pass
    return Path.home() / name
