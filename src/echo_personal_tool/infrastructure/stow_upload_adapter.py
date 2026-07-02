"""Adapter: DicomWebClient STOW-RS batch exposed as per-file DicomUploadClient."""

from __future__ import annotations

from echo_personal_tool.domain.ports import DicomUploadClient, DicomWebClient


class StowUploadAdapter:
    """Single-file facade; caller should prefer batch ``stow_instances`` on worker."""

    def __init__(self, client: DicomWebClient) -> None:
        self._client = client

    def upload_instance(self, dicom_bytes: bytes) -> bool:
        result = self._client.stow_instances([dicom_bytes])
        return result.success_count == 1 and not result.failed_uids
