"""Tests for presentation/dicom_export_dialog.py (design doc §5, §10).

The dialog is the confirmation step: it shows the frame as the export will look
and preselects variant A or B from the profile table, and the user can override
it.  These tests pin the defaults per device class, the options handed to the
worker and the promise that the preview never takes the export down with it.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from echo_personal_tool.infrastructure.phi_mask_profiles import (
    PhiMaskContext,
    clear_phi_mask_context_cache,
)
from echo_personal_tool.infrastructure.vendor_profiles.base import Vendor

pytestmark = pytest.mark.gui

#: Samsung 884x1180 with burned-in text: the corpus case for variant B.
SAMSUNG = PhiMaskContext(vendor=Vendor.SAMSUNG, panel_top=100, burned_in="YES", has_regions=True)


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    clear_phi_mask_context_cache()
    yield app
    clear_phi_mask_context_cache()


@pytest.fixture()
def frame():
    """A header band with glyph-like marks over a brighter panel."""
    array = np.full((884, 1180), 25, dtype=np.uint8)
    array[100:, :] = 95
    for column in range(60, 600, 24):
        array[5:20, column : column + 14] = 245
        array[6:19, column + 1 : column + 13] = 25  # outline, like a real character
    return array


def _dialog(frame=None, *, context=SAMSUNG, **kwargs):
    from echo_personal_tool.presentation.dicom_export_dialog import DicomExportDialog, ExportSample

    path = Path("/tmp/ZHELNOVA_OLGA_27112025.dcm")
    return DicomExportDialog(
        None,
        files=12,
        target_dir=Path("/tmp/export"),
        sample=ExportSample(path=path, label=path.name),
        sample_frame=frame,
        context=context,
        frame_size=None if frame is None else (frame.shape[0], frame.shape[1]),
        **kwargs,
    )


def test_samsung_burned_in_defaults_to_variant_b(frame):
    dialog = _dialog(frame)
    assert dialog.mask_pixels is True  # variant B is preselected
    options = dialog.chosen_options()
    assert options.mask_pixels is True
    assert options.clean_quasi_identifiers is False
    assert options.clean_private_tags is False
    assert options.verify_pixels is False  # the detector is off unless asked


def test_defaults_come_from_the_profile_table(frame):
    """Philips has no burned-in band, so variant A is the safer default."""
    from echo_personal_tool.presentation.dicom_export_dialog import profile_recommends_pixel_masking

    recommended, reason = profile_recommends_pixel_masking(
        PhiMaskContext(vendor=Vendor.PHILIPS, panel_top=None, burned_in=None),
        frame.shape[0],
        frame.shape[1],
    )
    assert recommended is False and reason == "no-burned-in-band"


def test_burned_in_annotation_no_means_no_masking_default(frame):
    from echo_personal_tool.presentation.dicom_export_dialog import profile_recommends_pixel_masking

    recommended, reason = profile_recommends_pixel_masking(
        PhiMaskContext(vendor=Vendor.SAMSUNG, panel_top=100, burned_in="NO"),
        frame.shape[0],
        frame.shape[1],
    )
    assert recommended is False and reason == "burned-in-annotation-no"


def test_the_user_can_override_the_default(frame):
    dialog = _dialog(frame)
    dialog._tags_radio.setChecked(True)
    options = dialog.chosen_options()
    assert options.mask_pixels is False
    assert dialog.mask_pixels is False


def test_detector_flag_is_opt_in_and_feeds_the_verification(frame):
    dialog = _dialog(frame, text_detector=True)
    options = dialog.chosen_options()
    assert options.verify_pixels is True
    # The flag alone never changes the mask: variant B is still just the default.
    assert options.mask_pixels is True


def test_preview_plan_matches_the_viewer_geometry(frame):
    dialog = _dialog(frame)
    plan = dialog.plan_for_preview()
    tops = [rect for rect in plan.rects if rect.y0 == 0 and not rect.is_empty]
    assert tops
    assert max(rect.y1 for rect in tops) <= 100  # the calibration bar stays visible


def test_preview_shows_the_masked_frame_and_respects_variant_a(frame):
    from echo_personal_tool.presentation.dicom_export_dialog import masked_preview

    dialog = _dialog(frame)
    assert dialog._preview.pixmap() is not None and not dialog._preview.pixmap().isNull()

    masked = masked_preview(frame, Path("/tmp/ZHELNOVA_OLGA_27112025.dcm"))
    assert masked[:100].max() < 60  # the burned-in band is gone
    assert int(masked[200, 200]) == 95  # the panel is untouched

    dialog._tags_radio.setChecked(True)  # variant A: the preview shows the original
    assert dialog._preview.pixmap() is not None


def test_dialog_survives_a_frame_that_cannot_be_previewed():
    dialog = _dialog(None, context=PhiMaskContext())
    options = dialog.chosen_options()
    assert dialog.plan_for_preview() is not None  # no geometry, no bands, no crash
    assert options.mask_pixels in (True, False)  # a default exists either way


def test_evaluation_record_carries_geometry_and_no_identity(frame):
    """§9: the record is what the corpus evaluation is built on."""
    import re

    dialog = _dialog(frame, text_detector=True)
    record = dialog.evaluation_record()
    for field in (
        "vendor=Samsung",
        f"H={frame.shape[0]}",
        f"W={frame.shape[1]}",
        "has_regions=True",
        "min_panel_y=100",
        "detected_band=",
        "confidence=",
        "applied_band=",
        "profile_band=",
        "user_action=принял",
    ):
        assert field in record, field

    # Nothing that could identify the patient or the file may appear.
    assert "ZHELNOVA" not in record and "27112025" not in record and ".dcm" not in record
    assert re.search(r"\d{2}-\d{2}-\d{4}", record) is None


def test_user_action_tracks_the_deviation_from_the_default(frame):
    dialog = _dialog(frame)
    assert dialog.user_action() == "принял"

    dialog._tags_radio.setChecked(True)  # variant A over a class that needs B
    assert dialog.user_action() == "отключил"
    assert "applied_band=None" in dialog.evaluation_record()

    dialog = _dialog(frame, default_quasi=True)
    assert dialog.user_action() == "подвинул"  # same variant, extra cleanup


def test_evaluation_record_for_a_cancelled_dialog(frame):
    assert "user_action=отменил" in _dialog(frame).evaluation_record(accepted=False)


def test_every_status_string_this_dialog_shows_is_translated(frame):
    """Regression for missing i18n keys: the dialog renders its own labels."""
    from echo_personal_tool.domain.services.phi_text_detector import detect_text_rows
    from echo_personal_tool.presentation.dicom_export_dialog import detector_note

    dialog = _dialog(frame, text_detector=True)
    for label in (dialog._caption, dialog._reason_label, dialog._detector_label):
        assert label.text().strip()
        assert not label.text().startswith("export_dicom.")  # a translated string, not a key

    note = detector_note(detect_text_rows(frame), preserve_ui=False)
    assert note and not note.startswith("export_dicom.")
