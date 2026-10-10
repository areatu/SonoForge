"""CI must identify the last test even when pytest-timeout skips the summary."""

import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.parametrize("ending", ["Timeout", "Fatal Python error: Aborted"])
def test_annotation_filter_preserves_last_node_without_failed_summary(tmp_path, ending):
    script = Path(__file__).resolve().parents[2] / ".github/scripts/annotate_pytest_failures.py"
    node = "tests/unit/test_main_window_tabs.py::test_strip_height_tracks_caliper_control[18]"
    node_file = tmp_path / "last-node"
    result = subprocess.run(
        [sys.executable, str(script), str(node_file)],
        input=f"tests/unit/test_main_window_tabs.py::test_previous PASSED [ 10%]\n{node} +++ {ending} +++\n"
        '  File "dark_theme.py", line 1069, in _apply_theme_direct\n    app.setStyleSheet(stylesheet)\n',
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert node_file.read_text().strip() == node
    assert "app.setStyleSheet" in Path(str(node_file) + ".tail").read_text()
    assert node in result.stdout
