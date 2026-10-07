"""Doppler acquisition mode, units by mode, and sign normalization (Э2).

CW reads in m/s, PW/TDI in cm/s; the mode is captured per marker from the
DICOM RegionDataType with an explicit manual override winning, storage stays
in cm/s. Velocities are normalized by magnitude at the compute boundary, so a
below-baseline TR jet still meets the > 280 cm/s criterion and the norm check.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.domain.calculations.diastology_grade import grade_diastolic_function
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.doppler_catalog import (
    FLOW_SITES,
    normalize_doppler_mode,
    scale_velocity_for_display,
    velocity_display_unit,
)
from echo_personal_tool.domain.models.doppler import (
    DopplerMeasurementDTO,
    DopplerPeakMarker,
    DopplerTrace,
)
from echo_personal_tool.domain.models.measurements import (
    DopplerFlowResult,
    DopplerResults,
    MeasurementSnapshot,
)
from echo_personal_tool.domain.services.measurement_results_formatter import (
    format_results_overlay,
    format_results_overlay_html,
)
from echo_personal_tool.infrastructure.measurement_codec import (
    FORMAT,
    SEMANTICS_VERSION,
    VERSION,
    MeasurementStorageError,
    dumps,
    loads,
)

_UTC = timezone.utc  # noqa: UP017 - retain Python 3.10 compatibility


def _peak(label: str, velocity_cm_s: float, *, mode: str = "", index: int = 0) -> DopplerPeakMarker:
    return DopplerPeakMarker(
        label=label,
        time_ms=10.0 * (index + 1),
        velocity_cm_s=velocity_cm_s,
        measurement_id=f"m{index}",
        mode=mode,
    )


def _dto(*peaks: DopplerPeakMarker, traces: tuple[DopplerTrace, ...] = ()) -> DopplerMeasurementDTO:
    return DopplerMeasurementDTO(peaks=tuple(peaks), intervals=(), traces=traces)


class TestNormalizeDopplerMode:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        (
            ("CW", "CW"),
            ("cw", "CW"),
            (" pw ", "PW"),
            ("TDI", "TDI"),
            ("TDI_PW", "TDI"),
            ("tdi_pw", "TDI"),
            ("", ""),
            (None, ""),
            ("spectral", ""),
            ("M-mode", ""),
        ),
    )
    def test_normalize(self, raw: str | None, expected: str) -> None:
        assert normalize_doppler_mode(raw) == expected


class TestVelocityDisplayPolicy:
    @pytest.mark.parametrize(
        ("mode", "velocity_cm_s", "expected_unit"),
        (
            ("CW", 45.0, "m/s"),
            ("CW", 420.0, "m/s"),
            ("CW", -312.0, "m/s"),
            ("PW", 420.0, "cm/s"),
            ("PW", 45.0, "cm/s"),
            ("TDI", 14.0, "cm/s"),
            ("", 95.0, "cm/s"),
            ("", 99.9, "cm/s"),
            ("", 100.0, "m/s"),
            ("", 420.0, "m/s"),
            ("", -150.0, "m/s"),
            ("", -90.0, "cm/s"),
        ),
    )
    def test_unit(self, mode: str, velocity_cm_s: float, expected_unit: str) -> None:
        assert velocity_display_unit(mode, velocity_cm_s) == expected_unit

    def test_unknown_mode_without_a_value_defaults_to_cm_s(self) -> None:
        assert velocity_display_unit("") == "cm/s"
        assert velocity_display_unit(None) == "cm/s"

    @pytest.mark.parametrize(
        ("velocity_cm_s", "mode", "expected"),
        (
            (312.0, "CW", (3.12, "m/s", 2)),
            (45.0, "CW", (0.45, "m/s", 2)),
            (72.4, "PW", (72.4, "cm/s", 1)),
            (14.0, "TDI", (14.0, "cm/s", 1)),
            (95.0, "", (95.0, "cm/s", 1)),
            (420.0, "", (4.2, "m/s", 2)),
        ),
    )
    def test_scale(self, velocity_cm_s: float, mode: str, expected: tuple[float, str, int]) -> None:
        assert scale_velocity_for_display(velocity_cm_s, mode) == expected


class TestSpectralDopplerMode:
    def test_reads_the_spectral_region(self) -> None:
        from echo_personal_tool.domain.models.properties_snapshot import (
            PropertiesSnapshot,
            RegionSummary,
        )
        from echo_personal_tool.infrastructure.properties_extractor import spectral_doppler_mode

        bmode = RegionSummary(0, "B-mode", None, (0, 100, 0, 100), None, None, None, None, None)
        spectral = RegionSummary(1, "Spectral", "CW", (0, 100, 100, 200), None, None, None, None, None)
        snapshot = PropertiesSnapshot.default()
        snapshot = PropertiesSnapshot(**{**snapshot.__dict__, "regions": (bmode, spectral)})
        assert spectral_doppler_mode(snapshot) == "CW"

    def test_no_spectral_region_reads_none(self) -> None:
        from echo_personal_tool.domain.models.properties_snapshot import PropertiesSnapshot
        from echo_personal_tool.infrastructure.properties_extractor import spectral_doppler_mode

        assert spectral_doppler_mode(PropertiesSnapshot.default()) is None


class TestSiteModeResolution:
    @pytest.mark.parametrize("site", FLOW_SITES)
    def test_newest_peak_mode_wins(self, site: str) -> None:
        dto = _dto(
            _peak(f"{site} Vmax", 200.0, mode="PW", index=0),
            _peak(f"{site} Vmax", 210.0, mode="CW", index=1),
        )
        assert compute(dto).flow(site).mode == "CW"

    def test_unknown_mode_markers_resolve_to_empty(self) -> None:
        dto = _dto(_peak("TR Vmax", 280.0))
        assert compute(dto).flow("TR").mode == ""

    def test_trace_mode_feeds_the_vmax_fallback(self) -> None:
        trace = DopplerTrace(
            label="AV VTI",
            points=((0.0, 0.0), (100.0, 300.0), (200.0, 0.0)),
            measurement_id="t0",
            mode="CW",
        )
        flow = compute(_dto(traces=(trace,))).flow("AV")
        assert flow is not None
        assert flow.vmax_cm_s == pytest.approx(300.0)
        assert flow.mode == "CW"

    def test_peak_mode_wins_over_trace_mode(self) -> None:
        trace = DopplerTrace(
            label="TR VTI",
            points=((0.0, 0.0), (100.0, 300.0), (200.0, 0.0)),
            measurement_id="t0",
            mode="PW",
        )
        dto = _dto(_peak("TR Vmax", 290.0, mode="CW"), traces=(trace,))
        assert compute(dto).flow("TR").mode == "CW"


class TestSignNormalization:
    def test_tissue_peaks_read_by_magnitude(self) -> None:
        dto = _dto(
            _peak("E", -90.0, index=0),
            _peak("A", -60.0, index=1),
            _peak("e_sept", -8.0, index=2),
            _peak("s_prime_rv", -12.0, index=3),
        )
        result = compute(dto)
        assert result.e_cm_s == pytest.approx(90.0)
        assert result.a_cm_s == pytest.approx(60.0)
        assert result.e_a_ratio == pytest.approx(1.5)
        assert result.e_prime_sept_cm_s == pytest.approx(8.0)
        assert result.s_prime_rv_cm_s == pytest.approx(12.0)

    def test_negative_tr_jet_reads_positive(self) -> None:
        dto = _dto(_peak("TR Vmax", -312.0, mode="CW"))
        result = compute(dto)
        assert result.tr_vmax_cm_s == pytest.approx(312.0)
        flow = result.flow("TR")
        assert flow.vmax_cm_s == pytest.approx(312.0)
        assert flow.pgmax_mmhg == pytest.approx(4.0 * 3.12**2)

    def test_diastology_criterion_meets_on_negative_tr(self) -> None:
        assert (
            grade_diastolic_function(
                e_over_e_prime=15.0,
                lav_index_ml_m2=40.0,
                tr_vmax_cm_s=-312.0,
            )
            == "Abnormal"
        )

    def test_diastology_e_prime_compared_by_magnitude(self) -> None:
        abnormal = grade_diastolic_function(
            e_over_e_prime=15.0,
            lav_index_ml_m2=40.0,
            tr_vmax_cm_s=200.0,
            e_prime_sept_cm_s=-5.0,
        )
        normal = grade_diastolic_function(
            e_over_e_prime=8.0,
            lav_index_ml_m2=28.0,
            tr_vmax_cm_s=200.0,
            e_prime_sept_cm_s=8.0,
        )
        assert abnormal == "Abnormal"
        assert normal == "Normal"


class TestBernoulliEtalonsByMode:
    @pytest.mark.parametrize(
        ("site", "velocity_cm_s", "expected_pgmax"),
        (
            ("TR", 280.0, 31),
            ("TR", 400.0, 64),
            ("AV", 280.0, 31),
            ("AV", 400.0, 64),
            ("MV", 280.0, 31),
        ),
    )
    def test_pgmax_etalon(self, site: str, velocity_cm_s: float, expected_pgmax: int) -> None:
        dto = _dto(_peak(f"{site} Vmax", velocity_cm_s, mode="CW"))
        flow = compute(dto).flow(site)
        assert round(flow.pgmax_mmhg) == expected_pgmax


class TestOverlayUnits:
    def _snapshot(self, *flows: DopplerFlowResult) -> MeasurementSnapshot:
        return MeasurementSnapshot(doppler=DopplerResults(flow_results=flows))

    def test_text_overlay_uses_mode_units(self) -> None:
        snapshot = self._snapshot(
            DopplerFlowResult(site="TR", vmax_cm_s=312.0, pgmax_mmhg=38.9, mode="CW"),
            DopplerFlowResult(site="LVOT", vmax_cm_s=95.0, vmean_cm_s=60.0, mode="PW"),
            DopplerFlowResult(site="AV", vmax_cm_s=420.0, pgmax_mmhg=70.6),
        )
        text = format_results_overlay(snapshot, time_calibrated=True)
        assert "TR Vmax: 3.12 m/s" in text
        assert "LVOT Vmax: 95.0 cm/s" in text
        assert "LVOT Vmean: 60.0 cm/s" in text
        assert "AV Vmax: 4.20 m/s" in text

    @staticmethod
    def _tr_line(html: str) -> str:
        (line,) = [line for line in html.split("<br>") if "TR Vmax" in line]
        return line

    def test_html_overlay_colors_tr_against_the_m_s_norm(self) -> None:
        normal = self._snapshot(DopplerFlowResult(site="TR", vmax_cm_s=250.0, mode="CW"))
        abnormal = self._snapshot(DopplerFlowResult(site="TR", vmax_cm_s=350.0, mode="CW"))
        normal_line = self._tr_line(format_results_overlay_html(normal))
        abnormal_line = self._tr_line(format_results_overlay_html(abnormal))
        assert ">2.50</span>" in normal_line
        assert "m/s" in normal_line
        assert ">3.50</span>" in abnormal_line
        # The tr_vmax norm is ≤2.8 m/s: only the fast jet reads red.
        assert "#ff6b6b" not in normal_line
        assert "#ff6b6b" in abnormal_line

    def test_html_overlay_compares_cm_s_display_in_m_s(self) -> None:
        # A PW override shows TR in cm/s; the norm is still applied in m/s,
        # so 250 cm/s reads normal instead of always-red.
        snapshot = self._snapshot(DopplerFlowResult(site="TR", vmax_cm_s=250.0, mode="PW"))
        line = self._tr_line(format_results_overlay_html(snapshot))
        assert ">250.0</span>" in line
        assert "cm/s" in line
        assert "#ff6b6b" not in line


class TestTraceSummaryUnits:
    def test_summary_follows_the_site_mode(self) -> None:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        metrics = compute(
            _dto(
                _peak("TR Vmax", 312.0, mode="CW"),
                _peak("LVOT Vmax", 95.0, mode="PW"),
            )
        )
        tr_summary = ViewerWidget._doppler_trace_summary(metrics, "TR VTI")
        lvot_summary = ViewerWidget._doppler_trace_summary(metrics, "LVOT VTI")
        assert "TR Vmax: 3.12 m/s" in tr_summary
        assert "LVOT Vmax: 95.0 cm/s" in lvot_summary


_SOP = "1.2.3.4"
_SOURCES = {_SOP: {"fingerprint": "a" * 64, "frames": 5, "spacing": [0.5, 0.6]}}


def _record(data: StudyMeasurementData) -> dict:
    return dict(
        format=FORMAT,
        schema_version=VERSION,
        measurement_semantics_version=SEMANTICS_VERSION,
        study_uid="1.2.3",
        revision=1,
        saved_at=datetime.now(_UTC).isoformat(),
        sources=_SOURCES,
        data=data,
    )


class TestCodecMode:
    def test_mode_round_trip(self) -> None:
        dto = DopplerMeasurementDTO(
            peaks=(_peak("TR Vmax", 280.0, mode="CW"),),
            intervals=(),
            traces=(
                DopplerTrace(
                    label="TR VTI",
                    points=((0.0, 0.0), (100.0, 200.0)),
                    measurement_id="t0",
                    mode="CW",
                ),
            ),
        )
        data = StudyMeasurementData(doppler_by_instance=((_SOP, dto),))
        loaded = loads(dumps(_record(data)))
        assert loaded["data"].doppler_by_instance[0][1].peaks[0].mode == "CW"
        assert loaded["data"].doppler_by_instance[0][1].traces[0].mode == "CW"

    def test_unknown_mode_rejected(self) -> None:
        dto = _dto(_peak("TR Vmax", 280.0, mode="M-mode"))
        with pytest.raises(MeasurementStorageError):
            dumps(_record(StudyMeasurementData(doppler_by_instance=((_SOP, dto),))))

    def test_documents_without_mode_keep_loading(self) -> None:
        import json

        dto = DopplerMeasurementDTO(
            peaks=(DopplerPeakMarker(label="TR Vmax", time_ms=10.0, velocity_cm_s=280.0),),
            intervals=(),
            traces=(),
        )
        wire = json.loads(dumps(_record(StudyMeasurementData(doppler_by_instance=((_SOP, dto),)))))
        del wire["data"]["doppler_by_instance"][0][1]["peaks"][0]["mode"]
        loaded = loads(json.dumps(wire).encode())
        assert loaded["data"].doppler_by_instance[0][1].peaks[0].mode == ""


@pytest.mark.gui
class TestPeakMarkerCaptions:
    @pytest.fixture(autouse=True)
    def _qapp(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    @pytest.fixture()
    def overlay(self):
        from unittest.mock import MagicMock

        from echo_personal_tool.presentation.doppler_overlay import DopplerOverlayTools

        plot = MagicMock()
        plot.items = []
        plot.addItem = lambda item: plot.items.append(item)
        plot.removeItem = MagicMock()
        return DopplerOverlayTools(plot)

    def test_flow_caption_has_pgmax(self) -> None:
        from echo_personal_tool.presentation.doppler_overlay import peak_marker_caption

        assert peak_marker_caption(_peak("TR Vmax", 312.0, mode="CW")) == "TR Vmax 3.12 m/s · PGmax 39 mmHg"

    def test_tissue_caption_has_no_pg(self) -> None:
        from echo_personal_tool.presentation.doppler_overlay import peak_marker_caption

        assert peak_marker_caption(_peak("E", 90.0, mode="PW")) == "E 90.0 cm/s"
        assert peak_marker_caption(_peak("e_sept", 8.0)) == "e_sept 8.0 cm/s"

    def test_caption_uses_magnitude_and_own_mode(self) -> None:
        from echo_personal_tool.presentation.doppler_overlay import peak_marker_caption

        assert peak_marker_caption(_peak("TR Vmax", -280.0, mode="CW")) == "TR Vmax 2.80 m/s · PGmax 31 mmHg"
        assert peak_marker_caption(_peak("LVOT Vmax", 95.0, mode="PW")) == "LVOT Vmax 95.0 cm/s · PGmax 4 mmHg"
        assert peak_marker_caption(_peak("AV Vmax", 420.0)) == "AV Vmax 4.20 m/s · PGmax 71 mmHg"

    def test_legacy_label_still_resolves_a_flow_site(self) -> None:
        from echo_personal_tool.presentation.doppler_overlay import peak_marker_caption

        assert "PGmax" in peak_marker_caption(_peak("TRpeak", 300.0, mode="CW"))

    def test_overlay_builds_one_caption_per_marker(self, overlay) -> None:
        overlay.set_doppler_mode("CW")
        overlay.set_peak_label("TR Vmax")
        overlay._add_peak_marker(100.0, 312.0)
        # Each marker keeps the mode resolved at its own placement time.
        overlay.set_doppler_mode("PW")
        overlay.set_peak_label("E")
        overlay._add_peak_marker(200.0, 90.0)
        assert [item.toPlainText() for item in overlay._peak_label_items] == [
            "TR Vmax 3.12 m/s · PGmax 39 mmHg",
            "E 90.0 cm/s",
        ]

    def test_overlay_clear_removes_captions(self, overlay) -> None:
        overlay.set_peak_label("TR Vmax")
        overlay._add_peak_marker(100.0, 312.0)
        (caption,) = overlay._peak_label_items
        overlay.clear_measurements()
        assert overlay._peak_label_items == []
        overlay._plot.removeItem.assert_any_call(caption)


class TestDopplerCaliperGradient:
    def test_report_rows_carry_mode_units_and_pgmax(self) -> None:
        from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
        from echo_personal_tool.domain.services.report_builder import GROUP_OTHER, build_report_groups

        snapshot = MeasurementSnapshot(
            linear_measurements=(
                LinearMeasurement(
                    label="Dist1",
                    pixel_length=10.0,
                    millimeter_length=None,
                    time_ms=100.0,
                    velocity_cm_s=312.0,
                    doppler=True,
                    doppler_mode="CW",
                ),
            )
        )
        rows = {
            value.label: (value.value, value.unit)
            for group in build_report_groups(snapshot)
            for value in group.values
            if group.key == GROUP_OTHER
        }
        assert rows["Dist1 Δt"] == ("100.0", "ms")
        assert rows["Dist1 ΔV"] == ("3.12", "m/s")
        assert rows["Dist1 PGmax"] == ("39", "mmHg")

    def test_codec_round_trip_keeps_doppler_mode(self) -> None:
        from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

        data = StudyMeasurementData(
            linear_measurements=(
                LinearMeasurement(
                    label="Dist1",
                    pixel_length=10.0,
                    millimeter_length=None,
                    frame_index=0,
                    sop_instance_uid=_SOP,
                    time_ms=100.0,
                    velocity_cm_s=312.0,
                    doppler=True,
                    doppler_mode="CW",
                ),
            )
        )
        loaded = loads(dumps(_record(data)))
        assert loaded["data"].linear_measurements[0].doppler_mode == "CW"

    def test_codec_rejects_unknown_doppler_mode(self) -> None:
        from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

        data = StudyMeasurementData(
            linear_measurements=(
                LinearMeasurement(
                    label="Dist1",
                    pixel_length=10.0,
                    millimeter_length=None,
                    frame_index=0,
                    sop_instance_uid=_SOP,
                    velocity_cm_s=100.0,
                    doppler=True,
                    doppler_mode="M-mode",
                ),
            )
        )
        with pytest.raises(MeasurementStorageError):
            dumps(_record(data))

    def test_codec_reads_documents_without_doppler_mode(self) -> None:
        import json

        from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement

        data = StudyMeasurementData(
            linear_measurements=(
                LinearMeasurement(
                    label="Dist1",
                    pixel_length=10.0,
                    millimeter_length=None,
                    frame_index=0,
                    sop_instance_uid=_SOP,
                    velocity_cm_s=100.0,
                    doppler=True,
                ),
            )
        )
        wire = json.loads(dumps(_record(data)))
        del wire["data"]["linear_measurements"][0]["doppler_mode"]
        loaded = loads(json.dumps(wire).encode())
        assert loaded["data"].linear_measurements[0].doppler_mode == ""


@pytest.mark.gui
class TestOverlayModeStamping:
    @pytest.fixture(autouse=True)
    def _qapp(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    @pytest.fixture()
    def overlay(self):
        from unittest.mock import MagicMock

        from echo_personal_tool.presentation.doppler_overlay import DopplerOverlayTools

        plot = MagicMock()
        plot.items = []
        plot.addItem = lambda item: plot.items.append(item)
        plot.removeItem = MagicMock()
        return DopplerOverlayTools(plot)

    def test_peak_captures_current_mode(self, overlay) -> None:
        overlay.set_doppler_mode("CW")
        overlay.set_peak_label("TR Vmax")
        overlay._add_peak_marker(100.0, 280.0)
        (marker,) = overlay.get_measurement_dto().peaks
        assert marker.mode == "CW"
        assert marker.label == "TR Vmax"

    def test_changing_mode_does_not_rewrite_committed_markers(self, overlay) -> None:
        overlay.set_doppler_mode("CW")
        overlay.set_peak_label("TR Vmax")
        overlay._add_peak_marker(100.0, 280.0)
        overlay.set_doppler_mode("PW")
        overlay.set_peak_label("LVOT Vmax")
        overlay._add_peak_marker(200.0, 95.0)
        modes = {marker.label: marker.mode for marker in overlay.get_measurement_dto().peaks}
        assert modes == {"TR Vmax": "CW", "LVOT Vmax": "PW"}

    def test_drag_keeps_the_captured_mode(self, overlay) -> None:
        overlay.set_doppler_mode("CW")
        overlay.set_peak_label("TR Vmax")
        overlay._add_peak_marker(100.0, 280.0)
        overlay._peak_drag_index = 0
        mapping = overlay.axis_mapping()
        assert overlay.move_peak_drag(mapping.x_from_time_ms(150.0), mapping.y_from_velocity_cm_s(300.0))
        (marker,) = overlay.get_measurement_dto().peaks
        assert marker.mode == "CW"
        assert marker.velocity_cm_s == pytest.approx(300.0)

    def test_unknown_mode_by_default(self, overlay) -> None:
        assert overlay.doppler_mode() == ""
        overlay.set_peak_label("TR Vmax")
        overlay._add_peak_marker(100.0, 280.0)
        (marker,) = overlay.get_measurement_dto().peaks
        assert marker.mode == ""


@pytest.mark.gui
class TestViewerModeResolution:
    @pytest.fixture(autouse=True)
    def _qapp(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    def test_override_wins_over_dicom(self) -> None:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        try:
            viewer.set_dicom_doppler_mode("PW")
            assert viewer._doppler.doppler_mode() == "PW"
            viewer.set_doppler_mode_override("CW")
            assert viewer._doppler.doppler_mode() == "CW"
            viewer.reset_doppler_mode_override()
            assert viewer._doppler.doppler_mode() == "PW"
            viewer.set_dicom_doppler_mode(None)
            assert viewer._doppler.doppler_mode() == ""
        finally:
            viewer.deleteLater()

    def test_tdi_pw_folds_into_tdi(self) -> None:
        from echo_personal_tool.presentation.viewer_widget import ViewerWidget

        viewer = ViewerWidget()
        try:
            viewer.set_dicom_doppler_mode("TDI_PW")
            assert viewer._doppler.doppler_mode() == "TDI"
        finally:
            viewer.deleteLater()


@pytest.mark.gui
class TestMenuModeControl:
    @pytest.fixture(autouse=True)
    def _qapp(self):
        from PySide6.QtWidgets import QApplication

        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        yield app

    def test_combo_emits_and_resets(self) -> None:
        from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget

        menu = MeasuresMenuWidget()
        try:
            emitted: list[str] = []
            menu.doppler_mode_changed.connect(emitted.append)
            assert menu.doppler_mode_override() == ""
            menu._doppler_mode_combo.setCurrentIndex(1)  # CW
            assert emitted == ["CW"]
            assert menu.doppler_mode_override() == "CW"
            menu.reset_doppler_mode()
            assert emitted == ["CW", ""]
            assert menu.doppler_mode_override() == ""
        finally:
            menu.deleteLater()

    def test_selection_survives_rebuild(self) -> None:
        from echo_personal_tool.presentation.measures_menu import MeasuresMenuWidget

        menu = MeasuresMenuWidget()
        try:
            menu._doppler_mode_combo.setCurrentIndex(3)  # TDI
            menu.rebuild_with_preferences(None)
            assert menu.doppler_mode_override() == "TDI"
            assert menu._doppler_mode_combo.currentData() == "TDI"
        finally:
            menu.deleteLater()
