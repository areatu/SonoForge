"""Unit tests for ScanWorker."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from echo_personal_tool.application.workers.scan_worker import ScanWorker


class TestScanWorker:
    def test_instantiation(self) -> None:
        worker = ScanWorker(root=Path("/media"))
        assert worker._root == Path("/media")
        assert worker._error_log_path is None

    def test_with_error_log(self) -> None:
        worker = ScanWorker(root=Path("/media"), error_log_path=Path("/err.log"))
        assert worker._error_log_path == Path("/err.log")

    def test_has_signals(self) -> None:
        worker = ScanWorker(root=Path("/media"))
        assert hasattr(worker.signals, "finished")
        assert hasattr(worker.signals, "failed")

    def test_auto_delete(self) -> None:
        worker = ScanWorker(root=Path("/media"))
        assert worker.autoDelete() is True

    def test_run_emits_finished(self) -> None:
        mock_scanner = MagicMock()
        mock_scanner.scan.return_value = ["study1", "study2"]

        with patch(
            "echo_personal_tool.application.workers.scan_worker.LocalMediaDirectoryScanner",
            return_value=mock_scanner,
        ):
            results = []
            worker = ScanWorker(root=Path("/media"))
            worker.signals.finished.connect(lambda r: results.extend(r))
            worker.run()

        assert results == ["study1", "study2"]
        mock_scanner.scan.assert_called_once_with(Path("/media"))

    def test_run_emits_failed(self) -> None:
        mock_scanner = MagicMock()
        mock_scanner.scan.side_effect = RuntimeError("disk error")

        with patch(
            "echo_personal_tool.application.workers.scan_worker.LocalMediaDirectoryScanner",
            return_value=mock_scanner,
        ):
            errors = []
            worker = ScanWorker(root=Path("/media"))
            worker.signals.failed.connect(lambda e: errors.append(e))
            worker.run()

        assert len(errors) == 1
        assert "disk error" in errors[0]
