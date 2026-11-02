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
        assert check_ui_colors.count_literals("A = '#102135'\n") == 1

    def test_counts_three_digit_colours(self):
        assert check_ui_colors.count_literals("A = '#ddd'\n") == 1

    def test_counts_eight_digit_colours(self):
        assert check_ui_colors.count_literals("A = '#10213580'\n") == 1

    def test_ignores_identifiers_that_start_with_hex_letters(self):
        """A QSS object name is not a colour."""
        assert check_ui_colors.count_literals("A = '#added'\n") == 0
        assert check_ui_colors.count_literals("A = '#systemBar'\n") == 0

    def test_counts_several_literals(self):
        assert check_ui_colors.count_literals("A = '#111111 #222222 #333333'\n") == 3

    def test_counts_a_colour_inside_a_qss_string(self):
        assert check_ui_colors.count_literals("SHEET = 'color: #102135;'\n") == 1

    def test_comments_are_not_colours(self):
        """An issue reference in a comment must not raise the ratchet."""
        assert check_ui_colors.count_literals("# colour #ffffff in a comment (#150)\nA = '#102135'\n") == 1

    def test_only_string_literals_are_counted(self):
        source = (
            "# colour #ffffff in a comment and issue (#150)\n"
            "A = '#102135'\n"
            'B = f"color: #abc; border: 1px solid {x}"\n'
            "C = 'see issue #150 and &#123; and url(a#b)'\n"
            "D = '#12345'  # five digits: not a colour\n"
            "E = '#11223344'\n"
        )
        # '#150' inside a string is indistinguishable from a 3-digit colour and counts.
        assert check_ui_colors.count_literals(source) == 4

    def test_a_broken_file_is_scanned_as_plain_text(self):
        """A file that cannot be parsed must not hide its literals."""
        assert check_ui_colors.count_literals("def broken(:\n    color = '#102135'\n") == 1


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
