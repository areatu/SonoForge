"""Worker wiring of the burned-ECG strip mask (plan А.5, issue #643).

These need PySide6 (QRunnable workers), so they stay out of the pure-core
lane; the mask itself and the subtract semantics are Qt-free and covered by
``test_burned_ecg_mask.py``.
"""

from __future__ import annotations

import types

import numpy as np
import pytest

pytestmark = pytest.mark.gui

from echo_personal_tool.domain.services.burned_ecg_mask import (  # noqa: E402
    store_burned_ecg_override,
    strip_from_rect,
)
from tests.unit.test_burned_ecg_mask import strip_cine  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_override():
    store_burned_ecg_override("auto")
    yield
    store_burned_ecg_override("auto")

    """The workers locate the strip once and subtract it from every consumer."""

    def test_speckle_worker_locates_and_downscales(self) -> None:
        from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker
        from echo_personal_tool.domain.models.speckle import MyocardialZone

        theta = np.linspace(0.0, np.pi, 12)
        zone = MyocardialZone(
            endo_points=np.column_stack([80 + 40 * np.cos(theta), 30 + 50 * np.sin(theta)]),
            epi_points=np.column_stack([80 + 52 * np.cos(theta), 30 + 62 * np.sin(theta)]),
            thickness_mm=8.0,
            pixel_spacing=(0.5, 0.5),
        )
        frames = strip_cine(height=200, width=300, n=24)
        worker = SpeckleTrackingWorker(frames=frames, zone=zone, pixel_spacing=(0.5, 0.5))
        state = types.SimpleNamespace(frames=frames, n_frames=frames.shape[0])
        strip = worker._detect_burned_strip(state)
        assert strip is not None
        assert strip.rect == (172, 189, 40, 280)
        state.burned_strip = strip  # what _run_setup does with the result
        exclude = worker._phase_exclude_mask(state)
        assert exclude is not None
        # The phase stack is ≤64 px on the long side: same scale as the frames.
        assert exclude.shape == (43, 64)
        assert exclude.any()

    def test_speckle_worker_override_off_locates_nothing(self) -> None:
        from echo_personal_tool.application.workers.speckle_worker import SpeckleTrackingWorker
        from echo_personal_tool.domain.models.speckle import MyocardialZone

        store_burned_ecg_override("off")
        theta = np.linspace(0.0, np.pi, 12)
        zone = MyocardialZone(
            endo_points=np.column_stack([80 + 40 * np.cos(theta), 30 + 50 * np.sin(theta)]),
            epi_points=np.column_stack([80 + 52 * np.cos(theta), 30 + 62 * np.sin(theta)]),
            thickness_mm=8.0,
            pixel_spacing=(0.5, 0.5),
        )
        frames = strip_cine(height=200, width=300, n=24)
        worker = SpeckleTrackingWorker(frames=frames, zone=zone, pixel_spacing=(0.5, 0.5))
        state = types.SimpleNamespace(frames=frames, n_frames=frames.shape[0])
        assert worker._detect_burned_strip(state) is None
        assert worker._phase_exclude_mask(state) is None

    def test_zone_mask_loses_the_band(self) -> None:
        """A strip drawn over the lower sector carves real zone pixels out."""
        from echo_personal_tool.domain.models.speckle import MyocardialZone
        from echo_personal_tool.domain.services.speckle_tracking import build_zone_mask

        theta = np.linspace(0.0, np.pi, 12)
        zone = MyocardialZone(
            endo_points=np.column_stack([80 + 40 * np.cos(theta), 40 + 95 * np.sin(theta)]),
            epi_points=np.column_stack([80 + 52 * np.cos(theta), 40 + 110 * np.sin(theta)]),
            thickness_mm=8.0,
            pixel_spacing=(0.5, 0.5),
        )
        mask = build_zone_mask(zone, (200, 300))
        strip = strip_from_rect((116, 133, 30, 270))  # over the lower sector
        carved = mask & ~strip.mask_for((200, 300))
        assert carved.sum() < mask.sum()

    def test_cine_phase_worker_scales_the_mask_to_the_downsample(self) -> None:
        from echo_personal_tool.application.workers.cine_phase_worker import CinePhaseWorker

        worker = CinePhaseWorker(
            source_path="unused.dcm",
            media_format="dicom",
            frame_time_ms=33.3,
            n_frames=24,
            instance_uid="uid",
            generation=1,
        )
        raw = list(strip_cine(height=200, width=300, n=24))
        first = np.asarray(raw[0])
        worker._raw_shape = (int(first.shape[0]), int(first.shape[1]))
        worker._burned_strip = worker._extract_burned_strip(raw)
        assert worker._burned_strip is not None
        small = np.zeros((64, 96, 3), dtype=np.uint8)
        mask = worker._downscaled_strip_mask(small[None])
        assert mask is not None
        assert mask.shape == (64, 96)
        assert mask[55:61, 13:90].any()

    def test_cine_phase_worker_override_off(self) -> None:
        from echo_personal_tool.application.workers.cine_phase_worker import CinePhaseWorker

        store_burned_ecg_override("off")
        worker = CinePhaseWorker(
            source_path="unused.dcm",
            media_format="dicom",
            frame_time_ms=33.3,
            n_frames=24,
            instance_uid="uid",
            generation=1,
        )
        assert worker._extract_burned_strip(list(strip_cine(n=24))) is None
