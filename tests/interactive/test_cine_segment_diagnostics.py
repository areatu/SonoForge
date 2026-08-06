"""Interactive diagnostics for untagged cine LV auto-segmentation.

Run on a real MP4:
  ECHO_CINE_DIAG_PATH=/path/to/clip.mp4 \\
  uv run pytest tests/interactive/test_cine_segment_diagnostics.py -m interactive -s

Or use the CLI:
  uv run python scripts/diagnose_cine_segment.py /path/to/clip.mp4 --frame 12 \\
      --output /tmp/cine_diag.png
"""

from __future__ import annotations

import os
from pathlib import Path

import cv2
import numpy as np
import pytest
from tests.fixtures.generate_synthetic_media import write_synthetic_composite_cine_mp4

from echo_personal_tool.domain.services.cine_segment_diagnostics import (
    diagnose_cine_frame,
    diagnose_video_file,
    format_diagnostic_report,
    render_diagnostic_overlay,
)
from echo_personal_tool.domain.services.segment_roi import echonet_crop_mode_for_media
from echo_personal_tool.domain.services.segmentation_service import crop_frame_for_echonet

pytestmark = pytest.mark.interactive


@pytest.mark.interactive
def test_composite_cine_geometry_uses_full_roi_crop() -> None:
    """Synthetic composite MP4: cine path must not center-square crop tall B-mode."""
    height, width = 600, 800
    frame = np.zeros((height, width, 3), dtype=np.uint8)
    frame[: int(height * 0.62), :] = 130
    frame[int(height * 0.62) :, :] = 35

    report = diagnose_cine_frame(frame, media_format="mp4", run_onnx=False)

    assert report.crop_mode == echonet_crop_mode_for_media("mp4")
    assert report.crop_height == report.crop_width
    assert report.crop_width <= width
    print(format_diagnostic_report(report))


@pytest.mark.interactive
def test_composite_mp4_diagnostic_overlay(tmp_path: Path) -> None:
    clip = tmp_path / "composite.mp4"
    write_synthetic_composite_cine_mp4(clip, frame_count=3)

    report = diagnose_video_file(clip, frame_index=1, run_onnx=False)
    print(format_diagnostic_report(report))

    from echo_personal_tool.domain.services.cine_segment_diagnostics import load_video_frame

    frame = load_video_frame(clip, 1)
    overlay = render_diagnostic_overlay(frame, roi_xyxy=report.roi_xyxy)
    out = tmp_path / "overlay.png"
    cv2.imwrite(str(out), overlay)
    print(f"overlay written: {out}")
    assert out.is_file()


@pytest.mark.interactive
def test_user_mp4_segmentation_diagnostic(tmp_path: Path) -> None:
    path_str = os.environ.get("ECHO_CINE_DIAG_PATH", "").strip()
    if not path_str:
        pytest.skip("Set ECHO_CINE_DIAG_PATH to an MP4 file for live diagnosis")
    path = Path(path_str)
    if not path.is_file():
        pytest.skip(f"ECHO_CINE_DIAG_PATH not found: {path}")

    frame_index = int(os.environ.get("ECHO_CINE_DIAG_FRAME", "0"))
    report = diagnose_video_file(path, frame_index=frame_index, run_onnx=True)
    print(format_diagnostic_report(report))

    from echo_personal_tool.domain.services.cine_segment_diagnostics import load_video_frame
    from echo_personal_tool.domain.services.segment_roi import resolve_segment_roi_xyxy
    from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine

    frame = load_video_frame(path, frame_index)
    mask = None
    if report.onnx_available:
        engine = OnnxInferenceEngine()
        roi = resolve_segment_roi_xyxy(frame, media_format="mp4")
        mask = engine.segment(frame, roi_xyxy=roi, crop_mode=report.crop_mode)
    overlay = render_diagnostic_overlay(frame, roi_xyxy=report.roi_xyxy, mask=mask)
    out = tmp_path / f"{path.stem}_f{frame_index}_diag.png"
    cv2.imwrite(str(out), overlay)
    print(f"overlay written: {out}")

    _, transform = crop_frame_for_echonet(
        frame,
        roi_xyxy=report.roi_xyxy,
        crop_mode=report.crop_mode,
    )
    print(f"crop rect: y={transform.crop_y0} x={transform.crop_x0} h={transform.crop_height} w={transform.crop_width}")
