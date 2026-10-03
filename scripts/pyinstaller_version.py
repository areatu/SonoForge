"""Generate Windows PE version resources for the SonoForge PyInstaller builds.

Why this module exists
----------------------
``EXE(...)`` in the PyInstaller specs used to carry no ``version=`` argument, so
every Windows executable shipped without a version resource: Explorer's
Properties → Details tab was empty, and there was no ``ProductName`` or
``ProductVersion`` for antivirus heuristics, allow-listing tools, or a code
signing provider to read.

That last point is a hard blocker for the SignPath Foundation free OSS signing
programme, whose conditions require that *"all signed binaries must have
metadata attributes set and enforced"* — product name equal to the project name
and product version identical in every build.

The single source of truth for the version is ``__version__`` in
``src/echo_personal_tool/__init__.py``. Nothing here is hardcoded, because the
previous hardcoded value (``CFBundleShortVersionString: '0.2.4'`` in
``sonoforge-standalone.spec``) drifted behind `__version__` and shipped that
way.

Why a generated *file* and not a ``VSVersionInfo`` object
---------------------------------------------------------
``EXE(version=...)`` accepts either a path or a
``PyInstaller.utils.win32.versioninfo.VSVersionInfo`` instance. The instance
form requires importing that module, whose top level does
``from PyInstaller.compat import win32api`` and ``import pefile`` — both
installed on Windows only. Importing it from a spec would therefore break the
macOS and Linux builds.

This module lives in ``scripts/`` rather than ``build/`` because ``build/`` is
gitignored (it is PyInstaller's workpath); a source file placed there is
silently skipped by ``git add -A`` and the specs then fail on a fresh checkout.

A path is safe everywhere: ``EXE.__init__`` explicitly handles the
non-Windows case with

    if self.versrsrc and not is_win:
        logger.warning('Ignoring version information; supported only on Windows!')
        self.versrsrc = None

so the same spec runs unchanged on all three platforms. The file is written to a
temporary directory and passed as an absolute path, keeping generated content
out of the repository tree.
"""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

__all__ = ["PROJECT_ROOT", "read_version", "write_version_file", "bundle_version_plist"]

PROJECT_ROOT = Path(__file__).resolve().parent.parent
_VERSION_SOURCE = PROJECT_ROOT / "src" / "echo_personal_tool" / "__init__.py"

_COMPANY = "SonoForge contributors"
_COPYRIGHT = "Copyright (C) SonoForge contributors. Licensed under GPL-3.0-only."

# VS_VERSIONINFO block for US English (0x0409) with the Unicode code page
# (0x04B0 = 1200). Must agree with the VarStruct('Translation', ...) below or
# Windows resolves no strings at all and the Details tab looks empty again.
_LANG_CODEPAGE = "040904B0"
_TRANSLATION = (1033, 1200)


def read_version() -> str:
    """Return ``__version__`` parsed from the package, without importing it.

    Importing ``echo_personal_tool`` would pull in PySide6 and the whole runtime
    dependency set, which a spec file must not require.
    """
    if not _VERSION_SOURCE.is_file():
        raise RuntimeError(
            f"Could not find the version source {_VERSION_SOURCE}. The Windows "
            "version resource and the macOS bundle version are both derived from "
            "it; a spec must not silently build with no version metadata."
        )
    text = _VERSION_SOURCE.read_text(encoding="utf-8")
    match = re.search(r"^__version__\s*=\s*[\"']([^\"']+)[\"']", text, re.MULTILINE)
    if not match:
        raise RuntimeError(
            f"Could not find __version__ in {_VERSION_SOURCE}. "
            "The Windows version resource and the macOS bundle version are both "
            "derived from it."
        )
    return match.group(1)


def _version_quad(version: str) -> tuple[int, int, int, int]:
    """Expand ``0.3.1`` to the four numeric fields VS_FIXEDFILEINFO needs.

    Non-numeric or missing components become ``0`` rather than raising: a
    pre-release suffix such as ``0.4.0rc1`` must still build. ``filevers`` and
    ``prodvers`` are DWORD pairs, so every field is masked to 16 bits by
    ``FixedFileInfo`` — values outside that range would silently wrap.
    """
    fields: list[int] = []
    for part in version.split(".")[:3]:
        digits = re.match(r"\d+", part)
        fields.append(int(digits.group(0)) if digits else 0)
    while len(fields) < 3:
        fields.append(0)
    if any(not 0 <= f <= 0xFFFF for f in fields):
        raise RuntimeError(f"Version {version!r} has a component outside 0..65535")
    return (fields[0], fields[1], fields[2], 0)


def write_version_file(
    original_filename: str,
    file_description: str,
    product_name: str = "SonoForge",
    internal_name: str | None = None,
) -> str:
    """Write a PyInstaller version-resource file and return its absolute path.

    The emitted text is exactly the serialization produced by
    ``VSVersionInfo.__str__``, which is what
    ``versioninfo.load_version_info_from_text_file`` expects to ``eval()`` in
    the versioninfo module namespace. The constructor names therefore must not
    be qualified with a module prefix.
    """
    version = read_version()
    quad = _version_quad(version)
    quad_text = ", ".join(str(q) for q in quad)
    dotted = f"{quad[0]}.{quad[1]}.{quad[2]}.{quad[3]}"
    internal = internal_name or Path(original_filename).stem

    def s(name: str, value: str) -> str:
        escaped = value.replace("\\", "\\\\").replace("'", "\\'")
        return f"          StringStruct('{name}', '{escaped}')"

    strings = ",\n".join(
        [
            s("CompanyName", _COMPANY),
            s("FileDescription", file_description),
            s("FileVersion", dotted),
            s("InternalName", internal),
            s("LegalCopyright", _COPYRIGHT),
            s("OriginalFilename", original_filename),
            s("ProductName", product_name),
            s("ProductVersion", dotted),
        ]
    )

    content = f"""# UTF-8
#
# Generated by build/pyinstaller_version.py from __version__ in
# src/echo_personal_tool/__init__.py. Do not edit and do not commit.
#
# For more details about fixed file info 'ffi' see:
# http://msdn.microsoft.com/en-us/library/ms646997.aspx
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({quad_text}),
    prodvers=({quad_text}),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo(
      [
        StringTable(
          '{_LANG_CODEPAGE}',
          [
{strings}
          ]
        )
      ]
    ),
    VarFileInfo([VarStruct('Translation', [{_TRANSLATION[0]}, {_TRANSLATION[1]}])])
  ]
)
"""
    out_dir = Path(tempfile.mkdtemp(prefix="sonoforge-versioninfo-"))
    out_path = out_dir / f"{internal}.version.txt"
    out_path.write_text(content, encoding="utf-8")
    return str(out_path)


def bundle_version_plist() -> dict:
    """Info.plist version keys for the macOS ``.app`` bundle.

    ``CFBundleShortVersionString`` is the user-visible release version and
    ``CFBundleVersion`` the build version; both were previously a hardcoded
    ``0.2.4`` that had drifted behind ``__version__``.
    """
    version = read_version()
    return {
        "CFBundleShortVersionString": version,
        "CFBundleVersion": version,
    }
