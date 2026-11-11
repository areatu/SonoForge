"""Contract and ratchet tests for unified measurement formatting (issue 482).

Verifies that:
1. ``format_measurement(measurement_id, value, unit)`` formats every catalog
   entry using ``MeasurementSpec.decimals_for(unit)`` in a single rounding step
   with no ``-0`` / ``-0.0`` artefacts.
2. Tool-panel status, plain-text overlay, HTML overlay, structured
   ``ReportDocument``/text report, and exported PDF render identical numeric
   strings for every measurement family.
3. Mutating ``MeasurementSpec.decimals`` in ``MEASUREMENTS`` immediately
   propagates the new precision across all four surfaces without changing any
   formatter code.
4. Formatter/report/status modules contain zero literal ``decimals=<int>``
   overrides, and both plain-text and HTML overlays render from
   ``build_overlay_rows``.
5. Technical UI display helpers in ``presentation.display_formats`` cover all
   non-measurement formatting contracts.
"""

from __future__ import annotations

import ast
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pymupdf
import pytest

from echo_personal_tool.application.report_export import render_report
from echo_personal_tool.application.tool_status import ToolStatusProvider
from echo_personal_tool.domain.doppler_catalog import format_velocity_measurement
from echo_personal_tool.domain.measurement_catalog import (
    MEASUREMENTS,
    format_measurement,
)
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.models.measurements import (
    ChamberSimpsonResult,
    DopplerFlowResult,
    DopplerResults,
    IndexedMeasurements,
    LvefResult,
    LvViewMetrics,
    MeasurementSnapshot,
    StrainReport,
    TeichholzResult,
)
from echo_personal_tool.domain.models.vessel_measurement import VesselMeasurement
from echo_personal_tool.domain.protocols import ProjectionValue, StudyProjection
from echo_personal_tool.domain.services.measurement_results_formatter import (
    format_results_overlay,
    format_results_overlay_html,
)
from echo_personal_tool.domain.services.report_builder import (
    PatientInfo,
    ReportDocument,
    build_report_document,
)
from echo_personal_tool.presentation import display_formats

SRC_ROOT = Path(__file__).resolve().parents[2] / "src" / "echo_personal_tool"


@contextmanager
def _override_catalog_decimals(measurement_id: str, new_decimals: int) -> Iterator[None]:
    spec = MEASUREMENTS[measurement_id]
    original = spec.decimals
    object.__setattr__(spec, "decimals", new_decimals)
    try:
        yield
    finally:
        object.__setattr__(spec, "decimals", original)


def _doc_and_pdf_text(snapshot: MeasurementSnapshot, *, length_unit: str) -> tuple[ReportDocument, set[str], str]:
    document = build_report_document(
        snapshot,
        patient=PatientInfo(sex="M", height_cm=180.0, weight_kg=82.0, bsa_m2=1.924),
        length_display_unit=length_unit,
    )
    doc_values = {v.value for group in document.groups for v in group.values}
    rendered = render_report(document)
    with pymupdf.open(stream=rendered.pdf, filetype="pdf") as pdf_doc:
        pdf_text = "\n".join(page.get_text() for page in pdf_doc)
    return document, doc_values, pdf_text


class TestCatalogFormatMeasurement:
    @pytest.mark.parametrize("measurement_id", sorted(MEASUREMENTS))
    def test_every_catalog_entry_formats_to_spec_decimals(self, measurement_id: str) -> None:
        spec = MEASUREMENTS[measurement_id]
        unit = spec.unit()
        expected_decimals = spec.decimals_for(unit)
        rendered = format_measurement(measurement_id, 12.3456, unit)
        if expected_decimals == 0:
            assert "." not in rendered
            assert rendered == "12"
        else:
            whole, frac = rendered.split(".")
            assert whole == "12"
            assert len(frac) == expected_decimals

    @pytest.mark.parametrize("measurement_id", sorted(MEASUREMENTS))
    def test_negative_zero_never_appears(self, measurement_id: str) -> None:
        spec = MEASUREMENTS[measurement_id]
        rendered = format_measurement(measurement_id, -1e-9, spec.unit())
        assert not rendered.startswith("-")

    @pytest.mark.parametrize(
        ("measurement_id", "unit", "raw_value", "expected"),
        [
            # 12.449 rounded in one step to 1 decimal -> "12.4" (double-rounding via 2 decimals would give "12.5").
            ("caliper.length", "cm", 12.449, "12.4"),
            ("caliper.length", "mm", 12.49, "12"),
            ("caliper.length", "mm", 12.51, "13"),
            ("tr.vmax", "m/s", 3.149, "3.1"),
            ("tr.vmax", "m/s", 3.151, "3.2"),
            ("tr.vmax", "cm/s", 314.9, "315"),
            ("lv.rwt", "", 0.4249, "0.42"),
            ("lv.rwt", "", 0.4251, "0.43"),
            ("patient.bsa", "m²", 1.8449, "1.84"),
            ("patient.bsa", "m²", 1.8451, "1.85"),
        ],
    )
    def test_single_step_rounding_without_double_rounding(
        self,
        measurement_id: str,
        unit: str,
        raw_value: float,
        expected: str,
    ) -> None:
        assert format_measurement(measurement_id, raw_value, unit) == expected

    def test_length_and_velocity_unit_overrides_shift_decimals(self) -> None:
        assert format_measurement("lv.ivsd", 11.4, "mm") == "11"
        assert format_measurement("lv.ivsd", 1.14, "cm") == "1.1"
        assert format_measurement("lv.ivsd", 114.4, "px") == "114"
        assert format_measurement("caliper.pixel", 114.4, "px") == "114.4"
        assert format_velocity_measurement("tr.vmax", 312.0, "CW") == ("3.1", "m/s")
        assert format_velocity_measurement("tr.vmax", 250.0, "PW") == ("250", "cm/s")
        assert format_velocity_measurement("doppler.vmax", 312.0, "CW") == ("3.12", "m/s")
        assert format_velocity_measurement("doppler.vmax", 95.4, "PW") == ("95.4", "cm/s")


def _rich_snapshot_and_projection() -> tuple[MeasurementSnapshot, StudyProjection]:
    linear = (
        LinearMeasurement(label="IVSd", pixel_length=40.0, millimeter_length=12.4),
        LinearMeasurement(label="LVEDD", pixel_length=160.0, millimeter_length=62.4),
        LinearMeasurement(label="LVPWd", pixel_length=38.0, millimeter_length=11.4),
    )
    snapshot = MeasurementSnapshot(
        spacing_calibrated=True,
        lvef=LvefResult(
            a4c=LvViewMetrics(edv_ml=148.4, esv_ml=68.6),
            a2c=LvViewMetrics(edv_ml=152.2, esv_ml=70.4),
            edv_bi_ml=150.3,
            esv_bi_ml=69.5,
            lvef_percent=53.8,
            method="simpson_biplan",
        ),
        teichholz=TeichholzResult(edv_ml=169.4, esv_ml=65.6, lvef_percent=61.3),
        lvm_g=248.6,
        rwt=0.406,
        la_simpson=ChamberSimpsonResult(
            chamber="LA",
            a4c=LvViewMetrics(esv_ml=74.6),
            a2c=LvViewMetrics(esv_ml=78.2),
            area_cm2=24.36,
        ),
        ra_simpson=ChamberSimpsonResult(
            chamber="RA",
            a4c=LvViewMetrics(esv_ml=62.4),
            area_cm2=19.84,
        ),
        rv_fac_percent=39.6,
        indexed=IndexedMeasurements(
            bsa_m2=1.924,
            simpson_edvi_ml_m2=78.1,
            simpson_esvi_ml_m2=36.1,
            lav_bi_index_ml_m2=39.74,
            rav_index_ml_m2=32.4,
            lvmi_g_m2=135.4,
            linear_index_mm_m2=(("LVEDD", 62.4 / 1.924),),
        ),
        doppler=DopplerResults(
            e_cm_s=88.4,
            a_cm_s=62.6,
            e_a_ratio=1.41,
            e_prime_sept_cm_s=7.44,
            e_over_e_prime=11.9,
            tr_vmax_cm_s=314.0,
            flow_results=(
                DopplerFlowResult(site="TR", vmax_cm_s=314.0, pgmax_mmhg=39.4, mode="CW"),
                DopplerFlowResult(site="LVOT", vmax_cm_s=96.4, vti_cm=21.4, mode="PW"),
            ),
        ),
        strain=StrainReport(
            gls_by_view=(("A4C", -18.24), ("A2C", -18.64)),
            qc_by_view=(("A4C", "valid"), ("A2C", "valid")),
            gls_average=-18.44,
            views_valid=("A4C", "A2C"),
            segmentation="AHA-18",
        ),
        linear_measurements=linear,
        vessel_measurements=(
            VesselMeasurement(
                psv_cm_s=84.36,
                edv_cm_s=24.64,
                ri=0.708,
                sd=3.42,
                mv_approx=44.55,
                sop_instance_uid="1.2.3",
                frame_index=0,
                label="ОСА правая",
            ),
        ),
    )
    projection = StudyProjection(
        values={
            "lv.ivsd": ProjectionValue(value=12.4),
            "lv.lvedd": ProjectionValue(value=58.6),
            "lv.ef_bp": ProjectionValue(value=53.8),
            "la.lavi_bp": ProjectionValue(value=39.74),
            "tr.vmax": ProjectionValue(value=314.0),
            "lv.gls": ProjectionValue(value=-18.44),
            "mv.e": ProjectionValue(value=88.4),
            "tdi.e_sept": ProjectionValue(value=7.44),
        },
    )
    return snapshot, projection


class TestCrossSurfaceAgreement:
    @pytest.mark.parametrize("length_unit", ["mm", "cm"])
    def test_status_overlay_html_report_and_pdf_render_identical_numbers(
        self,
        length_unit: str,
    ) -> None:
        snapshot, projection = _rich_snapshot_and_projection()
        provider = ToolStatusProvider(linear_unit=length_unit)

        text_overlay = format_results_overlay(snapshot, time_calibrated=True, length_display_unit=length_unit)
        html_overlay = format_results_overlay_html(
            snapshot,
            time_calibrated=True,
            sex_male=True,
            length_display_unit=length_unit,
        )
        _, doc_values, pdf_text = _doc_and_pdf_text(snapshot, length_unit=length_unit)

        expected_ivsd = "12" if length_unit == "mm" else "1.2"
        assert provider.status("lv.ivsd", projection).text == expected_ivsd
        assert f": {expected_ivsd} {length_unit}" in text_overlay
        assert f">{expected_ivsd}</span>" in html_overlay
        assert expected_ivsd in doc_values
        assert expected_ivsd in pdf_text

        for key, expected in (
            ("lv.ef_bp", "54"),
            ("la.lavi_bp", "40"),
            ("tr.vmax", "3.1"),
            ("mv.e", "88"),
            ("tdi.e_sept", "7.4"),
        ):
            assert provider.status(key, projection).text == expected
            assert expected in text_overlay
            assert f">{expected}<" in html_overlay
            assert expected in doc_values
            assert expected in pdf_text

        # Strain GLS agrees across ToolStatusProvider, ReportDocument, and PDF.
        assert provider.status("lv.gls", projection).text == "-18.4"
        assert "-18.4" in doc_values
        assert "-18.4" in pdf_text

        from echo_personal_tool.domain.services.indexed_results_formatter import build_indexed_overlay_rows

        # Indexed linear row (decimals=2 -> 32.43) agrees across indexed/text/HTML overlays;
        # BSA (1.92), LVMi (129), vessel PSV (84.4), and RWT (0.41) agree across report/PDF too.
        indexed_text = "\n".join(row.format_text() for row in build_indexed_overlay_rows(snapshot))
        assert "32.43 mm/m²" in text_overlay
        assert "32.43 mm/m²" in indexed_text
        assert ">32.43</span>" in html_overlay
        assert "1.92" in doc_values and "1.92" in pdf_text
        assert "135" in text_overlay and "135" in doc_values and "135" in pdf_text
        assert ">84.4</span>" in html_overlay
        assert "84.4" in doc_values
        assert "0.41" in text_overlay
        assert ">0.41</span>" in html_overlay
        assert "0.41" in doc_values
        assert "0.41" in pdf_text

    @pytest.mark.parametrize(
        ("measurement_id", "status_key", "mutated_decimals", "expected_mutated"),
        [
            ("lv.ivsd", "lv.ivsd", 2, "12.40"),
            ("lv.ef_bp", "lv.ef_bp", 2, "53.80"),
            ("la.lavi_bp", "la.lavi_bp", 2, "39.74"),
            ("tr.vmax", "tr.vmax", 3, "3.140"),
            ("mv.e", "mv.e", 2, "88.40"),
        ],
    )
    def test_mutating_catalog_decimals_propagates_to_all_surfaces(
        self,
        measurement_id: str,
        status_key: str,
        mutated_decimals: int,
        expected_mutated: str,
    ) -> None:
        snapshot, projection = _rich_snapshot_and_projection()
        provider = ToolStatusProvider(linear_unit="mm")

        with _override_catalog_decimals(measurement_id, mutated_decimals):
            assert provider.status(status_key, projection).text == expected_mutated
            text_overlay = format_results_overlay(snapshot, time_calibrated=True, length_display_unit="mm")
            html_overlay = format_results_overlay_html(snapshot, time_calibrated=True, length_display_unit="mm")
            _, doc_values, pdf_text = _doc_and_pdf_text(snapshot, length_unit="mm")

            assert expected_mutated in text_overlay
            assert f">{expected_mutated}<" in html_overlay
            assert expected_mutated in doc_values
            assert expected_mutated in pdf_text

    def test_mutating_gls_decimals_propagates_to_status_summary_table_report_and_pdf(self, qapp) -> None:
        from echo_personal_tool.ui.summary_table import SummaryTable

        snapshot, projection = _rich_snapshot_and_projection()
        provider = ToolStatusProvider(linear_unit="mm")
        table = SummaryTable()

        with _override_catalog_decimals("lv.gls", 2):
            assert provider.status("lv.gls", projection).text == "-18.44"
            table.update_values(gls=-18.44)
            assert table._rows["gls"][1].text() == "-18.44%"
            _, doc_values, pdf_text = _doc_and_pdf_text(snapshot, length_unit="mm")
            assert "-18.44" in doc_values
            assert "-18.44" in pdf_text


class TestFormatterRatchets:
    @pytest.mark.parametrize(
        "rel_path",
        [
            "domain/services/measurement_results_formatter.py",
            "domain/services/indexed_results_formatter.py",
            "domain/services/report_builder.py",
            "application/tool_status.py",
            "presentation/doppler_derivative_panel.py",
        ],
    )
    def test_no_literal_decimals_keyword_overrides(self, rel_path: str) -> None:
        source = (SRC_ROOT / rel_path).read_text(encoding="utf-8")
        tree = ast.parse(source, filename=rel_path)
        offenders: list[int] = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for kw in node.keywords:
                    if kw.arg == "decimals" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, int):
                        offenders.append(node.lineno)
        assert not offenders, f"{rel_path} passes literal decimals=... at lines {offenders}"

    def test_text_and_html_overlays_share_build_overlay_rows(self) -> None:
        path = SRC_ROOT / "domain/services/measurement_results_formatter.py"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        funcs = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
        for fn_name in ("format_results_overlay", "format_results_overlay_html"):
            fn = funcs[fn_name]
            called = {
                node.func.id for node in ast.walk(fn) if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
            }
            assert "build_overlay_rows" in called, f"{fn_name} must render from build_overlay_rows"


class TestDisplayFormatsHelpers:
    def test_technical_display_helpers_round_and_clamp(self) -> None:
        assert display_formats.format_fps(59.96) == "60.0"
        assert display_formats.format_fps(-5.0) == "0.0"
        assert display_formats.format_frame_time_ms(33.333) == "33.3"
        assert display_formats.format_frequency_mhz(2.54) == "2.5"
        assert display_formats.format_pixel_spacing_mm(0.25) == "0.250"
        assert display_formats.format_mm_per_px(0.456) == "0.46"
        assert display_formats.format_ms_per_px(4.0) == "4.00"
        assert display_formats.format_region_delta(0.02541) == "0.0254"
        assert display_formats.format_patient_height_cm(175.2) == "175"
        assert display_formats.format_patient_weight_kg(72.46) == "72.5"
        assert display_formats.format_bmi(23.66) == "23.7"
        assert display_formats.format_zoom_factor(2.0) == "2.0"
        assert display_formats.format_scale_factor(1.256) == "1.26"
        assert display_formats.format_dpr(2.0) == "2.0"
        assert display_formats.format_playback_seconds(1.234) == "1.2"
        assert display_formats.format_playback_seconds(1.234, fine=True) == "1.23"
        assert display_formats.format_sync_ratio(1.054) == "1.05"
        assert display_formats.format_confidence_score(0.946) == "0.95"
        assert display_formats.format_confidence_pct(0.946) == "95%"
        assert display_formats.format_whole_pct(91.6) == "92"
        assert display_formats.format_storage_unit_value(12.36) == "12.4"
        assert display_formats.format_storage_bytes(0) == "0 B"
        assert display_formats.format_storage_bytes(512) == "512 B"
        assert display_formats.format_storage_bytes(2048) == "2.0 KiB"
        assert display_formats.format_pixel_extent(42.36) == "42.4"
        assert display_formats.format_pixel_extent(42.36, whole=True) == "42"
