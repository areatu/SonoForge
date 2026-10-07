"""Preview-and-confirm dialog for the de-identified DICOM export (design §5, §1.11).

Saving a study to a folder used to be a byte copy of the download cache: the
file that left the machine carried the real ``PatientName`` and the burned-in
header.  This dialog is the control point agreed in the spec — the user sees, on
one real frame of the study, what the export will look like, and chooses between

* **A — tags only**: identifiers are replaced, pixels stay as they were;
* **B — tags + pixels**: additionally the burned-in header band is filled with
  its own background (the same geometry the viewer and the MP4 export use).

The preselected variant comes from the file class (§5), the two optional
cleanups (§3.3 quasi-identifiers, §7 private blocks) are off by default, and
when the experimental text detector is enabled its finding is shown as advice —
never applied silently.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFrame,
    QLabel,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.domain.services.phi_mask import MaskPlan, resolve_mask_plan
from echo_personal_tool.domain.services.phi_text_detector import TextReport, detect_text_rows
from echo_personal_tool.infrastructure.dicom_deidentifier import DeidentificationOptions
from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.phi_mask_profiles import (
    PhiMaskContext,
    phi_mask_context,
    profile_recommends_pixel_masking,
    resolve_mask_spec,
)
from echo_personal_tool.presentation.anonymization_filter import AnonymizationFilter
from echo_personal_tool.presentation.dark_theme import get_theme_palette
from echo_personal_tool.presentation.styled_dialogs import localize_dialog_button_box

#: Longest side of the preview image.  The dialog is a sanity check, not a
#: diagnostic viewer; scaling down keeps a 1080×1920 strain frame cheap.
PREVIEW_MAX_SIDE = 460


@dataclass(frozen=True)
class ExportSample:
    """The instance used to show what the export will look like."""

    path: Path
    label: str = ""


def load_preview_frame(path: Path) -> np.ndarray | None:
    """Decode the first frame of ``path`` for the preview, ``None`` on failure."""
    from echo_personal_tool.infrastructure.dicom_session import get_dicom_session

    try:
        session = get_dicom_session(path)
        session.open(path)
        return np.array(session.decode_first_frame(), copy=True)
    except Exception:  # noqa: BLE001 - a preview must never break the export
        return None


def masked_preview(frame: np.ndarray, source: Path) -> np.ndarray:
    """The frame as it will look in a variant-B export."""
    return AnonymizationFilter(enabled=True).apply(frame, source)


def frame_to_pixmap(frame: np.ndarray, *, max_side: int = PREVIEW_MAX_SIDE) -> QPixmap:
    """Convert a gray/RGB frame to a QPixmap scaled to fit the dialog."""
    array = np.asarray(frame)
    if array.ndim == 3 and array.shape[2] >= 3:
        rgb = np.ascontiguousarray(array[..., :3])
        height, width = rgb.shape[:2]
        image = QImage(rgb.data, width, height, 3 * width, QImage.Format.Format_RGB888).copy()
    else:
        gray = np.ascontiguousarray(array if array.ndim == 2 else array[..., 0])
        height, width = gray.shape[:2]
        image = QImage(gray.data, width, height, width, QImage.Format.Format_Grayscale8).copy()
    pixmap = QPixmap.fromImage(image)
    if max(pixmap.width(), pixmap.height()) > max_side:
        pixmap = pixmap.scaled(
            max_side,
            max_side,
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
    return pixmap


def detector_note(report: TextReport, *, preserve_ui: bool) -> str:
    """PHI-free one-liner about what the text detector saw (advice only)."""
    if report.reason == "empty-frame":
        return tr("export_dicom.detector_no_frame")
    if not report.found:
        return tr("export_dicom.detector_none")
    band = report.band or (0, 0)
    text = tr(
        "export_dicom.detector_found",
        y0=band[0],
        y1=band[1],
        glyphs=report.glyphs,
        confidence=f"{report.confidence:.2f}",
    )
    if preserve_ui:
        text += " " + tr("export_dicom.detector_preserve_ui")
    return text


class DicomExportDialog(QDialog):
    """Ask how a study should be de-identified before it is written to disk."""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        files: int,
        target_dir: Path,
        sample: ExportSample | None = None,
        sample_frame: np.ndarray | None = None,
        context: PhiMaskContext | None = None,
        frame_size: tuple[int, int] | None = None,
        text_detector: bool = False,
        default_quasi: bool = False,
        default_private: bool = False,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("export_dicom.title"))
        self.setMinimumWidth(560)

        self._files = int(files)
        self._sample = sample
        self._sample_frame = sample_frame
        self._context = context if context is not None else phi_mask_context(sample.path if sample else None)
        self._frame_size = frame_size
        self._detector_enabled = bool(text_detector)
        self._report = detect_text_rows(sample_frame) if self._detector_enabled and sample_frame is not None else None

        recommended, reason = profile_recommends_pixel_masking(self._context, *self._mask_geometry())
        self._mask_radio = QRadioButton(tr("export_dicom.variant_b"), self)
        self._tags_radio = QRadioButton(tr("export_dicom.variant_a"), self)
        self._mask_radio.setChecked(recommended)
        self._tags_radio.setChecked(not recommended)
        self._mask_radio.setToolTip(tr("export_dicom.variant_b_hint"))
        self._tags_radio.setToolTip(tr("export_dicom.variant_a_hint"))

        self._quasi_check = QCheckBox(tr("export_dicom.clean_quasi"), self)
        self._quasi_check.setChecked(default_quasi)
        self._quasi_check.setToolTip(tr("export_dicom.clean_quasi_hint"))
        self._private_check = QCheckBox(tr("export_dicom.clean_private"), self)
        self._private_check.setChecked(default_private)
        self._private_check.setToolTip(tr("export_dicom.clean_private_hint"))

        self._preview = QLabel(self)
        self._preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._preview.setMinimumHeight(160)
        self._preview.setFrameShape(QFrame.Shape.StyledPanel)
        self._preview.setStyleSheet("background: #101418;")
        self._caption = QLabel(self)
        self._caption.setWordWrap(True)
        self._reason_label = QLabel(tr(f"export_dicom.reason_{reason}"), self)
        self._reason_label.setWordWrap(True)
        self._detector_label = QLabel(self)
        self._detector_label.setWordWrap(True)
        self._detector_label.setVisible(self._detector_enabled)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText(tr("export_dicom.agree"))
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryButton")
        localize_dialog_button_box(buttons)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(8)
        header = QLabel(tr("export_dicom.header", files=files, path=str(target_dir)), self)
        header.setWordWrap(True)
        layout.addWidget(header)
        layout.addWidget(self._preview)
        layout.addWidget(self._caption)
        layout.addWidget(self._mask_radio)
        layout.addWidget(self._tags_radio)
        layout.addWidget(self._reason_label)
        layout.addWidget(self._detector_label)
        layout.addWidget(self._quasi_check)
        layout.addWidget(self._private_check)
        layout.addWidget(buttons)

        self._mask_radio.toggled.connect(self._refresh_preview)
        self._apply_palette()
        self._refresh_preview()

    # ── behaviour ───────────────────────────────────────────────────

    @property
    def mask_pixels(self) -> bool:
        return self._mask_radio.isChecked()

    def chosen_options(self) -> DeidentificationOptions:
        """Options matching the user's choice."""
        return DeidentificationOptions(
            mask_pixels=self.mask_pixels,
            clean_quasi_identifiers=self._quasi_check.isChecked(),
            clean_private_tags=self._private_check.isChecked(),
            verify_pixels=self._detector_enabled,
        )

    def user_action(self) -> str:
        """How the choice relates to the profile recommendation (§9).

        The dialog cannot move the mask, so the vocabulary maps as: ``принял`` —
        the recommended variant and no extra cleanup; ``подвинул`` — the variant
        kept, but the quasi-identifier or private-tag cleanup turned on; and
        ``отключил`` / ``включил`` — the mask state flipped against the advice.
        """
        recommended, _reason = profile_recommends_pixel_masking(self._context, *self._mask_geometry())
        if self.mask_pixels != recommended:
            return "отключил" if not self.mask_pixels else "включил"
        if self._quasi_check.isChecked() or self._private_check.isChecked():
            return "подвинул"
        return "принял"

    def evaluation_record(self, *, accepted: bool = True) -> str:
        """One PHI-free line of geometry for the corpus evaluation (§9).

        Values only: the vendor, the frame size, what the header said about the
        region sequence, what the detector saw and what the user chose.  No
        identifier, no pixel, no file name ever enters this string — it is meant
        to be collected over many runs and compared with the profile table.
        """
        rows, cols = self._mask_geometry()
        band = self._band()
        report = self._report
        fields = [
            f"vendor={self._context.vendor.value}",
            f"H={rows}",
            f"W={cols}",
            f"has_regions={self._context.has_regions}",
            f"min_panel_y={self._context.panel_top}",
            f"detected_band={report.bounds if report is not None else None}",
            f"confidence={report.confidence if report is not None else 0.0:.2f}",
            f"applied_band={band if self.mask_pixels else None}",
            f"profile_band={band}",
            f"files={self._files}",
            f"user_action={self.user_action() if accepted else 'отменил'}",
        ]
        return " ".join(fields)

    def plan_for_preview(self) -> MaskPlan:
        """The pixel plan the preview shows (also used by tests)."""
        rows, cols = self._mask_geometry()
        spec = resolve_mask_spec(self._context.vendor, rows, cols)
        return resolve_mask_plan(spec, rows, cols, panel_top=self._context.panel_top)

    def _mask_geometry(self) -> tuple[int, int]:
        if self._frame_size is not None:
            return self._frame_size
        if self._sample_frame is not None:
            return int(self._sample_frame.shape[0]), int(self._sample_frame.shape[1])
        return 0, 0

    def _apply_palette(self) -> None:
        palette = get_theme_palette()
        self._reason_label.setStyleSheet(f"color: {palette.get('accent', '#4dd0e1')};")
        self._detector_label.setStyleSheet(f"color: {palette.get('text_muted', '#9aa5b1')};")

    def _band(self) -> tuple[int, int] | None:
        tops = [rect for rect in self.plan_for_preview().rects if rect.y0 == 0 and not rect.is_empty]
        return (0, max(rect.y1 for rect in tops)) if tops else None

    def _refresh_preview(self) -> None:
        if self._sample_frame is None:
            self._preview.setText(tr("export_dicom.preview_unavailable"))
            self._caption.setText(tr("export_dicom.caption_no_preview"))
        else:
            shown = (
                masked_preview(self._sample_frame, self._sample.path)
                if self.mask_pixels and self._sample is not None
                else self._sample_frame
            )
            self._preview.setPixmap(frame_to_pixmap(shown))
            band = self._band() if self.mask_pixels else None
            label = self._sample_label()
            if band is None:
                self._caption.setText(tr("export_dicom.caption_tags_only", label=label))
            else:
                self._caption.setText(tr("export_dicom.caption_masked", label=label, y0=band[0], y1=band[1]))
        if self._detector_enabled:
            if self._report is None:
                self._detector_label.setText(tr("export_dicom.detector_none"))
            else:
                self._detector_label.setText(detector_note(self._report, preserve_ui=self._preserves_ui()))

    def _sample_label(self) -> str:
        if self._sample is None:
            return ""
        return self._sample.label or self._sample.path.name

    def _preserves_ui(self) -> bool:
        rows, cols = self._mask_geometry()
        return resolve_mask_spec(self._context.vendor, rows, cols).preserve_ui
