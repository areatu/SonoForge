"""Factory helpers for DICOMweb / DIMSE clients and query service."""

from __future__ import annotations

from echo_personal_tool.application.dicom_query_service import DicomQueryService
from echo_personal_tool.domain.ports import (
    DicomUploadClient,
    DicomWebClient,
    DimseClient,
    QuerySource,
)
from echo_personal_tool.infrastructure.dimse_client import PynetdimseClient
from echo_personal_tool.infrastructure.dimse_upload_adapter import DimseUploadAdapter
from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient
from echo_personal_tool.infrastructure.fake_dimse_client import FakeDimseClient
from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient
from echo_personal_tool.infrastructure.server_settings import ServerSettings


def parse_query_source(value: str) -> QuerySource:
    try:
        return QuerySource(value)
    except ValueError:
        return QuerySource.DICOMWEB


def make_dimse_client(settings: ServerSettings) -> DimseClient | None:
    if settings.use_mock:
        return FakeDimseClient()
    if not settings.dimse_enabled:
        return None
    return PynetdimseClient.from_settings(settings)


def make_dicom_web_client(settings: ServerSettings) -> DicomWebClient:
    if settings.use_mock:
        return FakeDicomWebClient()
    return OrthancDicomWebClient.from_settings(settings)


def make_dicom_query_service(settings: ServerSettings) -> DicomQueryService:
    return DicomQueryService(
        web=make_dicom_web_client(settings),
        dimse=make_dimse_client(settings),
        source=parse_query_source(settings.query_source),
    )


def make_dicom_retrieve_service(settings: ServerSettings):
    """Build DicomRetrieveService for OrthancDownloadWorker."""
    from echo_personal_tool.application.services.dicom_retrieve_service import (
        make_retrieve_service,
    )

    web: DicomWebClient | None
    if settings.use_mock:
        web = FakeDicomWebClient()
    elif settings.url.strip():
        web = OrthancDicomWebClient.from_settings(settings)
    else:
        web = None

    return make_retrieve_service(
        settings,
        web_client=web,
        dimse_client=make_dimse_client(settings),
    )


def make_upload_targets(
    settings: ServerSettings,
    protocol: str,
) -> tuple[DicomUploadClient | None, DicomWebClient | None]:
    """Return (c-store uploader, stow client) for DicomUploadWorker."""
    if protocol == "stow":
        return None, make_dicom_web_client(settings)
    if protocol == "dimse":
        dimse = make_dimse_client(settings)
        if dimse is None:
            raise ValueError("DIMSE is not enabled in server settings")
        return DimseUploadAdapter(dimse), None
    raise ValueError(f"Unknown upload protocol: {protocol}")


def dimse_upload_available(settings: ServerSettings) -> bool:
    return settings.use_mock or settings.dimse_enabled


def stow_upload_available(settings: ServerSettings) -> bool:
    if settings.use_mock:
        return True
    return bool(settings.stow_dicom_web_url.strip() or settings.url.strip())
