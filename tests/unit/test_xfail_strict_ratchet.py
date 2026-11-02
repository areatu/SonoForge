"""S1-04 (audit 2026-10-22 §13) ratchet: every ``xfail`` is strict.

A non-strict ``xfail`` turns an expected failure into a permanently green
test: the day the underlying defect is fixed, the marker stops guarding
anything and nobody notices — the suite keeps reporting the same "expected
failure" forever. ``xfail_strict = true`` in ``[tool.pytest.ini_options]``
makes strictness the default; this ratchet makes the default auditable.

Two independent failure modes are covered:

* a future ``@pytest.mark.xfail(reason=...)`` written without an explicit
  ``strict=True`` — it would inherit the default, but an explicit
  ``strict=False`` would silently opt back out of it;
* ``xfail_strict`` being removed from the pytest configuration, which would
  silently downgrade every marker in the repository at once.

The inventory below is intentionally empty: the target state and the current
state are the same, so the failure message stays explicit instead of growing a
"known debt" list that would rot. Do not add entries to silence the ratchet —
fix the marker.
"""

from __future__ import annotations

import ast
from pathlib import Path

import tomllib

_REPO_ROOT = Path(__file__).resolve().parents[2]
_TESTS_ROOT = _REPO_ROOT / "tests"
_PYPROJECT = _REPO_ROOT / "pyproject.toml"

# ``(relative file, line)`` of any marker allowed to be non-strict. Empty:
# nothing is. A marker that unexpectedly starts passing belongs on the
# caller's fix list, not on this one.
_ALLOWED_NON_STRICT: frozenset[tuple[str, int]] = frozenset()


def _xfail_call(node: ast.AST) -> ast.Call | None:
    """Return ``node`` when it is a ``pytest.mark.xfail(...)`` call."""
    if not isinstance(node, ast.Call):
        return None
    func = node.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "xfail"
        and isinstance(func.value, ast.Attribute)
        and func.value.attr == "mark"
    ):
        return node
    return None


def _marker_kwargs(call: ast.Call) -> dict[str, ast.expr]:
    return {keyword.arg: keyword.value for keyword in call.keywords}


def _non_strict_markers() -> list[tuple[str, int, str]]:
    """Inventory ``xfail`` markers that are not explicitly strict."""
    offenders: list[tuple[str, int, str]] = []
    for path in sorted(_TESTS_ROOT.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        rel = path.relative_to(_REPO_ROOT).as_posix()
        for node in ast.walk(tree):
            call = _xfail_call(node)
            if call is None:
                continue
            kwargs = _marker_kwargs(call)
            strict = kwargs.get("strict")
            if isinstance(strict, ast.Constant) and strict.value is True:
                continue
            if (rel, call.lineno) in _ALLOWED_NON_STRICT:
                continue
            if strict is None:
                reason = "no explicit strict=True (relies on the default)"
            elif isinstance(strict, ast.Constant):
                reason = f"strict={strict.value!r}"
            else:
                reason = "strict= is not a literal True"
            offenders.append((rel, call.lineno, reason))
    return offenders


def test_pytest_config_marks_xfail_strict() -> None:
    """``xfail_strict`` must stay ``true`` in the pytest configuration."""
    with _PYPROJECT.open("rb") as handle:
        config = tomllib.load(handle)
    pytest_options = config["tool"]["pytest"]["ini_options"]
    assert pytest_options.get("xfail_strict") is True, (
        "[tool.pytest.ini_options] must set xfail_strict = true; without it every "
        "xfail in the repository silently becomes a non-strict expected failure"
    )


def test_every_xfail_marker_is_explicitly_strict() -> None:
    """No ``xfail`` may opt out of strict mode."""
    offenders = _non_strict_markers()
    assert not offenders, (
        "non-strict xfail markers found — make each one explicit strict=True, or "
        "delete the marker if the expected failure has been fixed:\n"
        + "\n".join(f"  {rel}:{line}: {reason}" for rel, line, reason in offenders)
    )


def test_ratchet_detects_a_marker_without_strict(tmp_path: Path) -> None:
    """The detector must flag a bare ``xfail(reason=...)``."""
    module = tmp_path / "test_sample.py"
    module.write_text(
        "import pytest\n\n\n@pytest.mark.xfail(reason='stale gap')\ndef test_demo():\n    assert False\n",
        encoding="utf-8",
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    calls = [_xfail_call(node) for node in ast.walk(tree)]
    found = [call for call in calls if call is not None]
    assert len(found) == 1
    assert "strict" not in _marker_kwargs(found[0])


def test_ratchet_accepts_an_explicit_strict_marker(tmp_path: Path) -> None:
    """An explicit ``strict=True`` must not be flagged."""
    module = tmp_path / "test_sample.py"
    module.write_text(
        "import pytest\n\n\n@pytest.mark.xfail(reason='real gap', strict=True)\ndef test_demo():\n    assert False\n",
        encoding="utf-8",
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    calls = [_xfail_call(node) for node in ast.walk(tree)]
    found = [call for call in calls if call is not None]
    assert len(found) == 1
    assert _marker_kwargs(found[0])["strict"].value is True
