"""Tests for StowUploadAdapter."""

from __future__ import annotations

from unittest.mock import MagicMock

from echo_personal_tool.domain.models.orthanc import StowResult
from echo_personal_tool.infrastructure.stow_upload_adapter import StowUploadAdapter


class TestStowUploadAdapter:
    def _make_client(self, result: StowResult) -> MagicMock:
        client = MagicMock()
        client.stow_instances.return_value = result
        return client

    def test_upload_success(self) -> None:
        client = self._make_client(StowResult(success_count=1))
        adapter = StowUploadAdapter(client)
        assert adapter.upload_instance(b"\x00dicom") is True
        client.stow_instances.assert_called_once_with([b"\x00dicom"])

    def test_upload_failure_success_count_zero(self) -> None:
        client = self._make_client(StowResult(success_count=0))
        adapter = StowUploadAdapter(client)
        assert adapter.upload_instance(b"\x00data") is False

    def test_upload_failure_with_failed_uids(self) -> None:
        client = self._make_client(
            StowResult(success_count=1, failed_uids=["uid1"])
        )
        adapter = StowUploadAdapter(client)
        assert adapter.upload_instance(b"\x00data") is False

    def test_upload_failure_success_count_two(self) -> None:
        """success_count != 1 means failure for single-file upload."""
        client = self._make_client(StowResult(success_count=2))
        adapter = StowUploadAdapter(client)
        assert adapter.upload_instance(b"\x00data") is False

    def test_stow_called_with_list(self) -> None:
        """stow_instances expects a list of bytes, not raw bytes."""
        client = self._make_client(StowResult(success_count=1))
        adapter = StowUploadAdapter(client)
        adapter.upload_instance(b"content")
        args = client.stow_instances.call_args[0][0]
        assert isinstance(args, list)
        assert args == [b"content"]
