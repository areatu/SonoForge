"""Tests for the broad/silent ``except`` ratchet (issue #474).

A silent ``except Exception: pass`` in a medical viewer lets a measurement come
out wrong with nothing in the log. ``scripts/check_broad_excepts.py`` holds
the number of broad and of silent handlers per layer; the four silent ones in
``domain`` were fixed together with the gate.
"""

from __future__ import annotations

import ast
import json
import logging
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_broad_excepts  # noqa: E402

BASELINE_FILE = REPO_ROOT / "scripts" / "broad_except_baseline.json"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"


def _handlers(source: str) -> list[check_broad_excepts.Handler]:
    return check_broad_excepts.iter_broad_handlers(ast.parse(textwrap.dedent(source)), "pkg/m.py")


class TestWhatCounts:
    @pytest.mark.parametrize(
        "clause",
        [
            "except:",
            "except Exception:",
            "except BaseException:",
            "except (ValueError, Exception):",
            "except builtins.Exception:",
        ],
    )
    def test_broad_clauses(self, clause: str) -> None:
        assert len(_handlers(f"try:\n    f()\n{clause}\n    log()\n")) == 1

    @pytest.mark.parametrize("clause", ["except ValueError:", "except (OSError, KeyError):", "except MyException:"])
    def test_specific_clauses_are_not_broad(self, clause: str) -> None:
        assert _handlers(f"try:\n    f()\n{clause}\n    pass\n") == []

    @pytest.mark.parametrize(
        "body",
        [
            "pass",
            "continue",
            "break",
            "...",
            "return",
            "return None",
            "return 0",
            "return ''",
            "return []",
            "return {}",
            "return ()",
            "'''why'''\n    pass",
        ],
    )
    def test_silent_bodies(self, body: str) -> None:
        source = f"for _ in x:\n  try:\n    f()\n  except Exception:\n    {body}\n"
        if body in {"return", "return None", "return 0", "return ''", "return []", "return {}", "return ()"}:
            source = f"def g():\n  try:\n    f()\n  except Exception:\n    {body}\n"
        if body.startswith("'''"):
            source = f"try:\n    f()\nexcept Exception:\n    {body}\n"

        (handler,) = _handlers(source)

        assert handler.silent

    @pytest.mark.parametrize(
        "body",
        [
            "logger.warning('x')",
            "raise",
            "return fallback()",
            "return [1]",
            "value = None",
            "log_boundary_failure(_log, 'op', exc)",
        ],
    )
    def test_bodies_that_do_something_are_not_silent(self, body: str) -> None:
        (handler,) = _handlers(f"def g():\n  try:\n    f()\n  except Exception as exc:\n    {body}\n")

        assert not handler.silent

    def test_layers_are_the_top_level_packages(self) -> None:
        assert check_broad_excepts.layer_of("domain/services/x.py") == "domain"
        assert check_broad_excepts.layer_of("main.py") == "(root)"


class TestRatchet:
    BASE = {"presentation": {"broad": 3, "silent": 1}}

    def test_a_new_silent_handler_fails_both_counters(self) -> None:
        violations = check_broad_excepts.find_violations({"presentation": {"broad": 4, "silent": 2}}, self.BASE)

        assert len(violations) == 2
        assert violations[0].startswith("presentation: 2 silent broad except handlers, the baseline allows 1 (+1)")

    def test_a_new_layer_starts_at_zero(self) -> None:
        violations = check_broad_excepts.find_violations({"imaging": {"broad": 1, "silent": 0}}, self.BASE)

        assert violations == (
            "imaging: 1 broad except handlers, the baseline allows 0 (+1) — catch the exceptions the call can "
            "actually raise",
        )

    def test_logging_a_silent_handler_passes_without_touching_the_baseline(self) -> None:
        assert check_broad_excepts.find_violations({"presentation": {"broad": 3, "silent": 0}}, self.BASE) == ()

    def test_fix_never_raises_a_ceiling(self) -> None:
        fixed = check_broad_excepts.fixed_baseline({"presentation": {"broad": 2, "silent": 1}}, self.BASE)

        assert fixed == {"presentation": {"broad": 2, "silent": 1}}

    def test_command_line_round_trip(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        module = tmp_path / "src" / "presentation" / "w.py"
        module.parent.mkdir(parents=True)
        module.write_text("try:\n    f()\nexcept Exception:\n    log()\n", encoding="utf-8")
        argv = ["--source", str(tmp_path / "src"), "--baseline", str(tmp_path / "b.json")]

        assert check_broad_excepts.main(argv) == 2
        assert check_broad_excepts.main([*argv, "--fix"]) == 0
        assert check_broad_excepts.main(argv) == 0

        module.write_text(
            module.read_text(encoding="utf-8") + "try:\n    g()\nexcept Exception:\n    pass\n", encoding="utf-8"
        )
        capsys.readouterr()
        assert check_broad_excepts.main(argv) == 1
        assert "presentation: 1 silent" in capsys.readouterr().err
        assert check_broad_excepts.main([*argv, "--fix"]) == 1

    @pytest.mark.parametrize(
        "layers",
        [{"x": {"broad": 1}}, {"x": {"broad": 1, "silent": 2}}, {"x": {"broad": -1, "silent": 0}}, []],
        ids=["missing-silent", "silent-above-broad", "negative", "not-a-dict"],
    )
    def test_a_malformed_baseline_is_rejected(self, tmp_path: Path, layers: object) -> None:
        path = tmp_path / "b.json"
        path.write_text(json.dumps({"version": 1, "layers": layers}), encoding="utf-8")

        with pytest.raises(ValueError):
            check_broad_excepts.load_baseline(path)


class TestCommittedTree:
    def test_the_committed_tree_passes_the_ratchet(self) -> None:
        assert check_broad_excepts.main([]) == 0

    def test_domain_has_no_silent_broad_handler(self) -> None:
        handlers = check_broad_excepts.scan(check_broad_excepts.DEFAULT_SOURCE)
        silent_domain = [f"{h.path}:{h.line}" for h in handlers if h.silent and h.path.startswith("domain/")]

        assert silent_domain == []
        assert check_broad_excepts.load_baseline(BASELINE_FILE)["domain"]["silent"] == 0

    def test_the_ratchet_runs_in_the_lint_job(self) -> None:
        workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
        commands = [str(step.get("run", "")) for step in workflow["jobs"]["lint"]["steps"]]

        assert "python scripts/check_broad_excepts.py --github-summary" in commands


class TestFixedDomainHandlers:
    """The four silent domain handlers now say what went wrong."""

    @pytest.mark.parametrize(
        ("module_name", "function_name"),
        [
            ("echo_personal_tool.domain.services.reference_card", "_store"),
            ("echo_personal_tool.domain.services.reference_topics", "_cached_store"),
        ],
    )
    def test_a_broken_handbook_is_logged_and_still_returns_none(
        self,
        module_name: str,
        function_name: str,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        import importlib

        from echo_personal_tool.domain.services import reference_data_store

        module = importlib.import_module(module_name)
        loader = getattr(module, function_name)
        loader.cache_clear()

        def broken(self: object) -> object:
            raise ValueError("bad yaml")

        monkeypatch.setattr(reference_data_store.ReferenceDataStore, "load", broken)
        try:
            with caplog.at_level(logging.WARNING, logger=module_name):
                assert loader("en") is None
        finally:
            loader.cache_clear()

        assert any("reference handbook (en) could not be loaded: ValueError" in r.getMessage() for r in caplog.records)
        # The exception text is never formatted into the log (it may carry a path).
        assert all("bad yaml" not in r.getMessage() for r in caplog.records)
