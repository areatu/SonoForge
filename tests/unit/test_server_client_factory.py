"""Tests for DICOM client factories."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.ports import QuerySource
from echo_personal_tool.infrastructure.fake_dimse_client import FakeDimseClient
from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient
from echo_personal_tool.infrastructure.orthanc_client import OrthancDicomWebClient
from echo_personal_tool.infrastructure.server_client_factory import (
    make_dimse_client,
    make_dicom_query_service,
    make_dicom_web_client,
    make_upload_targets,
    parse_query_source,
)
from echo_personal_tool.infrastructure.server_settings import ServerSettings


def test_parse_query_source_defaults() -> None:
    assert parse_query_source("auto") == QuerySource.AUTO
    assert parse_query_source("invalid") == QuerySource.DICOMWEB


def test_make_dicom_web_client_mock() -> None:
    client = make_dicom_web_client(ServerSettings(use_mock=True))
    assert isinstance(client, FakeDicomWebClient)


def test_make_dicom_web_client_real() -> None:
    client = make_dicom_web_client(ServerSettings(use_mock=False))
    assert isinstance(client, OrthancDicomWebClient)


def test_make_dimse_client_mock() -> None:
    client = make_dimse_client(ServerSettings(use_mock=True))
    assert isinstance(client, FakeDimseClient)


def test_make_dimse_client_disabled() -> None:
    assert make_dimse_client(ServerSettings(use_mock=False, dimse_enabled=False)) is None


def test_make_dicom_query_service_uses_settings_source() -> None:
    svc = make_dicom_query_service(
        ServerSettings(use_mock=True, query_source="dimse")
    )
    assert svc.source == QuerySource.DIMSE
    studies = svc.query_studies()
    assert len(studies) >= 1


def test_make_upload_targets_stow() -> None:
    uploader, stow = make_upload_targets(ServerSettings(use_mock=True), "stow")
    assert uploader is None
    assert stow is not None


def test_make_upload_targets_dimse_mock() -> None:
    uploader, stow = make_upload_targets(ServerSettings(use_mock=True), "dimse")
    assert uploader is not None
    assert stow is None


def test_make_upload_targets_dimse_disabled_raises() -> None:
    with pytest.raises(ValueError, match="DIMSE"):
        make_upload_targets(ServerSettings(use_mock=False, dimse_enabled=False), "dimse")
