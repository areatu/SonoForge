"""Adapter: DimseClient -> DicomUploadClient via C-STORE."""

from __future__ import annotations

from echo_personal_tool.domain.ports import DimseClient


class DimseUploadAdapter:
    """Wraps a DimseClient to implement DicomUploadClient via c_store."""

    def __init__(self, client: DimseClient) -> None:
        self._client = client

    def upload_instance(self, dicom_bytes: bytes) -> bool:
        return self._client.c_store(dicom_bytes)
