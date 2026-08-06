"""Network benchmarks (DIMSE / STOW-RS).

Measures: C-ECHO round-trip, C-FIND query, STOW multipart build,
C-STORE adapter, FakeClient parity.

Run:  ECHO_BENCH=1 pytest tests/bench/test_network_bench.py -v --benchmark-only

Note: Real network tests require Orthanc running (ECHO_ORTHANC=1).
      FakeClient tests always run.
"""

from __future__ import annotations

import os

import pytest

from echo_personal_tool.infrastructure.fake_dicom_web_client import FakeDicomWebClient
from echo_personal_tool.infrastructure.fake_dimse_client import FakeDimseClient
from echo_personal_tool.infrastructure.orthanc_client import _build_stow_multipart_body

_BENCH = pytest.mark.skipif(
    os.environ.get("ECHO_BENCH", "") != "1",
    reason="Set ECHO_BENCH=1 to run benchmarks",
)


# ── FakeDimseClient benchmarks ──────────────────────────────────────


@_BENCH
def test_bench_dimse_c_echo_fake(benchmark) -> None:
    """C-ECHO on FakeDimseClient — measures call overhead."""
    client = FakeDimseClient()
    benchmark(client.c_echo)


@_BENCH
def test_bench_dimse_c_find_studies_fake(benchmark) -> None:
    """C-FIND studies on FakeDimseClient."""
    client = FakeDimseClient()
    benchmark(client.c_find_studies)


@_BENCH
def test_bench_dimse_c_find_studies_filtered(benchmark) -> None:
    """C-FIND studies with patient name filter."""
    client = FakeDimseClient()
    benchmark(client.c_find_studies, patient_name="DOE")


@_BENCH
def test_bench_dimse_c_find_series_fake(benchmark) -> None:
    """C-FIND series on FakeDimseClient."""
    client = FakeDimseClient()
    benchmark(client.c_find_series, "1.2.840.113619.2.55.3.12345")


@_BENCH
def test_bench_dimse_c_find_instances_fake(benchmark) -> None:
    """C-FIND instances on FakeDimseClient."""
    client = FakeDimseClient()
    benchmark(
        client.c_find_instances,
        "1.2.840.113619.2.55.3.12345",
        "1.2.840.113619.2.55.3.12345.1",
    )


@_BENCH
def test_bench_dimse_c_store_fake(benchmark) -> None:
    """C-STORE on FakeDimseClient."""
    client = FakeDimseClient()
    benchmark(client.c_store, b"\x00" * 4096)


# ── FakeDicomWebClient benchmarks ──────────────────────────────────


@_BENCH
def test_bench_web_query_studies(benchmark) -> None:
    """QIDO-RS query_studies on FakeDicomWebClient."""
    client = FakeDicomWebClient()
    benchmark(client.query_studies)


@_BENCH
def test_bench_web_query_studies_filtered(benchmark) -> None:
    """QIDO-RS query_studies with patient filter."""
    client = FakeDicomWebClient()
    benchmark(client.query_studies, patient_name="DOE")


@_BENCH
def test_bench_web_query_series(benchmark) -> None:
    """QIDO-RS query_series."""
    client = FakeDicomWebClient()
    benchmark(client.query_series, "1.2.840.113619.2.55.3.12345")


@_BENCH
def test_bench_web_stow_instances(benchmark) -> None:
    """STOW-RS on FakeDicomWebClient."""
    client = FakeDicomWebClient()
    dummy = [b"\x00" * 2048] * 5
    benchmark(client.stow_instances, dummy)


# ── STOW multipart body build ──────────────────────────────────────


@_BENCH
def test_bench_stow_multipart_1_file(benchmark) -> None:
    """Multipart body construction for 1 DICOM file."""
    data = b"\x00" * 65536
    benchmark(_build_stow_multipart_body, "bench-boundary", [data])


@_BENCH
def test_bench_stow_multipart_10_files(benchmark) -> None:
    """Multipart body construction for 10 DICOM files."""
    data = b"\x00" * 65536
    benchmark(_build_stow_multipart_body, "bench-boundary", [data] * 10)


@_BENCH
def test_bench_stow_multipart_50_files(benchmark) -> None:
    """Multipart body construction for 50 DICOM files."""
    data = b"\x00" * 65536
    benchmark(_build_stow_multipart_body, "bench-boundary", [data] * 50)


# ── DicomQueryService ──────────────────────────────────────────────


@_BENCH
def test_bench_query_service_auto(benchmark) -> None:
    """DicomQueryService AUTO mode — web first, dimse fallback."""
    from echo_personal_tool.application.dicom_query_service import DicomQueryService
    from echo_personal_tool.domain.ports import QuerySource

    svc = DicomQueryService(
        web=FakeDicomWebClient(),
        dimse=FakeDimseClient(),
        source=QuerySource.AUTO,
    )
    benchmark(svc.query_studies)


@_BENCH
def test_bench_query_service_dimse_only(benchmark) -> None:
    """DicomQueryService DIMSE-only mode."""
    from echo_personal_tool.application.dicom_query_service import DicomQueryService
    from echo_personal_tool.domain.ports import QuerySource

    svc = DicomQueryService(
        web=FakeDicomWebClient(),
        dimse=FakeDimseClient(),
        source=QuerySource.DIMSE,
    )
    benchmark(svc.query_studies)


@_BENCH
def test_bench_query_service_series(benchmark) -> None:
    """DicomQueryService query_series delegation."""
    from echo_personal_tool.application.dicom_query_service import DicomQueryService
    from echo_personal_tool.domain.ports import QuerySource

    svc = DicomQueryService(
        web=FakeDicomWebClient(),
        dimse=FakeDimseClient(),
        source=QuerySource.AUTO,
    )
    benchmark(svc.query_series, "1.2.840.113619.2.55.3.12345")
