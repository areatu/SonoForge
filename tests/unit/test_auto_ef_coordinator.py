"""Unit tests for AutoEfCoordinator and session persistence integration."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import cv2
import numpy as np

from echo_personal_tool.application.auto_ef_coordinator import (
    AutoEfCoordinator,
    apply_auto_ef_to_controller,
    build_candidates_from_instances,
)
from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.domain.models.result_provenance import QCStatus
from echo_personal_tool.domain.services.auto_ef_pipeline import (
    AUTO_EF_RESULT_ID,
    AutoEfClipCandidate,
    run_auto_ef_pipeline,
)
from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    SEMANTICS_VERSION,
    VERSION,
    dumps,
    loads,
    validate_data,
)


def _make_dome_png(path: Path, rx: int = 36, ry: int = 64) -> None:
    canvas = np.zeros((160, 160), dtype=np.uint8)
    pts = []
    for i in range(33):
        theta = np.pi * i / 32.0
        pts.append([int(round(80 - rx * np.cos(theta))), int(round(100 - ry * np.sin(theta)))])
    cv2.fillPoly(canvas, [np.asarray(pts, dtype=np.int32)], 255)
    cv2.imwrite(str(path), canvas)


class _StubSegmenter:
    model_id = "echonet_seg_resnet50"
    model_sha256 = "0" * 64

    def __init__(self, available: bool = True) -> None:
        self._available = available

    def is_available(self) -> bool:
        return self._available

    def segment(self, frame: np.ndarray, **_kwargs: Any) -> np.ndarray:
        gray = frame.mean(axis=2) if frame.ndim == 3 else frame
        return (gray > 127).astype(np.uint8)


def _make_instance(uid: str, desc: str, path: Path) -> InstanceMetadata:
    return InstanceMetadata(
        sop_instance_uid=uid,
        series_uid=f"ser.{uid}",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.0,
        series_description=desc,
        path=path,
        media_format="image",
        clip_mode="2d",
    )


def test_build_candidates_from_instances_reads_view_hints_and_overrides(tmp_path: Path) -> None:
    p4 = tmp_path / "a4c.png"
    p2 = tmp_path / "a2c.png"
    _make_dome_png(p4, rx=38)
    _make_dome_png(p2, rx=34)
    i4 = _make_instance("uid.4", "Apical 4CH", p4)
    i2 = _make_instance("uid.2", "Clip B", p2)

    cands = build_candidates_from_instances([i4, i2], study_uid="study.1", view_overrides={"uid.2": "A2C"})
    assert len(cands) == 2
    assert cands[0].view_override == "A4C"
    assert cands[1].view_override == "A2C"


def test_apply_auto_ef_to_controller_persists_contours_and_v7_provenance() -> None:
    seg = _StubSegmenter()
    f_ed = np.zeros((160, 160), dtype=np.uint8)
    f_es = np.zeros((160, 160), dtype=np.uint8)
    cv2.circle(f_ed, (80, 90), 38, 255, -1)
    cv2.circle(f_es, (80, 90), 24, 255, -1)
    c4 = AutoEfClipCandidate("u4", [f_ed, f_es], pixel_spacing_mm=(0.5, 0.5), view_override="A4C")
    c2 = AutoEfClipCandidate("u2", [f_ed, f_es], pixel_spacing_mm=(0.5, 0.5), view_override="A2C")
    raw = run_auto_ef_pipeline([c4, c2], study_uid="1.2.840.999.1", a4c_segmenter=seg, a2c_segmenter=seg)

    store = StudyMeasurementSessionStore()
    save_calls: list[int] = []
    services = SimpleNamespace(
        measurement_store=store,
        persistence=SimpleNamespace(save_pending=lambda: save_calls.append(1)),
    )
    applied_contours: list[Any] = []
    controller = SimpleNamespace(
        services=services,
        _current_instance=None,
        state_manager=SimpleNamespace(
            snapshot=SimpleNamespace(contours=(), instance=None),
        ),
        on_contours_changed=lambda cs: applied_contours.extend(cs),
    )

    saved = apply_auto_ef_to_controller(controller, raw, bsa_m2=1.9, operator_confirmed=True)
    assert saved.provenance.qc.status == QCStatus.VALID
    assert len(applied_contours) == 4
    assert len(save_calls) == 1

    stored_prov = store.get_result_provenance("1.2.840.999.1", AUTO_EF_RESULT_ID)
    assert stored_prov is not None
    assert stored_prov.qc.status == QCStatus.VALID

    # Round-trip through v7 measurement codec + JSON Schema validator!
    data = store.get("1.2.840.999.1")
    sources = {
        "u4": {"fingerprint": "a" * 64, "frames": 2, "spacing": [0.5, 0.5]},
        "u2": {"fingerprint": "b" * 64, "frames": 2, "spacing": [0.5, 0.5]},
    }
    validate_data(data, sources)
    encoded = dumps(
        {
            "format": FORMAT,
            "schema_version": VERSION,
            "measurement_semantics_version": SEMANTICS_VERSION,
            "study_uid": "1.2.840.999.1",
            "revision": 1,
            "saved_at": "2026-11-25T12:00:00Z",
            "sources": sources,
            "data": data,
        }
    )
    decoded_record = loads(encoded)
    assert any(p.result_id == AUTO_EF_RESULT_ID for p in decoded_record["data"].result_provenance)


def test_coordinator_handles_missing_study_and_unavailable_segmenter() -> None:
    empty_ctrl = SimpleNamespace(
        services=None,
        _segmenter=_StubSegmenter(available=True),
        _current_instance=None,
        state_manager=SimpleNamespace(
            snapshot=SimpleNamespace(study=None, instance=None, calculations=None, effective_pixel_spacing=None),
        ),
    )
    coord = AutoEfCoordinator(empty_ctrl)
    failures: list[str] = []
    coord.failed.connect(failures.append)
    assert coord.start() is False
    assert failures == ["no_study"]

    inst = InstanceMetadata(
        sop_instance_uid="u1",
        series_uid="s1",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=None,
        series_description="A4C",
    )
    study = StudyMetadata(
        study_uid="st.1",
        study_datetime=datetime.now(UTC),
        series=(
            SeriesMetadata(series_uid="s1", study_uid="st.1", modality="US", description="A4C", instances=(inst,)),
        ),
    )
    unavail_ctrl = SimpleNamespace(
        services=None,
        _segmenter=_StubSegmenter(available=False),
        _current_instance=inst,
        state_manager=SimpleNamespace(
            snapshot=SimpleNamespace(study=study, instance=inst, calculations=None, effective_pixel_spacing=(0.5, 0.5)),
        ),
    )
    coord2 = AutoEfCoordinator(unavail_ctrl)
    failures2: list[str] = []
    coord2.failed.connect(failures2.append)
    assert coord2.start() is False
    assert failures2 == ["segmenter_unavailable"]
