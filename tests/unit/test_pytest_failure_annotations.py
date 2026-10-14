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

    # xdist may report a worker crash without a FAILED summary. The per-worker
    # current-node file must still identify the test that was running there.
    worker_node_file = tmp_path / "last-node-gw1"
    crashed_node = "tests/unit/test_gui.py::test_native_abort"
    worker_node_file.write_text(crashed_node + "\n")
    crash_result = subprocess.run(
        [sys.executable, str(script), str(node_file), "1"],
        input=f"worker 'gw1' crashed while running '{crashed_node}'\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert node_file.read_text().strip() == crashed_node
    assert crashed_node in crash_result.stdout

    # If the crash summary omits the active node, fall back to the worker's
    # fsynced node file rather than relying on a stale controller path.
    fallback_node_file = tmp_path / "last-node-gw2"
    fallback_node = "tests/unit/test_storage.py::test_write_cache"
    fallback_node_file.write_text(fallback_node + "\n")
    fallback_result = subprocess.run(
        [sys.executable, str(script), str(node_file), "1"],
        input="worker 'gw2' crashed unexpectedly\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert node_file.read_text().strip() == fallback_node
    assert "::error title=pytest crash" in fallback_result.stdout

    # xdist's "node down" form must identify gw1, not the newer/live gw2.
    down_result = subprocess.run(
        [sys.executable, str(script), str(node_file), "1"],
        input="[gw1] node down: Not properly terminated\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert node_file.read_text().strip() == crashed_node
    assert "::error title=pytest crash" in down_result.stdout
    worker_node_file.unlink()
    missing_result = subprocess.run(
        [sys.executable, str(script), str(node_file), "1"],
        input="[gw1] node down: Not properly terminated\n",
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert not node_file.exists()
    assert "active node unavailable for the crashed worker" in missing_result.stdout


def test_worker_crash_summary_still_publishes_fatal_stack(tmp_path, monkeypatch):
    script = Path(__file__).resolve().parents[2] / ".github/scripts/annotate_pytest_failures.py"
    node = "tests/unit/test_viewer_display_quality.py::test_debug_overlay_toggle"
    log = tmp_path / "pytest.log"
    # Native stack is far above the final short summary (more than tail's 80
    # lines), and background-thread frames precede the crashing thread.
    log.write_text(
        "Fatal Python error: Segmentation fault\n\n"
        "Thread 0x01 (most recent call first):\n"
        '  File "threading.py", line 324 in wait\n\n'
        "Current thread 0x02 (most recent call first):\n"
        '  File "echo_personal_tool/presentation/viewer_widget.py", line 1771 in toggle_debug_overlay\n'
        '  File "tests/unit/test_viewer_display_quality.py", line 50 in test_debug_overlay_toggle\n\n'
        + "other test PASSED\n" * 100
        + f"FAILED {node} - worker 'gw2' crashed while running '{node}'\n"
        + "1 failed, 850 passed\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PYTEST_LOG_FILE", str(log))
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "last-node"), "1"],
        input=log.read_text(),
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    annotations = [line for line in result.stdout.splitlines() if line.startswith("::error")]
    assert any("title=FAILED" in line and node in line for line in annotations)
    crash = [line for line in annotations if "title=pytest crash" in line]
    assert any("Fatal Python error: Segmentation fault" in line for line in crash)
    assert any("Current thread" in line for line in crash)
    assert any("viewer_widget.py" in line for line in crash)
    assert len(crash) == 1
    assert "%0ACurrent thread" in crash[0]
    assert (tmp_path / "last-node").read_text().strip() == node

    # An ordinary Python failure may include a traceback header too. It must
    # not be labelled a native crash when there is no worker-crash report.
    ordinary = f"Traceback (most recent call last):\nFAILED {node} - ValueError: invalid input\n"
    log.write_text(ordinary, encoding="utf-8")
    result = subprocess.run(
        [sys.executable, str(script), str(tmp_path / "last-node"), "1"],
        input=ordinary,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    )
    assert "::error title=FAILED" in result.stdout
    assert "title=pytest crash" not in result.stdout


@pytest.mark.parametrize(
    "executed,selected,expected,message",
    [(1, 2, 1, "dropped"), (3, 2, 1, "extra reports"), (2, 2, 0, "none lost")],
)
def test_count_gate_distinguishes_missing_from_extra_reports(tmp_path, executed, selected, expected, message):
    import json

    script = Path(__file__).resolve().parents[2] / ".github/scripts/check_pytest_counts.py"
    junit, metrics = tmp_path / "junit.xml", tmp_path / "metrics.json"
    junit.write_text(f'<testsuites><testsuite tests="{executed}" /></testsuites>')
    metrics.write_text(json.dumps({"selected": {"total": selected}}))
    result = subprocess.run(
        [sys.executable, str(script), "--junit", str(junit), "--metrics", str(metrics)],
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )
    assert result.returncode == expected
    assert message in result.stdout
    if executed > selected:
        assert "dropped" not in result.stdout
