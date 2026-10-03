"""Tests for the Windows PE version resource and macOS bundle version metadata.

These cover ``build/pyinstaller_version.py`` and the three PyInstaller specs that
consume it. The behaviour they protect is invisible in a test run and only shows
up in a shipped binary — an empty Properties -> Details tab on Windows, a macOS
``.app`` that reports the wrong release, and a code signing provider that refuses
to sign artifacts whose product name and version are not set. So the assertions
here are deliberately about the *generated text* and about the specs wiring it in,
not about a built executable.

The version file is consumed by PyInstaller through
``versioninfo.load_version_info_from_text_file``, which ``eval()``s the file in
the ``PyInstaller.utils.win32.versioninfo`` module namespace. That module imports
``pefile`` and ``pywin32`` at top level, both Windows-only, so it cannot be
imported here on the Linux/macOS CI runners. These tests therefore evaluate the
generated text against structural stubs that capture constructor arguments, which
checks the same things the real loader depends on: the expression parses, the
constructor names are unqualified, and the field values are right.
"""

from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "build" / "pyinstaller_version.py"
VERSION_SOURCE = ROOT / "src" / "echo_personal_tool" / "__init__.py"

# Specs that produce a Windows executable, and therefore must embed a version
# resource. build/linux/build.spec is Linux-only and is intentionally absent.
WINDOWS_SPECS = [
    ROOT / "sonoforge-standalone.spec",
    ROOT / "build" / "windows" / "build.spec",
    ROOT / "build" / "presenter" / "sonoforge-presenter.spec",
]


def _load_helper():
    spec = importlib.util.spec_from_file_location("sonoforge_pyinstaller_version", HELPER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


pv = _load_helper()


# -- Structural stand-ins for PyInstaller's versioninfo classes ----------------
class _Capture:
    """Records constructor arguments so the generated text can be inspected."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        self.args = args
        self.kwargs = kwargs


class VSVersionInfo(_Capture):
    pass


class FixedFileInfo(_Capture):
    pass


class StringFileInfo(_Capture):
    pass


class StringTable(_Capture):
    pass


class StringStruct(_Capture):
    pass


class VarFileInfo(_Capture):
    pass


class VarStruct(_Capture):
    pass


_EVAL_NAMESPACE = {
    name: cls
    for name, cls in [
        ("VSVersionInfo", VSVersionInfo),
        ("FixedFileInfo", FixedFileInfo),
        ("StringFileInfo", StringFileInfo),
        ("StringTable", StringTable),
        ("StringStruct", StringStruct),
        ("VarFileInfo", VarFileInfo),
        ("VarStruct", VarStruct),
    ]
}


def _parse_version_file(path: Path) -> dict[str, Any]:
    """Evaluate a generated version file the way PyInstaller does, then flatten it."""
    text = path.read_text(encoding="utf-8")
    # The real loader calls miscutils.decode(), which honours this encoding
    # cookie; its presence is part of the contract.
    assert text.startswith("# UTF-8"), "version file must start with the '# UTF-8' cookie"
    info = eval(text, dict(_EVAL_NAMESPACE))
    assert isinstance(info, VSVersionInfo)

    ffi = info.kwargs["ffi"]
    string_file_info = info.kwargs["kids"][0]
    var_file_info = info.kwargs["kids"][1]
    assert isinstance(string_file_info, StringFileInfo)
    assert isinstance(var_file_info, VarFileInfo)

    table = string_file_info.args[0][0]
    assert isinstance(table, StringTable)
    strings = {s.args[0]: s.args[1] for s in table.args[1]}
    translation = var_file_info.args[0][0]
    assert isinstance(translation, VarStruct)

    return {
        "filevers": ffi.kwargs["filevers"],
        "prodvers": ffi.kwargs["prodvers"],
        "lang_codepage": table.args[0],
        "strings": strings,
        "translation": translation.args[1],
    }


# -- Version discovery --------------------------------------------------------


def test_read_version_matches_package_source() -> None:
    """The helper must not keep its own copy of the version."""
    match = re.search(
        r"^__version__\s*=\s*[\"']([^\"']+)[\"']",
        VERSION_SOURCE.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert match, "no __version__ in src/echo_personal_tool/__init__.py"
    assert pv.read_version() == match.group(1)


@pytest.mark.parametrize("raw", ["1.2.3", "0.3", "2", "1.2.3.4", "0.4.0rc1", "2026.1.0"])
def test_version_quad_tolerates_real_world_version_strings(raw: str) -> None:
    """A pre-release or short version must still build rather than fail a release."""
    quad = pv._version_quad(raw)
    assert len(quad) == 4
    assert quad[3] == 0
    assert all(0 <= field <= 0xFFFF for field in quad)


def test_version_quad_rejects_out_of_range_component() -> None:
    """VS_FIXEDFILEINFO packs each field into 16 bits; wrapping would be silent."""
    with pytest.raises(RuntimeError, match="outside 0..65535"):
        pv._version_quad("70000.0.0")


def test_read_version_raises_when_source_file_is_missing(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A moved or deleted version source must fail with a readable message.

    Without the explicit existence check this surfaced as a bare
    FileNotFoundError from deep inside pathlib during a PyInstaller run.
    """
    monkeypatch.setattr(pv, "_VERSION_SOURCE", tmp_path / "missing.py")
    with pytest.raises(RuntimeError, match="Could not find the version source"):
        pv.read_version()


def test_read_version_raises_when_version_is_absent(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """A source file without __version__ must fail loudly, not build unversioned."""
    stale = tmp_path / "__init__.py"
    stale.write_text('"""Package."""\n\nSOMETHING_ELSE = 1\n', encoding="utf-8")
    monkeypatch.setattr(pv, "_VERSION_SOURCE", stale)
    with pytest.raises(RuntimeError, match="Could not find __version__"):
        pv.read_version()


# -- Generated Windows version resource ---------------------------------------


def test_generated_version_file_is_structurally_valid() -> None:
    version = pv.read_version()
    path = Path(
        pv.write_version_file(
            original_filename="SonoForge.exe",
            file_description="SonoForge - desktop echocardiography analysis",
        )
    )
    parsed = _parse_version_file(path)

    assert parsed["filevers"] == parsed["prodvers"]
    assert parsed["filevers"][:3] == tuple(int(x) for x in version.split(".")[:3])
    assert parsed["strings"]["FileVersion"] == parsed["strings"]["ProductVersion"]
    assert parsed["strings"]["ProductVersion"].startswith(version)
    assert parsed["strings"]["ProductName"] == "SonoForge"
    assert parsed["strings"]["OriginalFilename"] == "SonoForge.exe"
    assert parsed["strings"]["InternalName"] == "SonoForge"
    assert parsed["strings"]["CompanyName"]
    assert "GPL-3.0" in parsed["strings"]["LegalCopyright"]


def test_lang_codepage_agrees_with_translation() -> None:
    """A mismatch here makes Windows resolve no strings at all.

    The StringTable key is a LANGID/charset pair in hex; the VarStruct
    Translation is the same pair in decimal. They describe the same block and
    must agree, or the Details tab renders empty despite valid data.
    """
    path = Path(pv.write_version_file(original_filename="SonoForge.exe", file_description="d"))
    parsed = _parse_version_file(path)
    lang_hex, codepage_hex = parsed["lang_codepage"][:4], parsed["lang_codepage"][4:]
    lang_id, codepage_id = parsed["translation"]
    assert int(lang_hex, 16) == lang_id
    assert int(codepage_hex, 16) == codepage_id


def test_product_name_can_differ_per_product() -> None:
    """Presenter ships under its own product name while staying one project."""
    path = Path(
        pv.write_version_file(
            original_filename="SonoForgePresenter.exe",
            file_description="SonoForge Presenter - portable DICOM presentation viewer",
            product_name="SonoForge Presenter",
        )
    )
    parsed = _parse_version_file(path)
    assert parsed["strings"]["ProductName"] == "SonoForge Presenter"
    assert parsed["strings"]["InternalName"] == "SonoForgePresenter"
    assert parsed["strings"]["OriginalFilename"] == "SonoForgePresenter.exe"
    # The version stays identical across products, which is what a signing
    # provider enforces: one product version value per build.
    assert parsed["strings"]["ProductVersion"].startswith(pv.read_version())


def test_version_file_is_written_outside_the_repository() -> None:
    """Generated content must not land in the working tree."""
    path = Path(pv.write_version_file(original_filename="SonoForge.exe", file_description="d"))
    assert path.is_absolute()
    assert ROOT not in path.parents


# -- macOS bundle metadata ----------------------------------------------------


def test_bundle_plist_carries_both_version_keys() -> None:
    version = pv.read_version()
    plist = pv.bundle_version_plist()
    assert plist["CFBundleShortVersionString"] == version
    assert plist["CFBundleVersion"] == version


def test_standalone_spec_has_no_hardcoded_bundle_version() -> None:
    """Regression guard: CFBundleShortVersionString was pinned at '0.2.4'.

    It drifted behind `__version__` and shipped that way, so the macOS app
    reported the wrong version in Finder and in-app. The value must come from
    bundle_version_plist().
    """
    text = (ROOT / "sonoforge-standalone.spec").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.strip().startswith("#"))
    assert not re.search(r"CFBundle(?:Short)?VersionString['\"]?\s*:\s*['\"][0-9]", code), (
        "hardcoded bundle version in sonoforge-standalone.spec; use bundle_version_plist()"
    )
    assert "bundle_version_plist()" in code


# -- Spec wiring --------------------------------------------------------------


@pytest.mark.parametrize("spec_path", WINDOWS_SPECS, ids=lambda p: p.name)
def test_windows_specs_embed_a_version_resource(spec_path: Path) -> None:
    text = spec_path.read_text(encoding="utf-8")
    assert "from pyinstaller_version import" in text, f"{spec_path.name} does not import the helper"
    assert re.search(r"version\s*=", text), f"{spec_path.name} never passes version= to EXE"
    assert "write_version_file(" in text, f"{spec_path.name} does not generate a version file"


@pytest.mark.parametrize("spec_path", WINDOWS_SPECS, ids=lambda p: p.name)
def test_specs_reach_the_helper_from_their_own_directory(spec_path: Path) -> None:
    """Each spec must add build/ to sys.path relative to SPECPATH, not to cwd.

    PyInstaller injects SPECPATH as the directory holding the spec. Anchoring to
    it keeps the import working regardless of the directory PyInstaller is
    invoked from.
    """
    text = spec_path.read_text(encoding="utf-8")
    assert "SPECPATH" in text or "PROJECT_ROOT" in text, (
        f"{spec_path.name} must derive the helper path from SPECPATH, not from cwd"
    )
    assert (ROOT / "build" / "pyinstaller_version.py").is_file()
    # build/ also contains the linux/, windows/ and presenter/ directories. If it
    # stays on sys.path those names resolve as namespace packages and can shadow
    # real modules for the remainder of the PyInstaller run, so the specs must
    # pop it again once the helper is imported.
    assert "sys.path.insert(" in text and "sys.path.remove(" in text, (
        f"{spec_path.name} must remove build/ from sys.path after importing the helper"
    )
    assert text.index("sys.path.remove(") > text.index("from pyinstaller_version import")
