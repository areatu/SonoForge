"""Gold-contour I/O for ED endocardial ground-truth annotation (plan §11.2 п.1).

File layout matches what already lives in ``gold/lv_*.json`` for ``gold105.dcm``
(Study UID, pixel spacing, per-frame points in raw image pixels) so a contour
saved straight from :class:`StrainWindow` is byte-compatible with the existing
validation harness and with ONNX segmentation benchmarks in ``domain/services``.

Only the ED frame is saved here: KPI validation (§3.7, §7) compares our contour
against the gold **on the same frame** (ED), and running the tracker end-to-end
from that contour gives the GLS number to check against the vendor. ES contours
are derived by the tracker, not hand-drawn.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    from echo_personal_tool.domain.models.speckle import StrainResult as _StrainResult

GOLD_DIR = pathlib.Path(__file__).resolve().parents[4] / "gold"
#: File-name convention so a gold contour can be matched back to its clip
#: without asking the user to type anything. ``{uid}`` is the Study Instance
#: UID from the DICOM (slashed replaced with underscores); ``{view}`` is
#: ``A4C``/``A2C``/``A3C``.
GOLD_NAME_TEMPLATE = "lv_{uid}_{view}.json"


@dataclass
class GoldContour:
    """A hand-corrected ED endocardial contour for one (study, view) pair."""

    study_id: str
    sop_instance_uid: str
    pixel_spacing_mm: tuple[float, float]
    view: str  # A4C / A2C / A3C
    frame_index: int
    points: np.ndarray  # (N, 2) in raw image pixels, open arc from annulus to annulus

    def to_dict(self, *, source_path: str = "") -> dict:
        """Serialize to the on-disk JSON schema (matches ``gold/lv_*.json``)."""
        return {
            "study_id": self.study_id,
            "sop_instance_uid": self.sop_instance_uid,
            "instance_path": source_path,
            "pixel_spacing_mm": [float(self.pixel_spacing_mm[0]), float(self.pixel_spacing_mm[1])],
            "chamber": "LV",
            "annotation_source": "sonoforge-strain-window",
            "frames": [
                {
                    "frame_index": int(self.frame_index),
                    "phase": "ED",
                    "view": self.view,
                    "chamber": "LV",
                    "points": [[float(x), float(y)] for x, y in np.asarray(self.points)],
                }
            ],
        }

    @classmethod
    def from_dict(cls, data: dict) -> GoldContour:
        frames = data.get("frames") or []
        # Pick the ED frame if present; fall back to the first frame.
        ed_frame = next((f for f in frames if str(f.get("phase", "")).upper() == "ED"), frames[0] if frames else None)
        if ed_frame is None:
            raise ValueError("gold contour has no frames list")
        pts = np.asarray(ed_frame.get("points") or [], dtype=float)
        if pts.ndim != 2 or pts.shape[1] != 2 or len(pts) < 3:
            raise ValueError("gold contour has fewer than 3 points in the ED frame")
        spacing = data.get("pixel_spacing_mm") or [1.0, 1.0]
        return cls(
            study_id=str(data.get("study_id", "")),
            sop_instance_uid=str(data.get("sop_instance_uid", "")),
            pixel_spacing_mm=(float(spacing[0]), float(spacing[1])),
            view=str(ed_frame.get("view", "") or ""),
            frame_index=int(ed_frame.get("frame_index", 0)),
            points=pts,
        )

    def save(self, directory: pathlib.Path | None = None, *, source_path: str = "") -> pathlib.Path:
        """Write the contour to ``{directory}/lv_{uid}_{view}.json`` and return the path."""
        if directory is None:
            directory = GOLD_DIR
        directory.mkdir(parents=True, exist_ok=True)
        safe_uid = (self.study_id or "unknown").replace("/", "_").replace("\\", "_")
        path = directory / GOLD_NAME_TEMPLATE.format(uid=safe_uid, view=self.view.upper())
        path.write_text(
            json.dumps(self.to_dict(source_path=source_path), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return path


def contour_from_result(
    result: _StrainResult,
    positions_ed: np.ndarray | None = None,
    *,
    view: str,
    study_uid: str = "",
    sop_instance_uid: str = "",
    pixel_spacing_mm: tuple[float, float] = (1.0, 1.0),
) -> GoldContour:
    """Build a :class:`GoldContour` from the ED endocardial positions on screen.

    ``positions_ed`` defaults to the endo-kernel positions recorded in
    ``result.tracked_ed_positions``. That is what the user has been editing
    with the mouse in the strain window, so Save picks up exactly what they
    see — not the original auto contour.
    """
    if positions_ed is None:
        if getattr(result, "tracked_ed_positions", None) is None:
            raise ValueError("no tracked ED positions — run STE first")
        endo_idx = [i for i, k in enumerate(result.kernels) if k.layer == "endo"]
        positions_ed = np.asarray(result.tracked_ed_positions)[endo_idx]
    positions_ed = np.asarray(positions_ed, dtype=float)
    if positions_ed.ndim != 2 or positions_ed.shape[1] != 2:
        raise ValueError(f"ED positions must be (N, 2), got {positions_ed.shape}")
    return GoldContour(
        study_id=study_uid,
        sop_instance_uid=sop_instance_uid,
        pixel_spacing_mm=tuple(float(v) for v in pixel_spacing_mm),
        view=str(view or "").upper(),
        frame_index=int(getattr(result, "ed_index", 0) or 0),
        points=positions_ed,
    )


def load_for(path: pathlib.Path) -> GoldContour | None:
    """Load a gold contour JSON from disk. Returns ``None`` if the file is absent."""
    if not path.is_file():
        return None
    return GoldContour.from_dict(json.loads(path.read_text(encoding="utf-8")))


def default_path_for(study_uid: str, view: str, directory: pathlib.Path | None = None) -> pathlib.Path:
    """Default save/load path for a given (study, view) pair."""
    if directory is None:
        directory = GOLD_DIR
    safe_uid = (study_uid or "unknown").replace("/", "_").replace("\\", "_")
    return directory / GOLD_NAME_TEMPLATE.format(uid=safe_uid, view=view.upper())
