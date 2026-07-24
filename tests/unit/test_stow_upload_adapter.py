"""Unit tests for StowUploadAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

from echo_personal_tool.infrastructure.stow_upload_adapter import StowUploadAdapter


class TestStowUploadAdapter:
    def test_success(self) -> None:
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.success_count = 1
        mock_result.failed_uids = []
        mock_client.stow_instances.return_value = mock_result

        adapter = StowUploadAdapter(mock_client)
        result = adapter.upload_instance(b"\x00\x01\x02")
        assert result is True
        mock_client.stow_instances.assert_called_once_with([b"\x00\x01\x02"])

    def test_failure_count(self) -> None:
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.success_count = 0
        mock_result.failed_uids = ["uid1"]
        mock_client.stow_instances.return_value = mock_result

        adapter = StowUploadAdapter(mock_client)
        result = adapter.upload_instance(b"\x00\x01")
        assert result is False

    def test_partial_failure(self) -> None:
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.success_count = 1
        mock_result.failed_uids = ["uid1"]  # has failures
        mock_client.stow_instances.return_value = mock_result

        adapter = StowUploadAdapter(mock_client)
        result = adapter.upload_instance(b"\x00\x01")
        assert result is False  # failed_uids is non-empty

    def test_stores_client(self) -> None:
        mock_client = MagicMock()
        adapter = StowUploadAdapter(mock_client)
        assert adapter._client is mock_client
