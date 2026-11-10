"""Unit tests for .github/scripts/check_worker_coverage.py (issue 483)."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = ROOT / ".github" / "scripts" / "check_worker_coverage.py"
spec = importlib.util.spec_from_file_location("check_worker_coverage", SCRIPT_PATH)
assert spec is not None and spec.loader is not None
cwc = importlib.util.module_from_spec(spec)
sys.modules["check_worker_coverage"] = cwc
spec.loader.exec_module(cwc)


def _build_cobertura_xml(
    workers: dict[str, tuple[int, int]],
    *,
    prefix: str = "src/echo_personal_tool/application/workers/",
) -> str:
    """Create a synthetic Cobertura XML with ``(covered, total)`` per worker file."""
    classes: list[str] = []
    for name, (covered, total) in workers.items():
        lines_xml = "\n".join(f'<line number="{idx + 1}" hits="{1 if idx < covered else 0}"/>' for idx in range(total))
        classes.append(
            f'<class name="{name}" filename="{prefix}{name}" line-rate="0.9"><lines>{lines_xml}</lines></class>'
        )
    return (
        '<?xml version="1.0" ?><coverage><packages><package name="workers"><classes>'
        + "".join(classes)
        + "</classes></package></packages></coverage>"
    )


class CheckWorkerCoverageTests(unittest.TestCase):
    def test_package_relative_cobertura_filenames_are_parsed(self) -> None:
        workers = {f"w_{idx}.py": (9, 10) for idx in range(16)}
        with tempfile.TemporaryDirectory() as tmp:
            xml_file = Path(tmp) / "coverage.xml"
            xml_file.write_text(_build_cobertura_xml(workers, prefix="application/workers/"), encoding="utf-8")
            self.assertEqual(cwc.main([str(xml_file), "--min-files", "15"]), 0)

    def test_passing_cobertura_report_returns_zero(self) -> None:
        workers = {f"w_{idx}.py": (9, 10) for idx in range(16)}
        workers["__init__.py"] = (0, 0)
        with tempfile.TemporaryDirectory() as tmp:
            xml_file = Path(tmp) / "coverage.xml"
            xml_file.write_text(_build_cobertura_xml(workers), encoding="utf-8")
            summary_file = Path(tmp) / "summary.md"
            items = cwc.parse_worker_coverage(xml_file)
            self.assertEqual(len(items), 16)
            self.assertEqual(
                cwc.evaluate(items, min_files=15, min_total_percent=82.0, min_module_percent=65.0),
                [],
            )
            summary = cwc.render_summary(items, 82.0, 65.0)
            summary_file.write_text(summary, encoding="utf-8")
            self.assertIn("w_0.py", summary)

    def test_zero_percent_module_fails_even_when_package_average_is_high(self) -> None:
        workers = {f"w_{idx}.py": (100, 100) for idx in range(15)}
        workers["untested_worker.py"] = (0, 40)
        with tempfile.TemporaryDirectory() as tmp:
            xml_file = Path(tmp) / "coverage.xml"
            xml_file.write_text(_build_cobertura_xml(workers), encoding="utf-8")
            code = cwc.main(
                [str(xml_file), "--min-files", "15", "--min-total-percent", "82", "--min-module-percent", "65"]
            )
            self.assertEqual(code, 1)

    def test_vacuous_report_with_too_few_worker_files_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            xml_file = Path(tmp) / "coverage.xml"
            xml_file.write_text(_build_cobertura_xml({"only_one.py": (10, 10)}), encoding="utf-8")
            code = cwc.main([str(xml_file), "--min-files", "15"])
            self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
