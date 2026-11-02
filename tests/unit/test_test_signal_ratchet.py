"""Tests for the test-signal ratchet (issue #327).

The audit counted tests, not protection: a test that never asserts, never expects
an exception and never compares anything passes whatever the code does.
`scripts/check_test_signal.py` keeps the number of such tests from growing and
lets an intentional "does not raise" test exist only as an explicit, justified
exception. These tests pin what counts as a verifying signal, how tests are
collected, the arithmetic of the baseline and the command line.
"""

from __future__ import annotations

import ast
import json
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_test_signal  # noqa: E402

BASELINE_FILE = REPO_ROOT / "scripts" / "test_signal_baseline.json"
SCRIPT_FILE = REPO_ROOT / "scripts" / "check_test_signal.py"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _function(body: str) -> ast.FunctionDef:
    """A ``def test_sample():`` whose body is ``body``."""
    source = "def test_sample():\n" + textwrap.indent(textwrap.dedent(body).strip("\n"), "    ") + "\n"
    function = ast.parse(source).body[0]
    assert isinstance(function, ast.FunctionDef)
    return function


def _write_tests(tmp_path: Path, files: dict[str, str]) -> Path:
    """Create ``tmp_path/tests/<name>`` modules and return the ``tests`` directory."""
    root = tmp_path / "tests"
    for name, source in files.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(source), encoding="utf-8")
    return root


def _scan(tmp_path: Path, files: dict[str, str]) -> dict[str, check_test_signal.CollectedTest]:
    root = _write_tests(tmp_path, files)
    tests, errors = check_test_signal.scan_tests(root, relative_to=tmp_path)
    assert errors == []
    return tests


def _collected(
    node_id: str,
    *,
    signal: bool = True,
    asserts: int = 1,
    measurement: bool = False,
    smoke: bool = False,
    manual: bool = False,
    line: int = 1,
) -> check_test_signal.CollectedTest:
    return check_test_signal.CollectedTest(
        node_id=node_id,
        line=line,
        asserts=asserts,
        has_signal=signal,
        measurement=measurement,
        smoke=smoke,
        manual=manual,
    )


def _baseline(
    no_signal: tuple[str, ...] = (), smoke: dict[str, str] | None = None, metrics: dict[str, int] | None = None
) -> check_test_signal.Baseline:
    return check_test_signal.Baseline(no_signal=frozenset(no_signal), smoke=smoke or {}, metrics=metrics or {})


def _run(tmp_path: Path, *extra: str, root: Path | None = None) -> int:
    return check_test_signal.main(
        ["--root", str(root or tmp_path / "tests"), "--baseline", str(tmp_path / "baseline.json"), *extra]
    )


class TestSignalDetection:
    @pytest.mark.parametrize(
        "body",
        [
            "assert value == 1",
            "assert False, 'unreachable'",
            "with pytest.raises(ValueError):\n    run()",
            "with pytest.warns(UserWarning):\n    run()",
            "with pytest.deprecated_call():\n    run()",
            "monkeypatch.setattr(host, 'open', lambda: pytest.fail('must not open'))",
            "mock.assert_called_once_with(1)",
            "mock.assert_not_called()",
            "np.testing.assert_allclose(a, b)",
            "self.assertEqual(a, b)",
            "_assert_valid(report)",
            "qtbot.assertNotEmitted(widget.changed)",
            "with qtbot.waitSignal(widget.changed):\n    widget.change()",
            "qtbot.waitUntil(lambda: widget.ready)",
            "jsonschema.validate(document, schema)",
            "jsonschema.Draft202012Validator.check_schema(schema)",
            "assert value == 1 or other == 2",
            "assert value and True",
            "assert True and value == 1",
            "assert not value",
        ],
    )
    def test_these_bodies_can_fail_a_test(self, body: str) -> None:
        _asserts, signal = check_test_signal.analyze_body(_function(body))

        assert signal, body

    @pytest.mark.parametrize(
        "body",
        [
            "widget = make()\nwidget.show()",
            "check_roundtrip(value)",
            "same = pytest.approx(1.0)\nvalue == same",
            "snapshot = state.snapshot\nuse(snapshot)",
            "assert True",
            "assert 1",
            "assert (value == 1, 'message')",
            "assert value == 1 or True",
            "assert True or value == 1",
            "assert value or 1",
            "assert value or other or True",
            "assert True and 1",
            "assert not False",
            "assert not 0",
            "controller.failover()",
            "reassert_state(value)",
            "assertions_enabled = True",
            "errors = validator.validate(document)",
            "widget.validate()",
            "schemas.validate(document)",
        ],
    )
    def test_these_bodies_cannot_fail_a_test(self, body: str) -> None:
        _asserts, signal = check_test_signal.analyze_body(_function(body))

        assert not signal, body

    def test_assert_statements_are_counted_including_nested_callbacks(self) -> None:
        function = _function(
            """
            assert first
            def callback(value):
                assert value
            assert second, "message"
            """
        )

        assert check_test_signal.analyze_body(function) == (3, True)

    def test_a_tautology_is_counted_as_an_assert_but_not_as_a_signal(self) -> None:
        assert check_test_signal.analyze_body(_function("assert True")) == (1, False)

    def test_a_callback_that_asserts_is_enough(self) -> None:
        function = _function(
            """
            def on_event(payload):
                assert payload == 1
            subscribe(on_event)
            """
        )

        assert check_test_signal.analyze_body(function) == (1, True)


class TestCollection:
    def test_tests_are_collected_the_way_pytest_collects_them(self, tmp_path: Path) -> None:
        tests = _scan(
            tmp_path,
            {
                "unit/test_sample.py": """
                    import unittest

                    def test_top(): assert 1 == 1
                    def helper(): assert 1 == 1
                    def testing_prefix(): assert 1 == 1

                    class TestGroup:
                        def test_method(self): assert 1 == 1
                        def helper(self): assert 1 == 1
                        class TestNested:
                            def test_inner(self): assert 1 == 1

                    class NotCollected:
                        def test_hidden(self): assert 1 == 1

                    class LegacyCase(unittest.TestCase):
                        def test_old_style(self): self.assertTrue(1)
                """
            },
        )

        assert set(tests) == {
            "tests/unit/test_sample.py::test_top",
            "tests/unit/test_sample.py::testing_prefix",
            "tests/unit/test_sample.py::TestGroup::test_method",
            "tests/unit/test_sample.py::TestGroup::TestNested::test_inner",
            "tests/unit/test_sample.py::LegacyCase::test_old_style",
        }

    def test_only_modules_pytest_would_collect_are_scanned(self, tmp_path: Path) -> None:
        body = "def test_something(): assert 1 == 1\n"
        tests = _scan(
            tmp_path,
            {
                "unit/test_real.py": body,
                "unit/sample_test.py": body,
                "unit/conftest.py": body,
                "unit/helpers.py": body,
                "unit/__pycache__/test_stale.py": body,
            },
        )

        assert sorted(tests) == [
            "tests/unit/sample_test.py::test_something",
            "tests/unit/test_real.py::test_something",
        ]

    def test_async_tests_are_collected(self, tmp_path: Path) -> None:
        tests = _scan(tmp_path, {"unit/test_async.py": "async def test_later(): assert 1 == 1\n"})

        assert list(tests) == ["tests/unit/test_async.py::test_later"]

    def test_a_name_defined_twice_is_collected_once_and_the_last_definition_wins(self, tmp_path: Path) -> None:
        tests = _scan(
            tmp_path,
            {
                "unit/test_dup.py": """
                    def test_twice(): pass
                    def test_twice(): assert 1 == 1
                """
            },
        )

        assert len(tests) == 1
        assert tests["tests/unit/test_dup.py::test_twice"].has_signal

    def test_a_file_that_cannot_be_parsed_is_reported_not_raised(self, tmp_path: Path) -> None:
        root = _write_tests(
            tmp_path, {"unit/test_ok.py": "def test_ok(): assert 1 == 1\n", "unit/test_bad.py": "def (:\n"}
        )

        tests, errors = check_test_signal.scan_tests(root, relative_to=tmp_path)

        assert list(tests) == ["tests/unit/test_ok.py::test_ok"]
        assert len(errors) == 1
        assert errors[0].startswith("tests/unit/test_bad.py: cannot parse")

    def test_node_ids_are_relative_to_the_requested_base(self, tmp_path: Path) -> None:
        root = _write_tests(tmp_path, {"unit/test_sample.py": "def test_one(): assert 1 == 1\n"})

        tests, _errors = check_test_signal.scan_tests(root, relative_to=root)

        assert list(tests) == ["unit/test_sample.py::test_one"]

    def test_the_line_of_the_test_is_recorded(self, tmp_path: Path) -> None:
        tests = _scan(tmp_path, {"unit/test_lines.py": "import os\n\n\ndef test_third(): pass\n"})

        assert tests["tests/unit/test_lines.py::test_third"].line == 4


class TestMarkersAndMeasurements:
    def test_the_smoke_marker_is_seen_on_functions_classes_and_modules(self, tmp_path: Path) -> None:
        tests = _scan(
            tmp_path,
            {
                "unit/test_marks.py": """
                    import pytest
                    from pytest import mark

                    @pytest.mark.smoke
                    def test_decorated(): pass

                    @pytest.mark.smoke("builds without raising")
                    def test_with_reason(): pass

                    @mark.smoke
                    def test_short_form(): pass

                    @pytest.mark.parametrize("value", [1])
                    def test_other_marker(value): pass

                    @pytest.mark.smoke
                    class TestClassWide:
                        def test_inherits(self): pass

                    class TestAttribute:
                        pytestmark = pytest.mark.smoke
                        def test_inherits_too(self): pass

                    class TestPlain:
                        def test_unmarked(self): pass
                """,
                "unit/test_module_wide.py": """
                    import pytest

                    pytestmark = [pytest.mark.gui, pytest.mark.smoke]

                    def test_covered_by_the_module(): pass
                """,
            },
        )
        smoke = {node_id.split("::", 1)[1] for node_id, test in tests.items() if test.smoke}

        assert smoke == {
            "test_decorated",
            "test_with_reason",
            "test_short_form",
            "TestClassWide::test_inherits",
            "TestAttribute::test_inherits_too",
            "test_covered_by_the_module",
        }

    def test_the_benchmark_fixture_marks_a_measurement_that_is_not_debt(self, tmp_path: Path) -> None:
        tests = _scan(
            tmp_path,
            {
                "bench/test_speed.py": """
                    def test_timing(benchmark):
                        benchmark(run)

                    def test_timing_and_check(benchmark):
                        assert benchmark(run) == 1
                """
            },
        )
        timing = tests["tests/bench/test_speed.py::test_timing"]
        checked = tests["tests/bench/test_speed.py::test_timing_and_check"]

        assert timing.measurement
        assert not timing.is_debt
        assert checked.measurement
        assert checked.has_signal

    def test_an_interactive_diagnostic_is_manual_and_not_debt(self, tmp_path: Path) -> None:
        tests = _scan(
            tmp_path,
            {
                "interactive/test_diag.py": """
                    import pytest

                    @pytest.mark.interactive
                    def test_prints_a_report(): print("report for a human")

                    def test_plain(): print("nothing verified")
                """,
                "interactive/test_module_wide.py": """
                    import pytest

                    pytestmark = pytest.mark.interactive

                    def test_covered_by_the_module(): print("report")
                """,
            },
        )

        assert tests["tests/interactive/test_diag.py::test_prints_a_report"].manual
        assert not tests["tests/interactive/test_diag.py::test_prints_a_report"].is_debt
        assert tests["tests/interactive/test_module_wide.py::test_covered_by_the_module"].manual
        assert tests["tests/interactive/test_diag.py::test_plain"].is_debt

    @pytest.mark.parametrize(
        ("signal", "measurement", "smoke", "manual", "debt"),
        [
            (False, False, False, False, True),
            (True, False, False, False, False),
            (False, True, False, False, False),
            (False, False, True, False, False),
            (False, False, False, True, False),
        ],
    )
    def test_only_an_unexplained_test_without_signal_is_debt(
        self, signal: bool, measurement: bool, smoke: bool, manual: bool, debt: bool
    ) -> None:
        test = _collected("t", signal=signal, measurement=measurement, smoke=smoke, manual=manual)

        assert test.is_debt is debt


class TestViolations:
    def test_a_new_test_without_signal_fails_with_its_id_and_line(self) -> None:
        tests = {
            "tests/unit/test_new.py::test_it": _collected("tests/unit/test_new.py::test_it", signal=False, line=12)
        }

        violations = check_test_signal.find_violations(tests, _baseline())

        assert len(violations) == 1
        assert "tests/unit/test_new.py::test_it (line 12)" in violations[0]
        assert "@pytest.mark.smoke" in violations[0]

    def test_a_listed_legacy_test_is_tolerated(self) -> None:
        node_id = "tests/unit/test_old.py::test_it"
        tests = {node_id: _collected(node_id, signal=False)}

        assert check_test_signal.find_violations(tests, _baseline((node_id,))) == ()

    def test_strengthening_a_legacy_test_makes_its_entry_stale(self) -> None:
        node_id = "tests/unit/test_old.py::test_it"
        tests = {node_id: _collected(node_id, signal=True)}

        violations = check_test_signal.find_violations(tests, _baseline((node_id,)))

        assert len(violations) == 1
        assert "stale baseline entry" in violations[0]
        assert "--fix" in violations[0]

    def test_removing_or_renaming_a_legacy_test_makes_its_entry_stale(self) -> None:
        violations = check_test_signal.find_violations({}, _baseline(("tests/unit/test_gone.py::test_it",)))

        assert len(violations) == 1
        assert "tests/unit/test_gone.py::test_it" in violations[0]

    def test_a_smoke_test_needs_a_listed_reason(self) -> None:
        node_id = "tests/unit/test_smoke.py::test_builds"
        tests = {node_id: _collected(node_id, signal=False, smoke=True, line=7)}

        unlisted = check_test_signal.find_violations(tests, _baseline())
        listed = check_test_signal.find_violations(tests, _baseline(smoke={node_id: "must not raise on empty data"}))

        assert len(unlisted) == 1
        assert "smoke test without a reason" in unlisted[0]
        assert listed == ()

    def test_a_smoke_entry_without_the_marker_is_stale(self) -> None:
        node_id = "tests/unit/test_smoke.py::test_builds"
        tests = {node_id: _collected(node_id, signal=True)}

        violations = check_test_signal.find_violations(tests, _baseline(smoke={node_id: "reason"}))

        assert len(violations) == 1
        assert "stale smoke entry" in violations[0]

    def test_a_measurement_never_needs_an_entry(self) -> None:
        node_id = "tests/bench/test_speed.py::test_timing"
        tests = {node_id: _collected(node_id, signal=False, measurement=True)}

        assert check_test_signal.find_violations(tests, _baseline()) == ()

    def test_new_problems_are_listed_before_stale_entries(self) -> None:
        new_id = "tests/unit/test_new.py::test_it"
        stale_id = "tests/unit/test_old.py::test_it"
        tests = {new_id: _collected(new_id, signal=False)}

        violations = check_test_signal.find_violations(tests, _baseline((stale_id,)))

        assert [violation.split(" ", 1)[0] for violation in violations] == [new_id, stale_id + ":"]


class TestBaselineFile:
    def test_the_baseline_round_trips_sorted_and_with_reference_metrics(self, tmp_path: Path) -> None:
        tests = {
            "tests/unit/test_b.py::test_two": _collected("tests/unit/test_b.py::test_two", signal=False, asserts=0),
            "tests/unit/test_a.py::test_one": _collected("tests/unit/test_a.py::test_one", signal=False, asserts=0),
            "tests/unit/test_c.py::test_three": _collected("tests/unit/test_c.py::test_three", asserts=2),
        }
        path = tmp_path / "baseline.json"

        check_test_signal.write_baseline(
            path,
            tests,
            no_signal=["tests/unit/test_b.py::test_two", "tests/unit/test_a.py::test_one"],
            smoke={"tests/unit/test_z.py::test_z": "why"},
        )
        data = json.loads(path.read_text(encoding="utf-8"))
        loaded = check_test_signal.load_baseline(path)

        assert data["version"] == 1
        assert data["no_signal"] == ["tests/unit/test_a.py::test_one", "tests/unit/test_b.py::test_two"]
        assert data["metrics"]["tests"] == 3
        assert data["metrics"]["no_signal"] == 2
        assert data["metrics"]["no_assert_statement"] == 2
        assert path.read_text(encoding="utf-8").endswith("\n")
        assert loaded.no_signal == {"tests/unit/test_a.py::test_one", "tests/unit/test_b.py::test_two"}
        assert loaded.smoke == {"tests/unit/test_z.py::test_z": "why"}

    @pytest.mark.parametrize(
        "payload",
        [
            {"version": 2, "no_signal": [], "smoke": {}},
            {"version": 1, "no_signal": "tests/unit/test_a.py::test_one", "smoke": {}},
            {"version": 1, "no_signal": [], "smoke": {"tests/unit/test_a.py::test_one": "  "}},
            {"version": 1, "no_signal": [], "smoke": ["tests/unit/test_a.py::test_one"]},
            {"version": 1, "no_signal": [1], "smoke": {}},
        ],
        ids=["version", "list-expected", "blank-reason", "smoke-not-a-mapping", "non-string-id"],
    )
    def test_a_malformed_baseline_is_rejected(self, tmp_path: Path, payload: dict[str, object]) -> None:
        path = tmp_path / "baseline.json"
        path.write_text(json.dumps(payload), encoding="utf-8")

        with pytest.raises(ValueError):
            check_test_signal.load_baseline(path)


class TestReport:
    def test_metrics_split_debt_measurements_and_weak_tests(self) -> None:
        tests = {
            "a": _collected("a", signal=False, asserts=0),
            "b": _collected("b", signal=True, asserts=1),
            "c": _collected("c", signal=True, asserts=3),
            "d": _collected("d", signal=False, asserts=0, measurement=True),
            "e": _collected("e", signal=False, asserts=0, smoke=True),
            "f": _collected("f", signal=False, asserts=0, manual=True),
        }

        assert check_test_signal.summarize(tests) == {
            "tests": 6,
            "no_signal": 1,
            "measurement": 1,
            "manual": 1,
            "smoke": 1,
            "le1_assert": 5,
            "no_assert_statement": 4,
        }

    def test_the_markdown_table_shows_the_trend_against_the_baseline(self) -> None:
        metrics = {
            "tests": 110,
            "no_signal": 7,
            "measurement": 3,
            "manual": 2,
            "smoke": 1,
            "le1_assert": 50,
            "no_assert_statement": 9,
        }
        baseline = _baseline(
            tuple(f"t{number}" for number in range(10)),
            smoke={"s": "reason"},
            metrics={"tests": 100, "measurement": 3, "le1_assert": 52, "no_assert_statement": 8},
        )

        markdown = check_test_signal.render_markdown(metrics, baseline, ())

        assert "| Metric | Now | Baseline | Δ |" in markdown
        assert "| Tests | 110 | 100 | +10 |" in markdown
        assert "**Without a verifying signal** (debt, gated: may only go down) | 7 | 10 | -3 |" in markdown
        assert "| With ≤1 `assert` (informational) | 50 (45.5%) | 52 | -2 |" in markdown
        assert "| Without any `assert` statement (informational) | 9 (8.2%) | 8 | +1 |" in markdown
        assert "Violations" not in markdown

    def test_the_markdown_table_lists_violations_when_the_check_fails(self) -> None:
        metrics = {
            "tests": 1,
            "no_signal": 1,
            "measurement": 0,
            "manual": 0,
            "smoke": 0,
            "le1_assert": 1,
            "no_assert_statement": 1,
        }

        markdown = check_test_signal.render_markdown(metrics, _baseline(), ("tests/unit/test_x.py::test_y: new",))

        assert "**Violations**" in markdown
        assert "- `tests/unit/test_x.py::test_y: new`" in markdown

    def test_a_missing_reference_is_shown_as_a_dash(self) -> None:
        metrics = {
            "tests": 4,
            "no_signal": 0,
            "measurement": 0,
            "manual": 0,
            "smoke": 0,
            "le1_assert": 4,
            "no_assert_statement": 0,
        }

        markdown = check_test_signal.render_markdown(metrics, _baseline(), ())

        assert "| Tests | 4 | — | — |" in markdown


class TestCommandLine:
    def test_a_missing_baseline_is_an_error_that_explains_how_to_create_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_tests(tmp_path, {"unit/test_a.py": "def test_a(): assert 1 == 1\n"})

        assert _run(tmp_path) == 2
        assert "--fix" in capsys.readouterr().err

    def test_fix_creates_the_baseline_and_the_check_then_passes(self, tmp_path: Path) -> None:
        _write_tests(
            tmp_path,
            {"unit/test_a.py": "def test_checked(): assert 1 == 1\ndef test_legacy(): print('no check')\n"},
        )

        assert _run(tmp_path, "--fix") == 0
        baseline = json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))

        assert baseline["no_signal"] == ["tests/unit/test_a.py::test_legacy"]
        assert _run(tmp_path) == 0

    def test_a_new_test_without_signal_fails_and_fix_refuses_to_hide_it(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _write_tests(tmp_path, {"unit/test_a.py": "def test_checked(): assert 1 == 1\n"})
        assert _run(tmp_path, "--fix") == 0
        before = (tmp_path / "baseline.json").read_text(encoding="utf-8")
        capsys.readouterr()
        (root / "unit" / "test_b.py").write_text("def test_new(): print('no check')\n", encoding="utf-8")

        assert _run(tmp_path) == 1
        failure = capsys.readouterr().err
        assert "tests/unit/test_b.py::test_new" in failure

        assert _run(tmp_path, "--fix") == 1
        refusal = capsys.readouterr().err
        assert "refusing to raise the bar" in refusal
        assert "renamed or moved" in refusal
        assert (tmp_path / "baseline.json").read_text(encoding="utf-8") == before

    def test_strengthening_a_legacy_test_fails_until_fix_lowers_the_baseline(self, tmp_path: Path) -> None:
        root = _write_tests(tmp_path, {"unit/test_a.py": "def test_legacy(): print('no check')\n"})
        assert _run(tmp_path, "--fix") == 0
        (root / "unit" / "test_a.py").write_text("def test_legacy(): assert print('x') is None\n", encoding="utf-8")

        assert _run(tmp_path) == 1
        assert _run(tmp_path, "--fix") == 0
        assert json.loads((tmp_path / "baseline.json").read_text(encoding="utf-8"))["no_signal"] == []
        assert _run(tmp_path) == 0

    def test_a_smoke_test_passes_once_its_reason_is_recorded(self, tmp_path: Path) -> None:
        _write_tests(
            tmp_path,
            {"unit/test_a.py": "import pytest\n\n@pytest.mark.smoke\ndef test_builds(): print('no check')\n"},
        )

        assert _run(tmp_path, "--fix") == 1  # --fix cannot invent a reason
        path = tmp_path / "baseline.json"
        check_test_signal.write_baseline(path, {}, no_signal=[], smoke={"tests/unit/test_a.py::test_builds": "ctor"})

        assert _run(tmp_path) == 0

    def test_an_unparsable_test_module_is_an_error(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        _write_tests(tmp_path, {"unit/test_a.py": "def test_a(): assert 1 == 1\n", "unit/test_bad.py": "def (:\n"})

        assert _run(tmp_path) == 2
        assert "tests/unit/test_bad.py" in capsys.readouterr().err

    def test_a_wrong_root_does_not_pass_silently(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        (tmp_path / "empty").mkdir()

        assert _run(tmp_path, root=tmp_path / "empty") == 2
        assert "no tests found" in capsys.readouterr().err

    def test_the_summary_is_appended_to_the_github_step_summary_file(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _write_tests(tmp_path, {"unit/test_a.py": "def test_legacy(): print('no check')\n"})
        assert _run(tmp_path, "--fix") == 0
        summary = tmp_path / "summary.md"
        summary.write_text("earlier step\n", encoding="utf-8")
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        assert _run(tmp_path, "--github-summary") == 0
        text = summary.read_text(encoding="utf-8")

        assert text.startswith("earlier step\n")
        assert "### Test signal (#327)" in text
        assert "| Tests | 1 | 1 | 0 |" in text

    def test_the_summary_goes_to_stdout_outside_ci(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        _write_tests(tmp_path, {"unit/test_a.py": "def test_ok(): assert 1 == 1\n"})
        assert _run(tmp_path, "--fix") == 0
        monkeypatch.delenv("GITHUB_STEP_SUMMARY", raising=False)
        capsys.readouterr()

        assert _run(tmp_path, "--github-summary") == 0
        assert "### Test signal (#327)" in capsys.readouterr().out

    def test_a_failing_run_still_publishes_the_summary_with_the_violations(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        root = _write_tests(tmp_path, {"unit/test_a.py": "def test_ok(): assert 1 == 1\n"})
        assert _run(tmp_path, "--fix") == 0
        (root / "unit" / "test_b.py").write_text("def test_new(): print('no check')\n", encoding="utf-8")
        summary = tmp_path / "summary.md"
        monkeypatch.setenv("GITHUB_STEP_SUMMARY", str(summary))

        assert _run(tmp_path, "--github-summary") == 1
        assert "tests/unit/test_b.py::test_new" in summary.read_text(encoding="utf-8")


class TestCommittedBaseline:
    def test_the_committed_tree_passes_the_ratchet(self) -> None:
        assert check_test_signal.main([]) == 0

    def test_the_baseline_is_sorted_and_free_of_duplicates(self) -> None:
        data = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

        assert data["version"] == 1
        assert data["no_signal"] == sorted(set(data["no_signal"]))
        assert list(data["smoke"]) == sorted(data["smoke"])

    def test_the_recorded_counts_match_the_lists(self) -> None:
        data = json.loads(BASELINE_FILE.read_text(encoding="utf-8"))

        assert data["metrics"]["no_signal"] == len(data["no_signal"])
        assert data["metrics"]["smoke"] == len(data["smoke"])

    def test_every_smoke_exception_carries_a_reason(self) -> None:
        baseline = check_test_signal.load_baseline(BASELINE_FILE)

        assert all(reason.strip() for reason in baseline.smoke.values())

    def test_the_smoke_marker_is_registered(self) -> None:
        import tomllib

        config = tomllib.loads((REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
        markers = config["tool"]["pytest"]["ini_options"]["markers"]

        assert any(marker.startswith("smoke:") for marker in markers)
        assert any(marker.startswith("gui_smoke:") for marker in markers)


class TestWiring:
    def test_the_ratchet_runs_in_the_lint_job_and_publishes_its_summary(self) -> None:
        workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
        commands = [str(step.get("run", "")) for step in workflow["jobs"]["lint"]["steps"]]

        assert "python scripts/check_test_signal.py --github-summary" in commands

    def test_the_script_needs_nothing_the_lint_job_does_not_install(self) -> None:
        """The lint job installs ruff, mypy and the type-check environment, not pytest or PyYAML."""
        tree = ast.parse(SCRIPT_FILE.read_text(encoding="utf-8"))
        modules = {
            alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        }
        modules |= {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
        }

        assert modules <= set(sys.stdlib_module_names)

    @pytest.mark.parametrize(
        "document",
        ["CONTRIBUTING.md", "tests/README.md", "tests/README_RU.md", ".github/PULL_REQUEST_TEMPLATE.md"],
    )
    def test_the_rule_is_written_down_where_contributors_look(self, document: str) -> None:
        text = (REPO_ROOT / document).read_text(encoding="utf-8")

        assert "check_test_signal.py" in text
