"""Optional ML dependencies must not add phantom JUnit tests to CI shards."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize(
    "selection,selected,skipped,suite",
    [("gui", 1, 0, "onnx"), ("not gui", 2, 2, "onnx"), ("gui", 1, 0, "ssl"), ("not gui", 27, 6, "ssl")],
    ids=["gui", "logic", "ssl-gui", "ssl-logic"],
)
def test_ml_extras_absence_preserves_selected_junit_inventory(
    tmp_path, monkeypatch, selection, selected, skipped, suite
):
    # A fresh interpreter emulates CI without torch even on an ML workstation.
    # Do not uninstall packages or loosen check_pytest_counts.py's equality gate.
    (tmp_path / "no_training_extras.py").write_text(
        "import importlib.abc\n"
        "import sys\n"
        "class NoTorch(importlib.abc.MetaPathFinder):\n"
        "    def find_spec(self, fullname, path=None, target=None):\n"
        "        if fullname == 'torch' or fullname.startswith('torch.'):\n"
        "            raise ModuleNotFoundError(\"No module named 'torch'\", name=fullname)\n"
        "sys.meta_path.insert(0, NoTorch())\n"
    )
    probe = tmp_path / "test_gui_probe.py"
    probe.write_text("import pytest\n@pytest.mark.gui\ndef test_probe():\n    assert True\n")
    junit, metrics = tmp_path / "junit.xml", tmp_path / "metrics.json"
    # Exercise isolation even in a serial local run. Nested pytest is its own
    # controller, not the parent's gw1; inheriting this identity suppresses the
    # metrics writer because only gw0 publishes a distributed inventory.
    monkeypatch.setenv("PYTEST_XDIST_WORKER", "gw1")
    env = os.environ.copy()
    for key in ("PYTEST_XDIST_WORKER", "PYTEST_XDIST_WORKER_COUNT", "PYTEST_XDIST_TESTRUNUID"):
        env.pop(key, None)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("PYTEST_ADDOPTS", None)
    env.pop("PYTEST_PLUGINS", None)
    env["PYTEST_CI_METRICS_FILE"] = str(metrics)
    env["PYTHONPATH"] = os.pathsep.join(
        [str(tmp_path), str(ROOT / ".github" / "scripts"), str(ROOT / "src"), str(ROOT)]
    )
    modules = (
        ["test_echo_template_onnx.py"]
        if suite == "onnx"
        else [
            "test_echo_ssl_objectives.py",
            "test_echo_ssl_data.py",
            "test_echo_ssl_training.py",
            "test_echo_ssl_smoke.py",
            "test_echo_ssl_gates.py",
        ]
    )
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--noconftest",
            "-p",
            "pytest_timeout",
            "-p",
            "pytest_ci_metrics",
            "-p",
            "no_training_extras",
            "-o",
            "addopts=",
            "-q",
            "-m",
            selection,
            f"--junitxml={junit}",
            *(str(ROOT / "tests/unit" / module) for module in modules),
            str(probe),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(metrics.read_text())["selected"]["total"] == selected
    suite = ET.parse(junit).getroot().find("testsuite")
    assert int(suite.get("tests")) == selected
    assert int(suite.get("skipped")) == skipped
    gate = subprocess.run(
        [
            sys.executable,
            str(ROOT / ".github/scripts/check_pytest_counts.py"),
            "--junit",
            str(junit),
            "--metrics",
            str(metrics),
        ],
        cwd=ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert gate.returncode == 0, gate.stdout + gate.stderr
