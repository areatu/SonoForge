"""QH-1e: independent synthetic oracles; no clinical data or model inference.

Scalar tolerance: rel=1e-10, abs=1e-10. Simpson tolerance: rel=0.002
(fixed 20 midpoint disks + polygon approximation of an analytic half ellipsoid).
Display rounding is checked separately and never fed back into numerical tests.
"""

from __future__ import annotations

import math
from dataclasses import replace

import pymupdf
import pytest

from echo_personal_tool.application.calculator_inputs import evaluate_standalone, resolve_study_inputs
from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.domain.calculations.bernoulli import pressure_gradient_mmhg
from echo_personal_tool.domain.calculations.body_surface import bsa_du_bois_m2, compute_indexed_measurements
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.calculators import CALCULATORS, evaluate
from echo_personal_tool.domain.calculators.models import SOURCE_DERIVED, SOURCE_MANUAL, SOURCE_PATIENT
from echo_personal_tool.domain.models import Contour, MeasurementSnapshot
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker, DopplerTrace
from echo_personal_tool.domain.models.doppler_axis import DopplerAxisMapping
from echo_personal_tool.domain.services.doppler_repeats import report_sample_count
from echo_personal_tool.domain.services.report_builder import build_report_document
from echo_personal_tool.infrastructure.i18n import set_language
from echo_personal_tool.infrastructure.measurement_repository import MeasurementRepository


def _scalar(expected):
    return pytest.approx(expected, rel=1e-10, abs=1e-10)


def _half_ellipse(phase, view, diameter_mm, length_mm, spacing):
    """Open arc, MA at y=L; revolving it gives V=π D² L / 6.

    Physical coordinates are converted to image x/column and y/row pixels.
    Two unequal views describe elliptical disks: V=π D4 D2 L / 6.
    """
    row, col = spacing
    points = [
        ((diameter_mm / 2 * (1 + math.cos(t))) / col, (length_mm * (1 - math.sin(t))) / row)
        for t in (math.pi - i * math.pi / 1000 for i in range(1001))
    ]
    return Contour(
        phase=phase,
        view=view,
        points=points,
        mitral_annulus=((0, length_mm / row), (diameter_mm / col, length_mm / row)),
        apex_landmark=(diameter_mm / 2 / col, 0),
    )


@pytest.mark.parametrize("spacing", [(1.0, 1.0), (0.5, 0.5), (0.4, 0.8)])
@pytest.mark.parametrize("biplane", [False, True])
def test_simpson_analytic_half_ellipsoid(spacing, biplane):
    contours = tuple(
        _half_ellipse(phase, view, diameter, length, spacing)
        for view, ed_d, es_d in (("A4C", 50, 30), ("A2C", 40, 24))
        if biplane or view == "A4C"
        for phase, diameter, length in (("ED", ed_d, 80), ("ES", es_d, 64))
    )
    result = calculate(contours, spacing)
    assert result is not None
    assert result.a4c.edv_ml == pytest.approx(math.pi * 50**2 * 80 / 6000, rel=0.002)
    assert result.a4c.esv_ml == pytest.approx(math.pi * 30**2 * 64 / 6000, rel=0.002)
    assert result.lvef_percent == _scalar(71.2)
    assert result.method == ("simpson_biplan" if biplane else "simpson_monoplan")
    if biplane:
        assert result.edv_bi_ml == pytest.approx(math.pi * 50 * 40 * 80 / 6000, rel=0.002)
        assert result.esv_bi_ml == pytest.approx(math.pi * 30 * 24 * 64 / 6000, rel=0.002)


@pytest.mark.parametrize("spacing", [None, (0.0, 1.0), (1.0, -1.0)])
def test_simpson_requires_positive_calibration(spacing):
    contour = _half_ellipse("ED", "A4C", 50, 80, (1, 1))
    assert calculate((contour,), spacing) is None


def test_simpson_partial_and_pending_do_not_invent_ef():
    contour = _half_ellipse("ED", "A4C", 50, 80, (1, 1))
    result = calculate((contour,), (1, 1))
    assert result.a4c.edv_ml is not None
    assert result.a4c.esv_ml is None
    assert result.lvef_percent is None
    assert calculate((replace(contour, review_pending=True),), (1, 1)) is None


@pytest.mark.parametrize("velocity,expected", [(280, 31.36), (-280, 31.36), (400, 64), (0, 0)])
def test_bernoulli_cm_s_and_sign(velocity, expected):
    assert pressure_gradient_mmhg(velocity) == _scalar(expected)
    dto = DopplerMeasurementDTO(peaks=(DopplerPeakMarker("AV Vmax", 0, velocity),), intervals=(), traces=())
    flow = compute(dto).flow("AV")
    assert flow.vmax_cm_s == abs(velocity)
    assert flow.pgmax_mmhg == _scalar(expected)


@pytest.mark.parametrize("sign", [-1, 1])
@pytest.mark.parametrize("width,height,origin", [(100, 200, 0), (640, 480, 17)])
def test_doppler_calibration_triangle_integrals(sign, width, height, origin):
    axis = DopplerAxisMapping(
        time_origin_ms=origin,
        time_span_ms=200,
        plot_origin_x=11,
        plot_origin_y=13,
        plot_width=width,
        plot_height=height,
        velocity_min_cm_s=-400,
        velocity_max_cm_s=400,
    )
    # Independent pixel positions: time 0,100,200 ms; velocity 0,±400,0 cm/s.
    trace = DopplerTrace(
        "AV VTI",
        tuple(
            (axis.time_ms_from_x(x), axis.velocity_cm_s_from_y(y))
            for x, y in (
                (11, 13 + height / 2),
                (11 + width / 2, 13 if sign > 0 else 13 + height),
                (11 + width, 13 + height / 2),
            )
        ),
    )
    flow = compute(DopplerMeasurementDTO(peaks=(), intervals=(), traces=(trace,))).flow("AV")
    assert flow.vti_cm == _scalar(40)  # 1/2 × 0.2 s × 400 cm/s
    assert flow.vmean_cm_s == _scalar(200)
    assert flow.pgmax_mmhg == _scalar(64)
    assert flow.pgmean_mmhg == _scalar(64 / 3)  # mean(v²), NOT square(mean(v))
    assert flow.vti_repeats == 1


@pytest.mark.parametrize("count", [0, 1, 2, 3, 4, 10])
def test_repeat_window_and_used_count(count):
    velocities = [100 + 20 * i for i in range(count)]
    dto = DopplerMeasurementDTO(
        peaks=tuple(DopplerPeakMarker("TR Vmax", i, -v, measurement_id=f"p{i}") for i, v in enumerate(velocities)),
        intervals=(),
        traces=(),
    )
    flow = compute(dto).flow("TR")
    if not count:
        assert flow is None
        assert report_sample_count(0) == 0
    else:
        assert report_sample_count(flow.vmax_repeats) == min(count, 3)
        expected = sum(velocities[-3:]) / min(count, 3)
        assert flow.vmax_cm_s == _scalar(expected)
        assert flow.pgmax_mmhg == _scalar(4 * (expected / 100) ** 2)


@pytest.mark.parametrize("bad", [0, -1, math.nan, math.inf, -math.inf])
@pytest.mark.parametrize("field", ["height", "weight"])
def test_bsa_rejects_nonphysical_and_nonfinite_values(bad, field):
    height, weight = (bad, 70) if field == "height" else (170, bad)
    assert bsa_du_bois_m2(height, weight) is None
    assert compute_indexed_measurements(MeasurementSnapshot(), height_cm=height, weight_kg=weight) is None


def test_bsa_formula_provenance_and_override():
    inputs = resolve_study_inputs(
        doppler=None, height_cm=170, weight_kg=70, height_source="dicom", weight_source="manual"
    )
    assert inputs["height"].source == inputs["weight"].source == SOURCE_PATIENT
    assert inputs["height"].detail == "dicom"
    assert inputs["weight"].detail == "manual"
    assert inputs["bsa"].source == SOURCE_DERIVED
    assert inputs["bsa"].detail == "Du Bois"
    assert inputs["bsa"].value == _scalar(1.809707801753247)
    override = resolve_study_inputs(doppler=None, height_cm=170, weight_kg=70, manual={"bsa": 2.0})["bsa"]
    assert override.source == SOURCE_MANUAL
    assert override.value == 2
    assert override.auto_value == inputs["bsa"].value
    assert override.auto_source == SOURCE_DERIVED
    assert resolve_study_inputs(doppler=None, height_cm=170)["bsa"].value is None


@pytest.mark.parametrize("language", ["en", "ru"])
def test_disk_restore_structured_document_and_real_pdf_rounding(tmp_path, language):
    from echo_personal_tool.infrastructure.measurement_report_pdf import export_report_document_pdf

    set_language(language)
    uid, sop = "1.2.3", "1.2.3.4"
    sources = {sop: {"fingerprint": "a" * 64, "frames": 1, "spacing": [0.5, 0.5]}}
    peaks = (DopplerPeakMarker("TR Vmax", 0, -280, measurement_id="p1", mode="CW"),)
    data = StudyMeasurementData(
        doppler_by_instance=((sop, DopplerMeasurementDTO(peaks=peaks, intervals=(), traces=())),),
        height_cm=170,
        weight_kg=70,
        height_source="manual",
        weight_source="manual",
    )
    repository = MeasurementRepository(tmp_path / "records")
    repository.save(uid, data, sources, expected_revision=0)
    repository.close()
    restored = MeasurementRepository(tmp_path / "records").load(uid)["data"]
    assert restored == data
    snapshots = []
    for item in (data, restored):
        doppler = compute(item.doppler_measurement)
        inputs = resolve_study_inputs(
            doppler=doppler, height_cm=item.height_cm, weight_kg=item.weight_kg, manual={"rap": 8}
        )
        calculations = evaluate(inputs)
        output = calculations.result("pulmonary_pressure").output("tr_pg")
        assert output.value == _scalar(31.36)
        assert output.formatted() == "31"  # panel uses OutputValue.formatted()
        snapshots.append(MeasurementSnapshot(doppler=doppler, calculations=calculations))
    assert snapshots[0] == snapshots[1]
    from echo_personal_tool.domain.services.nomenclature import flow_label

    vmax_label = flow_label("TR", "Vmax")
    pgmax_label = flow_label("TR", "PGmax")
    document = build_report_document(snapshots[1])
    rows = [(v.label, v.value) for group in document.groups for v in group.values]
    assert (pgmax_label, "31.4") in rows
    assert ("TR PGmax", "31") in rows
    assert (vmax_label, "2.80") in rows
    path = export_report_document_pdf(document, tmp_path / "report.pdf")
    with pymupdf.open(path) as pdf:
        pdf_text = "\n".join(page.get_text() for page in pdf)
    assert f"{vmax_label}\n2.80 m/s" in pdf_text
    assert f"{pgmax_label}\n31.4 mmHg" in pdf_text
    assert "TR PGmax\n31 mmHg" in pdf_text
    # Existing views intentionally use different precision (text 1 decimal,
    # structured report/panel integer); they must agree at their own precision.


# At least one independent numeric oracle per registered calculator. The
# required manifest also gates existing multi-output and invalid-input cases.
_CALCULATOR_CASES = [
    ("stroke_volume", "sv", {"lvot_d": 2, "lvot_vti": 20}, "lvot_d", 20 * math.pi, "62.8"),
    ("aortic_valve_area", "ava_vmax", {"lvot_d": 2, "lvot_vmax": 100, "av_vmax": 4}, "av_vmax", math.pi / 4, "0.79"),
    ("pisa_mr", "eroa_mr", {"pisa_r_mr": 1, "va_mr": 40, "mr_vmax": 5}, "va_mr", 80 * math.pi / 500, "0.50"),
    ("pisa_ar", "eroa_ar", {"pisa_r_ar": 0.6, "va_ar": 40, "ar_vmax": 4}, "ar_vmax", 80 * math.pi * 0.36 / 400, "0.23"),
    ("mitral_valve_area", "mva_pht", {"mv_pht": 220}, "mv_pht", 1, "1.00"),
    ("pulmonary_pressure", "tr_pg", {"tr_vmax": 2.8}, "tr_vmax", 31.36, "31"),
    ("qp_qs", "qp_qs", {"rvot_d": 2.4, "rvot_vti": 25, "lvot_d": 2, "lvot_vti": 20}, "lvot_vti", 1.8, "1.80"),
    ("teichholz", "edv_teich", {"lvedd": 5}, "lvedd", 875 / 7.4, "118"),
    ("dpdt", "lv_dpdt", {"mr_dpdt_dt": 20}, "mr_dpdt_dt", 1600, "1600"),
    ("orifice_area", "area_d", {"orifice_d": 2}, "orifice_d", math.pi, "3.14"),
]


def test_every_registered_calculator_has_an_independent_oracle():
    assert {case[0] for case in _CALCULATOR_CASES} == {spec.id for spec in CALCULATORS}


@pytest.mark.parametrize(
    "calculator,output,values,required,expected,formatted",
    _CALCULATOR_CASES,
    ids=[case[0] for case in _CALCULATOR_CASES],
)
def test_calculator_numeric_and_rounding_oracles(calculator, output, values, required, expected, formatted):
    result = evaluate_standalone(values).result(calculator).output(output)
    assert result.value == _scalar(expected)
    assert result.formatted() == formatted


@pytest.mark.parametrize("bad", [None, 0, -1, math.nan, math.inf, -math.inf])
@pytest.mark.parametrize(
    "calculator,output,values,required,expected,formatted",
    _CALCULATOR_CASES,
    ids=[case[0] for case in _CALCULATOR_CASES],
)
def test_calculator_missing_and_invalid_required_input(calculator, output, values, required, expected, formatted, bad):
    inputs = dict(values)
    if bad is None:
        del inputs[required]
    else:
        inputs[required] = bad
    result = evaluate_standalone(inputs).result(calculator).output(output)
    assert result.value is None
    assert result.formatted() == "—"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_teichholz_nonfinite_inputs_are_not_measurements(bad):
    from echo_personal_tool.domain.calculations.teichholz import (
        ejection_fraction_percent,
        fractional_shortening_percent,
        from_linear_measurements,
        volume_ml,
    )
    from echo_personal_tool.domain.models import LinearMeasurement

    with pytest.raises(ValueError, match="positive and finite"):
        volume_ml(bad)
    assert fractional_shortening_percent(bad, 3) is None
    assert fractional_shortening_percent(5, bad) is None
    assert ejection_fraction_percent(bad, 30) is None
    assert ejection_fraction_percent(100, bad) is None
    for ed, es in ((bad, 30), (50, bad)):
        assert (
            from_linear_measurements((LinearMeasurement("LVEDD", 100, ed), LinearMeasurement("LVESD", 60, es))) is None
        )
