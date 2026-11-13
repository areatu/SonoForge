"""Regression protection for fixture separation and forbidden Qt imports (#556)."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from tests.conftest import _NoQtImports, pytest_sessionfinish
from tests.unit.conftest import _unit_qt_environment


def test_pure_core_does_not_activate_qt_fixtures():
    request = Mock()
    request.config.getoption.return_value = True
    _unit_qt_environment.__wrapped__(request)
    request.getfixturevalue.assert_not_called()


def test_default_lane_preserves_qt_hygiene():
    request = Mock()
    request.config.getoption.return_value = False
    _unit_qt_environment.__wrapped__(request)
    assert [call.args[0] for call in request.getfixturevalue.call_args_list] == [
        "_drain_global_thread_pool",
        "_isolate_user_settings",
        "_gc_per_test",
        "_restore_canonical_app_sheet",
        "_stub_web_engine",
    ]


def test_qt_guard_rejects_and_records_optional_import():
    guard = _NoQtImports()
    with pytest.raises(ImportError, match="Qt import forbidden"):
        guard.find_spec("PySide6.QtWidgets")
    assert guard.attempts == ["PySide6.QtWidgets"]
    assert guard.find_spec("numpy") is None


def test_swallowed_qt_import_still_fails_lane():
    config = Mock()
    config._pure_core_guard = SimpleNamespace(attempts=["PySide6"])
    session = SimpleNamespace(config=config, exitstatus=0)
    pytest_sessionfinish(session, 0)
    assert session.exitstatus == pytest.ExitCode.TESTS_FAILED
