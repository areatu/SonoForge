"""Pytest configuration."""

from __future__ import annotations

import importlib.abc
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

ORTHANC_FIXTURES = ROOT / "tests" / "fixtures" / "orthanc"

import pytest


@pytest.hookimpl(hookwrapper=True, tryfirst=True)
def pytest_runtest_teardown(item, nextitem):  # noqa: ARG001
    """Flush Qt's deferred deletions after pytest-qt closed the widgets.

    ``pytest-qt`` calls ``widget.close()`` + ``deleteLater()`` on every widget
    registered through ``qtbot.addWidget``, but it never dispatches
    ``DeferredDelete``. A closed ``MainWindow`` therefore stays alive with its
    whole widget tree (~200 MB) until the worker process ends, and four xdist
    workers OOM the runner. Delivering the posted events here frees the C++
    objects between tests.
    """
    yield
    if item.config.getoption("--pure-core"):
        return
    try:
        from PySide6.QtCore import QCoreApplication, QEvent
        from PySide6.QtWidgets import QApplication
    except ImportError:  # pragma: no cover - PySide6 is a hard dependency
        return
    app = QApplication.instance()
    if app is None:
        return
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    app.processEvents()


@pytest.fixture(autouse=True)
def _ru_locale():
    """Reset language to Russian before each test."""
    from echo_personal_tool.infrastructure.i18n import set_language

    set_language("ru")
    yield
    set_language("ru")


# ── Orthanc DICOMweb fixtures ──────────────────────────────────────


@pytest.fixture()
def qido_studies_single() -> list[dict]:
    with open(ORTHANC_FIXTURES / "qido" / "studies_single.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_studies_multi() -> list[dict]:
    with open(ORTHANC_FIXTURES / "qido" / "studies_multi.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_studies_empty() -> list[dict]:
    with open(ORTHANC_FIXTURES / "qido" / "studies_empty.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_series_echo() -> list[dict]:
    with open(ORTHANC_FIXTURES / "qido" / "series_echo.json") as f:
        return json.load(f)


@pytest.fixture()
def qido_series_ct() -> list[dict]:
    with open(ORTHANC_FIXTURES / "qido" / "series_ct.json") as f:
        return json.load(f)


@pytest.fixture()
def wado_instance_metadata() -> dict:
    with open(ORTHANC_FIXTURES / "wado" / "instance_metadata.json") as f:
        return json.load(f)


@pytest.fixture()
def wado_instances_echo() -> list[dict]:
    with open(ORTHANC_FIXTURES / "wado" / "instances_echo.json") as f:
        return json.load(f)


@pytest.fixture()
def stow_success() -> dict:
    with open(ORTHANC_FIXTURES / "stow" / "success.json") as f:
        return json.load(f)


@pytest.fixture()
def stow_partial_failure() -> dict:
    with open(ORTHANC_FIXTURES / "stow" / "partial_failure.json") as f:
        return json.load(f)


@pytest.fixture()
def stow_all_failed() -> dict:
    with open(ORTHANC_FIXTURES / "stow" / "all_failed.json") as f:
        return json.load(f)


@pytest.fixture()
def error_500() -> dict:
    with open(ORTHANC_FIXTURES / "errors" / "500_internal.json") as f:
        return json.load(f)


@pytest.fixture()
def error_401() -> dict:
    with open(ORTHANC_FIXTURES / "errors" / "401_unauthorized.json") as f:
        return json.load(f)


@pytest.fixture()
def error_404() -> dict:
    with open(ORTHANC_FIXTURES / "errors" / "404_not_found.json") as f:
        return json.load(f)


@pytest.fixture()
def error_408() -> dict:
    with open(ORTHANC_FIXTURES / "errors" / "408_timeout.json") as f:
        return json.load(f)


class _NoQtImports(importlib.abc.MetaPathFinder):
    """Reject, rather than stub, Qt in the explicitly isolated regression lane."""

    def __init__(self):
        self.attempts = []

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] in {"PySide6", "PyQt6", "PyQt5", "PySide2", "pytestqt"}:
            self.attempts.append(fullname)
            raise ImportError(f"Qt import forbidden in --pure-core: {fullname}")
        return None


def pytest_addoption(parser):
    parser.addoption("--pure-core", action="store_true", help="Run the Qt-free regression manifest only")


def pytest_configure(config):
    if not config.getoption("--pure-core"):
        return
    if any(name.split(".")[0] in {"PySide6", "PyQt6", "PyQt5", "PySide2", "pytestqt"} for name in sys.modules):
        raise pytest.UsageError("--pure-core requires a fresh process with PYTEST_DISABLE_PLUGIN_AUTOLOAD=1")
    guard = _NoQtImports()
    sys.meta_path.insert(0, guard)
    config._pure_core_guard = guard
    config.add_cleanup(lambda: sys.meta_path.remove(guard))


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--pure-core"):
        return
    allowed = set(json.loads((ROOT / "tests/pure_core_manifest.json").read_text())["modules"])
    unexpected = sorted({item.path.relative_to(ROOT).as_posix() for item in items} - allowed)
    if unexpected:
        raise pytest.UsageError("Outside pure-core manifest: " + ", ".join(unexpected))
    if not items:
        raise pytest.UsageError("The pure-core lane must not be empty")


def pytest_sessionfinish(session, exitstatus):
    guard = getattr(session.config, "_pure_core_guard", None)
    if guard is not None and guard.attempts:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter:
            reporter.write_sep("!", "Forbidden Qt imports: " + ", ".join(sorted(set(guard.attempts))))
        session.exitstatus = pytest.ExitCode.TESTS_FAILED
