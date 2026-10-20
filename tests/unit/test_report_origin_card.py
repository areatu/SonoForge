"""GUI tests for the «откуда значение» card (UI-4 PR-4, spec §4.6).

The card is the screen side of the provenance contract: it shows the method,
the source clip with its frame, the measurement identity and the inputs of a
calculator output, and it says «происхождение не записано» where nothing was
recorded.  Its only action jumps back to the images on the recorded frame.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.gui

UID = "1.2.840.113619.2.55.3.1234567890.77"


@pytest.fixture(autouse=True)
def _setup_qapp():
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture(autouse=True)
def _english():
    from echo_personal_tool.infrastructure.i18n import set_language

    set_language("en")
    yield
    set_language("en")


def _caliper_row():
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_groups

    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=120.0,
        millimeter_length=48.0,
        frame_index=7,
        sop_instance_uid=UID,
        measurement_id="m-0001",
        revision=3,
    )
    groups = build_report_groups(MeasurementSnapshot(linear_measurements=(measurement,)))
    return next(value for group in groups for value in group.values if value.origin is not None)


def _card():
    from echo_personal_tool.presentation.report_mode.provenance import ReportValueCard

    return ReportValueCard()


def _labels(card, name: str):
    from PySide6.QtWidgets import QLabel

    return [label for label in card.findChildren(QLabel) if label.objectName() == name]


def test_the_card_shows_the_method_clip_and_frame() -> None:
    card = _card()
    card.show_value(_caliper_row())

    assert card.isVisible() is True
    assert "LVIDd" in _labels(card, "reportValueCardTitle")[0].text()
    assert "48" in _labels(card, "reportValueCardTitle")[0].text()
    assert "Linear caliper" in _labels(card, "reportValueCardMethod")[0].text()
    sources = _labels(card, "reportValueCardSource")
    assert len(sources) == 1
    assert "frame 8" in sources[0].text()  # frame_index is zero-based on disk


def test_the_clip_is_named_the_way_the_gallery_names_it() -> None:
    card = _card()
    card.set_clip_label_provider(lambda uid: "clip_01.dcm" if uid == UID else "")
    card.show_value(_caliper_row())

    assert "clip_01.dcm" in _labels(card, "reportValueCardSource")[0].text()


def test_a_clip_without_a_name_falls_back_to_the_uid_tail() -> None:
    card = _card()
    card.show_value(_caliper_row())

    text = _labels(card, "reportValueCardSource")[0].text()
    assert UID[-8:] in text


def test_the_measurement_identity_is_shown() -> None:
    card = _card()
    card.show_value(_caliper_row())

    identity = _labels(card, "reportValueCardIdentity")[0]
    assert identity.isVisible() is True
    assert "m-0001" in identity.text()
    assert "revision 3" in identity.text()


def test_open_frames_emits_the_recorded_clip_and_frame() -> None:
    card = _card()
    card.show_value(_caliper_row())
    seen: list[tuple[str, int]] = []
    card.open_frames_requested.connect(lambda uid, frame: seen.append((uid, frame)))

    card.open_button.click()

    assert seen == [(UID, 7)]
    assert card.open_button.isVisible() is True


def test_a_value_without_origin_says_so_and_offers_no_jump() -> None:
    from echo_personal_tool.domain.services.report_builder import ReportValue

    card = _card()
    card.show_value(ReportValue(label="EF", value="62", unit="%"))

    assert _labels(card, "reportValueCardMethod")[0].text() == ""
    assert card.open_button.isVisible() is False
    status = _labels(card, "reportValueCardStatus")[0]
    assert status.text() == "Provenance not recorded"
    assert status.property("recorded") is False


def test_a_calculator_output_lists_its_inputs_and_sources() -> None:
    from echo_personal_tool.application.calculator_inputs import resolve_standalone_inputs
    from echo_personal_tool.domain.calculators import evaluate
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_groups

    values = {"lvot_d": 2.0, "lvot_vti": 20.0, "av_vti": 100.0, "hr": 70.0, "bsa": 1.9}
    snapshot = MeasurementSnapshot(calculations=evaluate(resolve_standalone_inputs(values)))
    row = next(
        value
        for group in build_report_groups(snapshot)
        for value in group.values
        if value.label == "SV"
    )

    card = _card()
    card.show_value(row)

    assert "Calculator" in _labels(card, "reportValueCardMethod")[0].text()
    inputs = [label.text() for label in _labels(card, "reportValueCardInput")]
    assert any("LVOTd" in text and "measured" in text or "manual" in text for text in inputs)
    assert any("LVOT VTI" in text for text in inputs)
    assert card.open_button.isVisible() is False


def test_an_unrecorded_origin_is_not_presented_as_fresh() -> None:
    from echo_personal_tool.domain.models.value_origin import unrecorded_origin
    from echo_personal_tool.domain.services.report_builder import ReportValue

    card = _card()
    card.show_value(ReportValue(label="GLS", value="-18", unit="%", origin=unrecorded_origin("strain")))

    status = _labels(card, "reportValueCardStatus")[0]
    assert status.text() == "Provenance not recorded"
    assert status.property("recorded") is False


def test_the_card_is_hidden_until_a_value_is_shown() -> None:
    card = _card()
    assert card.isVisible() is False
    assert card.value is None


# ── the preview hosts the card ────────────────────────────────────────


def _preview(qtbot):
    from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.services.report_builder import build_report_document
    from echo_personal_tool.presentation.report_mode.preview import ReportPreview

    measurement = LinearMeasurement(
        label="LVEDD",
        pixel_length=120.0,
        millimeter_length=48.0,
        frame_index=7,
        sop_instance_uid=UID,
        measurement_id="m-0001",
    )
    document = build_report_document(MeasurementSnapshot(linear_measurements=(measurement,)), None)
    preview = ReportPreview(lambda: document)
    qtbot.addWidget(preview)
    preview.resize(900, 700)
    preview.show()
    qtbot.waitExposed(preview)
    preview.refresh_now()
    return preview


def test_hovering_a_value_opens_the_card_of_that_value(qtbot, monkeypatch) -> None:
    from PySide6.QtCore import QPoint

    preview = _preview(qtbot)
    monkeypatch.setattr(preview, "value_at", lambda x, y: (0, 0))

    preview._on_hover(QPoint(120, 140))

    assert preview.hovered_value is not None
    assert preview.hovered_value.origin is not None
    assert preview.hovered_value.origin.clips[0].frame_index == 7
    assert preview.card.isVisible() is True


def test_a_gap_between_cells_hides_the_card(qtbot, monkeypatch) -> None:
    from PySide6.QtCore import QPoint

    preview = _preview(qtbot)
    monkeypatch.setattr(preview, "value_at", lambda x, y: (0, 0))
    preview._on_hover(QPoint(120, 140))
    assert preview.card.isVisible() is True

    monkeypatch.setattr(preview, "value_at", lambda x, y: None)
    preview._on_hover(QPoint(5, 5))

    assert preview.card.isVisible() is False
    assert preview.hovered_value is None


def test_the_card_jump_is_forwarded_out_of_the_preview(qtbot, monkeypatch) -> None:
    from PySide6.QtCore import QPoint

    preview = _preview(qtbot)
    monkeypatch.setattr(preview, "value_at", lambda x, y: (0, 0))
    seen: list[tuple[str, int]] = []
    preview.open_frames_requested.connect(lambda uid, frame: seen.append((uid, frame)))

    preview._on_hover(QPoint(120, 140))
    preview.card.open_button.click()

    assert seen == [(UID, 7)]


def test_value_record_maps_an_anchor_to_the_document_row(qtbot) -> None:
    preview = _preview(qtbot)

    row = preview.value_record((0, 0))

    assert row is not None
    assert row.label
    assert preview.value_record((99, 99)) is None
    assert preview.value_record(None) is None
