"""Tests for DimseUploadAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

from echo_personal_tool.infrastructure.dimse_upload_adapter import DimseUploadAdapter


class TestDimseUploadAdapter:
    def test_upload_success(self) -> None:
        client = MagicMock()
        client.c_store.return_value = True
        adapter = DimseUploadAdapter(client)
        assert adapter.upload_instance(b"\x00dicom") is True
        client.c_store.assert_called_once_with(b"\x00dicom")

    def test_upload_failure(self) -> None:
        client = MagicMock()
        client.c_store.return_value = False
        adapter = DimseUploadAdapter(client)
        assert adapter.upload_instance(b"\x00data") is False

    def test_stores_client_reference(self) -> None:
        client = MagicMock()
        adapter = DimseUploadAdapter(client)
        assert adapter._client is client
