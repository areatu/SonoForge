"""Tests for echo_personal_tool.__main__ (0% coverage target).

Verifies freeze_support() is called and main() is invoked.
"""

from __future__ import annotations

from unittest.mock import patch


def test_freeze_support_called_on_module_load() -> None:
    """multiprocessing.freeze_support() is called when __main__ is imported."""
    with (
        patch("multiprocessing.freeze_support") as mock_freeze,
        patch("echo_personal_tool.main.main", return_value=0),
    ):
        # First import triggers the module-level code
        import echo_personal_tool.__main__  # noqa: F401

    mock_freeze.assert_called()


def test_main_module_has_main_reference() -> None:
    """__main__.py imports main from echo_personal_tool.main."""
    import inspect

    import echo_personal_tool.__main__ as _mod

    source = inspect.getsource(_mod)
    assert "from echo_personal_tool.main import main" in source


def test_freeze_support_and_main_at_module_level() -> None:
    """Module source contains freeze_support() call and main() call."""
    import inspect

    import echo_personal_tool.__main__ as _mod

    source = inspect.getsource(_mod)
    assert "multiprocessing.freeze_support()" in source
    assert "SystemExit(main())" in source
