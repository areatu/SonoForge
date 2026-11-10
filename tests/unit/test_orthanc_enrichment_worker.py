"""Behavioral unit tests for OrthancEnrichmentWorker (issue 483)."""

from __future__ import annotations

import logging
from collections.abc import Callable
from unittest.mock import MagicMock

import pytest

from echo_personal_tool.application.workers.orthanc_enrichment_worker import (
    EnrichmentSignals,
    OrthancEnrichmentWorker,
)
from echo_personal_tool.domain.models.orthanc import StudyEnrichment


class TestOrthancEnrichmentWorker:
    def test_streams_batches_and_emits_finished_dict(self) -> None:
        signals = EnrichmentSignals()
        batches: list[dict[str, StudyEnrichment]] = []
        finished_calls: list[tuple[object, object]] = []
        signals.batch.connect(batches.append)
        signals.finished.connect(lambda res, err: finished_calls.append((res, err)))

        page_1 = {"1.2.3": StudyEnrichment(study_uid="1.2.3", modes=frozenset({"2D"}))}
        page_2 = {"1.2.4": StudyEnrichment(study_uid="1.2.4", modes=frozenset({"PW"}), is_stress=True)}
        full = {**page_1, **page_2}

        def _fetch(*, on_batch: Callable[[dict[str, StudyEnrichment]], None]) -> dict[str, StudyEnrichment]:
            on_batch(page_1)
            on_batch(page_2)
            return full

        worker = OrthancEnrichmentWorker(_fetch, signals)
        worker.run()

        assert batches == [page_1, page_2]
        assert finished_calls == [(full, None)]

    def test_failure_emits_safe_category_and_redacts_phi_from_logs(
        self,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        signals = EnrichmentSignals()
        finished_calls: list[tuple[object, object]] = []
        signals.finished.connect(lambda res, err: finished_calls.append((res, err)))

        def _boom(**_kwargs: object) -> dict[str, StudyEnrichment]:
            raise OSError("PHI_SECRET_PATIENT_483 /private/study.dcm")

        worker = OrthancEnrichmentWorker(_boom, signals)
        with caplog.at_level(logging.WARNING):
            worker.run()

        assert len(finished_calls) == 1
        result, error = finished_calls[0]
        assert result is None
        assert isinstance(error, str) and len(error) > 0
        assert "PHI_SECRET_PATIENT_483" not in error
        assert "operation=dicom.query code=io error_type=OSError" in caplog.text
        assert "PHI_SECRET_PATIENT_483" not in caplog.text
        assert all(record.exc_info is None for record in caplog.records)

    def test_non_dict_return_value_is_coerced_to_none(self) -> None:
        signals = EnrichmentSignals()
        finished_calls: list[tuple[object, object]] = []
        signals.finished.connect(lambda res, err: finished_calls.append((res, err)))

        worker = OrthancEnrichmentWorker(lambda **_kw: ["unexpected"], signals)  # type: ignore[arg-type,return-value]
        worker.run()

        assert finished_calls == [(None, None)]

    def test_deleted_qt_signal_runtime_error_is_ignored_cleanly(self) -> None:
        fake_signals = MagicMock()
        fake_signals.batch.emit.side_effect = RuntimeError("Signal source has been deleted")
        fake_signals.finished.emit.side_effect = RuntimeError("Signal source has been deleted")

        def _fetch(*, on_batch: Callable[[dict[str, StudyEnrichment]], None]) -> dict[str, StudyEnrichment]:
            on_batch({"1.2.3": StudyEnrichment(study_uid="1.2.3")})
            return {"1.2.3": StudyEnrichment(study_uid="1.2.3")}

        worker = OrthancEnrichmentWorker(_fetch, fake_signals)
        worker.run()

        fake_signals.batch.emit.assert_called_once()
        fake_signals.finished.emit.assert_called_once()
