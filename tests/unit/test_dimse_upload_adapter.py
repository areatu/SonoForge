"""Unit tests for DimseUploadAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

from echo_personal_tool.infrastructure.dimse_upload_adapter import DimseUploadAdapter


class TestDimseUploadAdapter:
    def test_success(self) -> None:
        mock_client = MagicMock()
        mock_client.c_store.return_value = True
        adapter = DimseUploadAdapter(mock_client)

        result = adapter.upload_instance(b"\x00\x01\x02")
        assert result is True
        mock_client.c_store.assert_called_once_with(b"\x00\x01\x02")

    def test_failure(self) -> None:
        mock_client = MagicMock()
        mock_client.c_store.return_value = False
        adapter = DimseUploadAdapter(mock_client)

        result = adapter.upload_instance(b"\x00\x01")
        assert result is False

    def test_stores_client(self) -> None:
        mock_client = MagicMock()
        adapter = DimseUploadAdapter(mock_client)
        assert adapter._client is mock_client
