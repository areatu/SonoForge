"""Unit tests for the colour ratchet (scripts/check_ui_colors.py, UI-0 PR-1).

The ratchet is the guard of the design tokens: raw colour literals are allowed
in the palette module only, and their number outside it may only fall.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_ui_colors  # noqa: E402

BASELINE = REPO_ROOT / "scripts" / "ui_colors_baseline.json"


class TestCountLiterals:
    def test_counts_six_digit_colours(self):
        assert check_ui_colors.count_literals("color: #102135;") == 1

    def test_counts_three_digit_colours(self):
        assert check_ui_colors.count_literals("color: #ddd;") == 1

    def test_counts_eight_digit_colours(self):
        assert check_ui_colors.count_literals("color: #10213580;") == 1

    def test_ignores_identifiers_that_start_with_hex_letters(self):
        """A QSS object name is not a colour."""
        assert check_ui_colors.count_literals("#added { color: red; }") == 0
        assert check_ui_colors.count_literals("#systemBar { color: red; }") == 0

    def test_counts_several_literals(self):
        assert check_ui_colors.count_literals("#111111 #222222 #333333") == 3


class TestScan:
    def test_palette_module_is_whitelisted(self):
        counts = check_ui_colors.scan()
        assert "presentation/theme/palettes.py" not in counts

    def test_scan_skips_files_without_literals(self):
        counts = check_ui_colors.scan()
        assert all(count > 0 for count in counts.values())

    def test_scan_reports_relative_paths(self):
        for path in check_ui_colors.scan():
            assert not path.startswith("/"), path
            assert path.endswith(".py"), path


class TestBaseline:
    def test_repository_is_at_or_below_the_baseline(self):
        """The gate: a new literal outside the palette module fails the build."""
        counts = check_ui_colors.scan()
        baseline = check_ui_colors.load_baseline(BASELINE)
        total = check_ui_colors.total_of(counts)
        assert total <= int(baseline["total"]), (
            f"{total} colour literals outside the palette module, "
            f"the baseline allows {baseline['total']} — use a design token instead"
        )

    def test_baseline_file_is_self_describing(self):
        baseline = check_ui_colors.load_baseline(BASELINE)
        assert baseline["version"] == 1
        assert baseline["total"] == sum(baseline["files"].values())
        assert "presentation/theme/palettes.py" in baseline["whitelist"]

    def test_baseline_matches_the_current_state(self):
        """The stored baseline is the state of the repository (no silent drift)."""
        baseline = check_ui_colors.load_baseline(BASELINE)
        assert baseline["total"] == check_ui_colors.total_of(check_ui_colors.scan())


class TestCommandLine:
    def test_gate_passes_on_the_repository(self, tmp_path, capsys):
        assert check_ui_colors.main(["--baseline", str(BASELINE)]) == 0

    def test_growth_fails(self, tmp_path, capsys):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"version": 1, "total": 1, "files": {}}), encoding="utf-8")
        assert check_ui_colors.main(["--baseline", str(baseline)]) == 1
        assert "grew" in capsys.readouterr().err

    def test_update_lowers_the_baseline(self, tmp_path, capsys):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"version": 1, "total": 10_000, "files": {}}), encoding="utf-8")
        assert check_ui_colors.main(["--baseline", str(baseline), "--update"]) == 0
        written = json.loads(baseline.read_text(encoding="utf-8"))
        assert written["total"] == check_ui_colors.total_of(check_ui_colors.scan())

    def test_update_refuses_to_raise_the_baseline(self, tmp_path, capsys):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"version": 1, "total": 1, "files": {}}), encoding="utf-8")
        assert check_ui_colors.main(["--baseline", str(baseline), "--update"]) == 1
        assert "grew" in capsys.readouterr().err

    def test_update_can_raise_the_baseline_on_request(self, tmp_path):
        baseline = tmp_path / "baseline.json"
        baseline.write_text(json.dumps({"version": 1, "total": 1, "files": {}}), encoding="utf-8")
        assert check_ui_colors.main(["--baseline", str(baseline), "--update", "--allow-growth"]) == 0
        written = json.loads(baseline.read_text(encoding="utf-8"))
        assert written["total"] > 1

    def test_json_output(self, tmp_path, capsys):
        assert check_ui_colors.main(["--baseline", str(BASELINE), "--json"]) == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["total"] == check_ui_colors.total_of(check_ui_colors.scan())
        assert payload["grew"] is False


class TestBrokenBaseline:
    def test_a_broken_baseline_is_an_error(self, tmp_path, capsys):
        baseline = tmp_path / "baseline.json"
        baseline.write_text("{not json", encoding="utf-8")
        assert check_ui_colors.main(["--baseline", str(baseline)]) == 2
        assert "baseline" in capsys.readouterr().err
