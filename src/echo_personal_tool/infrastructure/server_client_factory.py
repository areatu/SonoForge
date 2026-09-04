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


def make_dicom_query_service(
    settings: ServerSettings,
    *,
    web: DicomWebClient | None = None,
    dimse: DimseClient | None = None,
) -> DicomQueryService:
    """Build the unified query service.

    ``web``/``dimse`` may be injected to share a single client instance
    between the query service, the retrieve service and the dialog (avoids
    duplicating HTTP connection pools per component). When omitted they are
    created from ``settings`` (legacy behaviour).
    """
    return DicomQueryService(
        web=web if web is not None else make_dicom_web_client(settings),
        dimse=dimse if dimse is not None else make_dimse_client(settings),
        source=parse_query_source(settings.query_source),
    )


def make_dicom_retrieve_service(
    settings: ServerSettings,
    *,
    web_client: DicomWebClient | None = None,
    dimse_client: DimseClient | None = None,
):
    """Build DicomRetrieveService for OrthancDownloadWorker.

    ``web_client``/``dimse_client`` may be injected to share a single client
    instance across the query service, retrieve service and dialog; when
    omitted they are created from ``settings`` (legacy behaviour).

    Non-blocking: no network probe is performed at build time (auto
    fallback is resolved at retrieval time). The HTTP client is registered
    as the cancel hook so a user-initiated cancel aborts in-flight
    downloads immediately instead of waiting for the timeout.
    """
    from echo_personal_tool.application.services.dicom_retrieve_service import (
        make_retrieve_service,
    )

    web: DicomWebClient | None = web_client
    if web is None:
        if settings.use_mock:
            web = FakeDicomWebClient()
        elif settings.url.strip():
            web = OrthancDicomWebClient.from_settings(settings)
        else:
            web = None
    if dimse_client is None:
        dimse_client = make_dimse_client(settings)

    service = make_retrieve_service(
        settings,
        web_client=web,
        dimse_client=dimse_client,
    )
    if web is not None and hasattr(web, "cancel_inflight"):
        service.set_cancel_web_hook(web.cancel_inflight)
    return service


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
