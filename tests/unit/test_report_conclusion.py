"""Conservative report-conclusion rules, rendering and merge semantics.

These cases pin the clinical guardrails of
``docs/superpowers/specs/2026-10-30-report-conclusion-autofill-ru.md``:
missing data never become normal, discordant valve metrics become review
items, and the generated block stays qualitative in both UI languages.
"""

from __future__ import annotations

import math
import re
from dataclasses import replace

import pytest

from echo_personal_tool.application.report_conclusion import age_years_from_text, autofill_conclusion
from echo_personal_tool.domain.calculations.body_surface import resolve_bsa_basis
from echo_personal_tool.domain.calculators.models import (
    SOURCE_MANUAL,
    SOURCE_MEASURED,
    CalculationsSnapshot,
    CalculatorResult,
    CalcWarning,
    InputValue,
    OutputValue,
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
from echo_personal_tool.domain.models.result_provenance import BSA_SOURCE_MANUAL, BsaBasis
from echo_personal_tool.domain.services.report_conclusion import (
    RULESET_VERSION,
    build_conclusion,
    merge_conclusion,
    render_conclusion,
)
from echo_personal_tool.infrastructure.i18n import set_language


@pytest.fixture(autouse=True)
def _ru_locale():
    set_language("ru")
    yield
    set_language("ru")


def _linear(label: str, mm: float) -> LinearMeasurement:
    return LinearMeasurement(label=label, pixel_length=mm, millimeter_length=mm)


def _output(output_id: str, value: float | None, unit: str = "") -> OutputValue:
    return OutputValue(
        id=output_id,
        label=output_id,
        value=value,
        unit=unit,
        decimals=2,
        formula="test",
    )


def _result(calculator_id: str, outputs: tuple[OutputValue, ...], warnings: tuple[CalcWarning, ...] = ()):
    return CalculatorResult(calculator_id=calculator_id, outputs=outputs, warnings=warnings)


def _manual_bsa_snapshot(**kwargs) -> MeasurementSnapshot:
    """A snapshot whose indexed values are fresh against a manual BSA input."""
    basis = BsaBasis(1.8, BSA_SOURCE_MANUAL)
    indexed = kwargs.pop("indexed", None)
    if indexed is None:
        indexed = IndexedMeasurements(bsa_m2=1.8, bsa_basis=basis)
    calculations = kwargs.pop("calculations", None)
    if calculations is None:
        calculations = CalculationsSnapshot(inputs=(InputValue("bsa", 1.8, SOURCE_MANUAL),))
    return MeasurementSnapshot(indexed=indexed, calculations=calculations, **kwargs)


def _keys(draft) -> set[str]:
    return {finding.text_key for finding in draft.findings}


def _one(draft, finding_id: str):
    return next(finding for finding in draft.findings if finding.id == finding_id)


class TestScope:
    def test_empty_study_has_no_findings_and_no_normal_negatives(self) -> None:
        draft = build_conclusion(MeasurementSnapshot(), sex="M", age_years=45)
        assert draft.findings == ()
        assert draft.notices == ()
        assert render_conclusion(draft, "ru") == ""
        assert draft.ruleset_version == RULESET_VERSION

    def test_known_pediatric_age_disables_the_adult_ruleset(self) -> None:
        snapshot = MeasurementSnapshot(lvef=LvefResult(lvef_percent=60, method="simpson_biplan"))
        assert build_conclusion(snapshot, sex="M", age_years=17.9).findings == ()
        assert build_conclusion(snapshot, sex="M", age_years=18).findings != ()

    def test_standalone_calculator_snapshot_is_not_a_study_conclusion(self) -> None:
        snapshot = MeasurementSnapshot(
            lvef=LvefResult(lvef_percent=60, method="simpson_biplan"),
            calculations=CalculationsSnapshot(standalone=True),
        )
        assert build_conclusion(snapshot, sex="M").findings == ()


class TestLeftVentricle:
    @pytest.mark.parametrize(
        ("sex", "ef", "expected"),
        [
            ("M", 52, "normal"),
            ("M", 51.9, "mild"),
            ("F", 54, "normal"),
            ("F", 53.9, "mild"),
            ("", 54, "normal"),
            ("", 51.9, "mild"),
            ("M", 41, "mild"),
            ("M", 40.9, "moderate"),
            ("M", 30, "moderate"),
            ("M", 29.9, "severe"),
        ],
    )
    def test_ef_sex_bands_and_severity_boundaries(self, sex: str, ef: float, expected: str) -> None:
        snapshot = MeasurementSnapshot(lvef=LvefResult(lvef_percent=ef, method="simpson_biplan"))
        finding = _one(build_conclusion(snapshot, sex=sex), "lv.ef")
        assert finding.text_key == f"report.conclusion.finding.lv_ef.{expected}.biplane"

    def test_unknown_sex_between_52_and_54_is_review_not_normal(self) -> None:
        snapshot = MeasurementSnapshot(lvef=LvefResult(lvef_percent=53, method="simpson_biplan"))
        assert _one(build_conclusion(snapshot, sex=""), "lv.ef").text_key.endswith("lv_ef.review")

    def test_monoplane_method_is_named_in_the_phrase(self) -> None:
        snapshot = MeasurementSnapshot(lvef=LvefResult(lvef_percent=60, method="simpson_monoplan"))
        finding = _one(build_conclusion(snapshot, sex="M"), "lv.ef")
        assert finding.text_key.endswith(".monoplane")
        assert "моноплановый" in render_conclusion(build_conclusion(snapshot, sex="M"), "ru")

    def test_teichholz_conflict_becomes_review(self) -> None:
        snapshot = MeasurementSnapshot(
            lvef=LvefResult(lvef_percent=60, method="simpson_biplan"),
            teichholz=TeichholzResult(edv_ml=120, esv_ml=80, lvef_percent=33),
        )
        assert _one(build_conclusion(snapshot, sex="M"), "lv.ef").text_key.endswith("lv_ef.review")

    def test_uncalibrated_spacing_blocks_spatial_findings(self) -> None:
        snapshot = MeasurementSnapshot(
            spacing_calibrated=False,
            lvef=LvefResult(lvef_percent=60, method="simpson_biplan"),
            linear_measurements=(_linear("IVSd", 12), _linear("LVPWd", 12), _linear("TAPSE", 20)),
            rv_fac_percent=40,
        )
        assert build_conclusion(snapshot, sex="M").findings == ()

    @pytest.mark.parametrize(
        ("sex", "edvi", "expected"),
        [
            ("M", 74, "normal"),
            ("M", 75, "mild"),
            ("M", 90, "moderate"),
            ("M", 101, "severe"),
            ("F", 61, "normal"),
            ("F", 62, "mild"),
            ("F", 71, "moderate"),
            ("F", 81, "severe"),
        ],
    )
    def test_biplane_lvedvi_bands(self, sex: str, edvi: float, expected: str) -> None:
        snapshot = _manual_bsa_snapshot(
            lvef=LvefResult(lvef_percent=60, method="simpson_biplan"),
            indexed=IndexedMeasurements(
                bsa_m2=1.8,
                bsa_basis=BsaBasis(1.8, BSA_SOURCE_MANUAL),
                simpson_edvi_ml_m2=edvi,
            ),
        )
        assert _one(build_conclusion(snapshot, sex=sex), "lv.size").text_key.endswith(f"lv_size.{expected}")

    def test_monoplane_ef_does_not_produce_biplane_size_phrase(self) -> None:
        snapshot = _manual_bsa_snapshot(
            lvef=LvefResult(lvef_percent=60, method="simpson_monoplan"),
            indexed=IndexedMeasurements(
                bsa_m2=1.8,
                bsa_basis=BsaBasis(1.8, BSA_SOURCE_MANUAL),
                simpson_edvi_ml_m2=80,
            ),
        )
        assert "lv.size" not in {finding.id for finding in build_conclusion(snapshot, sex="M").findings}

    def test_stale_bsa_blocks_indexed_findings_and_adds_notice(self) -> None:
        basis = resolve_bsa_basis(height_cm=170, weight_kg=65)
        snapshot = MeasurementSnapshot(
            height_cm=180,
            weight_kg=65,
            lvef=LvefResult(lvef_percent=60, method="simpson_biplan"),
            indexed=IndexedMeasurements(
                bsa_m2=basis.value or 1.8,
                bsa_basis=basis,
                simpson_edvi_ml_m2=80,
                lvmi_g_m2=130,
            ),
        )
        draft = build_conclusion(snapshot, sex="M")
        assert "lv.size" not in {finding.id for finding in draft.findings}
        assert "lv.mass" not in {finding.id for finding in draft.findings}
        assert "report.conclusion.notice.bsa" in draft.notices

    @pytest.mark.parametrize(
        ("sex", "thickness", "expected"),
        [
            ("F", 10, "normal"),
            ("F", 11, "mild"),
            ("F", 13, "moderate"),
            ("F", 15, "severe"),
            ("M", 11, "normal"),
            ("M", 12, "mild"),
            ("M", 14, "moderate"),
            ("M", 16, "severe"),
        ],
    )
    def test_wall_thickness_requires_both_walls_and_uses_sex_bands(
        self, sex: str, thickness: float, expected: str
    ) -> None:
        snapshot = MeasurementSnapshot(
            linear_measurements=(_linear("IVSd", thickness), _linear("LVPWd", thickness)),
        )
        assert _one(build_conclusion(snapshot, sex=sex), "lv.wall").text_key.endswith(f"lv_wall.{expected}")
        only_one = MeasurementSnapshot(linear_measurements=(_linear("IVSd", thickness),))
        assert "lv.wall" not in {finding.id for finding in build_conclusion(only_one, sex=sex).findings}

    def test_implausibly_thin_walls_are_review(self) -> None:
        snapshot = MeasurementSnapshot(linear_measurements=(_linear("IVSd", 5), _linear("LVPWd", 10)))
        assert _one(build_conclusion(snapshot, sex="F"), "lv.wall").text_key.endswith("lv_wall.review")

    def test_lvmi_is_increased_only_and_rwt_is_separate(self) -> None:
        snapshot = _manual_bsa_snapshot(
            indexed=IndexedMeasurements(
                bsa_m2=1.8,
                bsa_basis=BsaBasis(1.8, BSA_SOURCE_MANUAL),
                lvmi_g_m2=116,
            ),
            rwt=0.43,
        )
        keys = _keys(build_conclusion(snapshot, sex="M"))
        assert "report.conclusion.finding.lv_mass.increased" in keys
        assert "report.conclusion.finding.lv_rwt.increased" in keys
        normal = _manual_bsa_snapshot(
            indexed=IndexedMeasurements(bsa_m2=1.8, bsa_basis=BsaBasis(1.8, BSA_SOURCE_MANUAL), lvmi_g_m2=90),
            rwt=0.40,
        )
        assert "lv.mass" not in {finding.id for finding in build_conclusion(normal, sex="M").findings}


def _strain(**kwargs) -> StrainReport:
    values = (("A4C", -21.0), ("A2C", -20.0), ("A3C", -19.0))
    base = dict(
        gls_by_view=values,
        qc_by_view=(("A4C", "valid"), ("A2C", "valid"), ("A3C", "valid")),
        gls_average=-20.0,
        views_valid=("A4C", "A2C", "A3C"),
        segmentation="AHA-18",
        avc_source_by_view=(("A4C", "ecg"), ("A2C", "ecg"), ("A3C", "ecg")),
        segments_missing=0,
        contour_source="manual",
    )
    base.update(kwargs)
    return StrainReport(**base)


class TestStrain:
    @pytest.mark.parametrize(
        ("average", "expected"),
        [(-21.0, "gls.normal"), (-20.0, "gls.borderline"), (-18.0, "gls.borderline"), (-17.9, "gls.reduced")],
    )
    def test_complete_manual_qc_strain_bands(self, average: float, expected: str) -> None:
        snapshot = MeasurementSnapshot(
            strain=_strain(
                gls_by_view=(("A4C", average), ("A2C", average), ("A3C", average)),
                gls_average=average,
            )
        )
        draft = build_conclusion(snapshot, sex="M")
        assert _one(draft, "lv.gls").text_key.endswith(expected)
        assert "report.conclusion.notice.strain_method" in draft.notices

    @pytest.mark.parametrize(
        "strain",
        [
            _strain(gls_by_view=(("A4C", -21.0), ("A2C", -20.0))),
            _strain(qc_by_view=(("A4C", "valid"), ("A2C", "review"), ("A3C", "valid"))),
            _strain(views_valid=("A4C", "A2C")),
            _strain(segments_missing=1),
            _strain(contour_source="draft"),
            _strain(avc_source_by_view=(("A4C", "ecg"), ("A2C", "unknown"), ("A3C", "ecg"))),
            _strain(gls_average=-10.0),
            _strain(gls_by_view=(("A4C", math.nan), ("A2C", -20.0), ("A3C", -19.0))),
        ],
    )
    def test_incomplete_or_unconfirmed_strain_is_not_classified(self, strain: StrainReport) -> None:
        draft = build_conclusion(MeasurementSnapshot(strain=strain), sex="M")
        assert "lv.gls" not in {finding.id for finding in draft.findings}
        assert "report.conclusion.notice.strain_qc" in draft.notices


class TestAtriaAndRightVentricle:
    def test_la_requires_biplane_es_volumes(self) -> None:
        la = ChamberSimpsonResult(
            chamber="LA",
            method="simpson_biplan",
            a4c=LvViewMetrics(esv_ml=60),
            a2c=LvViewMetrics(esv_ml=62),
        )
        snapshot = _manual_bsa_snapshot(
            la_simpson=la,
            indexed=IndexedMeasurements(
                bsa_m2=1.8,
                bsa_basis=BsaBasis(1.8, BSA_SOURCE_MANUAL),
                lav_bi_index_ml_m2=35,
            ),
        )
        assert _one(build_conclusion(snapshot, sex="M"), "la.size").text_key.endswith("la_size.mild")
        monoplane = replace(la, method="simpson_monoplan")
        assert "la.size" not in {
            finding.id for finding in build_conclusion(replace(snapshot, la_simpson=monoplane), sex="M").findings
        }

    def test_ra_uses_explicit_end_systolic_volume_not_ed_fallback(self) -> None:
        ra = ChamberSimpsonResult(chamber="RA", a4c=LvViewMetrics(esv_ml=54))
        snapshot = _manual_bsa_snapshot(ra_simpson=ra)
        assert _one(build_conclusion(snapshot, sex="M"), "ra.size").text_key.endswith("ra_size.mild")
        ed_only = ChamberSimpsonResult(chamber="RA", a4c=LvViewMetrics(edv_ml=54), max_volume_ml=54)
        assert "ra.size" not in {
            finding.id for finding in build_conclusion(replace(snapshot, ra_simpson=ed_only), sex="M").findings
        }

    @pytest.mark.parametrize(
        ("basal", "expected"),
        [(40, "normal"), (41, "mild"), (44, "mild"), (45, "moderate"), (49, "moderate"), (50, "severe")],
    )
    def test_rv_basal_bands(self, basal: float, expected: str) -> None:
        snapshot = MeasurementSnapshot(linear_measurements=(_linear("RV basal", basal),))
        assert _one(build_conclusion(snapshot, sex="M"), "rv.size").text_key.endswith(f"rv_size.{expected}")

    @pytest.mark.parametrize(
        ("tapse", "expected"),
        [(18, "normal"), (17, "mild"), (13, "moderate"), (10, "severe")],
    )
    def test_tapse_bands(self, tapse: float, expected: str) -> None:
        snapshot = MeasurementSnapshot(linear_measurements=(_linear("TAPSE", tapse),))
        assert _one(build_conclusion(snapshot, sex="M"), "rv.tapse").text_key.endswith(f"rv_tapse.{expected}")

    def test_tapse_and_fac_agree_or_review(self) -> None:
        agree = MeasurementSnapshot(linear_measurements=(_linear("TAPSE", 20),), rv_fac_percent=40)
        assert _one(build_conclusion(agree, sex="M"), "rv.function").text_key.endswith("rv_function.normal")
        disagree = MeasurementSnapshot(linear_measurements=(_linear("TAPSE", 20),), rv_fac_percent=20)
        assert _one(build_conclusion(disagree, sex="M"), "rv.function").text_key.endswith("rv_function.review")


def _as_snapshot(
    *,
    vmax: float | None = None,
    gradient: float | None = None,
    ava: float | None = None,
    dvi: float | None = None,
    warnings: tuple[CalcWarning, ...] = (),
    ava_vmax: float | None = None,
) -> MeasurementSnapshot:
    inputs = (InputValue("av_vmax", vmax, SOURCE_MEASURED),) if vmax is not None else ()
    outputs = []
    if ava is not None:
        outputs.append(_output("ava_vti", ava, "cm²"))
    if ava_vmax is not None:
        outputs.append(_output("ava_vmax", ava_vmax, "cm²"))
    if dvi is not None:
        outputs.append(_output("dvi_vti", dvi))
    doppler = (
        DopplerResults(flow_results=(DopplerFlowResult(site="AV", pgmean_mmhg=gradient),))
        if gradient is not None
        else None
    )
    return MeasurementSnapshot(
        doppler=doppler,
        calculations=CalculationsSnapshot(
            inputs=inputs,
            results=(_result("aortic_valve_area", tuple(outputs), warnings),),
        ),
    )


class TestAorticStenosis:
    @pytest.mark.parametrize(
        ("vmax", "gradient", "ava", "dvi", "expected"),
        [
            (2.7, 15, 1.8, 0.6, "as.mild"),
            (3.5, 30, 1.2, 0.35, "as.moderate"),
            (4.5, 50, 0.8, 0.2, "as.severe"),
            (5.5, 70, 0.7, 0.18, "as.very_severe"),
            (2.0, 8, 2.2, 0.8, "as.no_obstruction"),
            (4.5, 20, 1.2, 0.4, "as.review"),
            (4.5, None, None, None, "as.review"),
        ],
    )
    def test_concordance_and_discordance(
        self, vmax: float, gradient: float | None, ava: float | None, dvi: float | None, expected: str
    ) -> None:
        draft = build_conclusion(_as_snapshot(vmax=vmax, gradient=gradient, ava=ava, dvi=dvi), sex="M")
        assert _one(draft, "av.stenosis").text_key.endswith(expected)

    def test_engine_warnings_and_ava_method_conflict_block_grade(self) -> None:
        warned = _as_snapshot(
            vmax=4.5,
            gradient=50,
            ava=0.8,
            dvi=0.2,
            warnings=(CalcWarning("ava_methods_diverge"),),
        )
        assert _one(build_conclusion(warned, sex="M"), "av.stenosis").text_key.endswith("as.review")
        conflict = _as_snapshot(vmax=4.5, gradient=50, ava=0.8, ava_vmax=1.3, dvi=0.2)
        assert _one(build_conclusion(conflict, sex="M"), "av.stenosis").text_key.endswith("as.review")


def _regurg_snapshot(valve: str, eroa: float | None, rvol: float | None, rf: float | None) -> MeasurementSnapshot:
    outputs = tuple(
        _output(f"{name}_{valve}", value)
        for name, value in (("eroa", eroa), ("rvol", rvol), ("rf", rf))
        if value is not None
    )
    return MeasurementSnapshot(calculations=CalculationsSnapshot(results=(_result(f"pisa_{valve}", outputs),)))


class TestRegurgitation:
    @pytest.mark.parametrize(
        ("eroa", "rvol", "rf", "expected"),
        [
            (0.08, 20, 20, "ar.mild"),
            (0.20, 45, 40, "ar.moderate"),
            (0.35, 70, 60, "ar.severe"),
            (0.35, 70, None, "ar.review"),
            (0.35, 40, 60, "ar.review"),
        ],
    )
    def test_ar_requires_full_concordant_set(self, eroa: float, rvol: float, rf: float | None, expected: str) -> None:
        draft = build_conclusion(_regurg_snapshot("ar", eroa, rvol, rf), sex="M")
        assert _one(draft, "av.regurgitation").text_key.endswith(expected)

    @pytest.mark.parametrize(
        ("eroa", "rvol", "rf", "expected"),
        [
            (0.10, 20, 20, "mr.mild"),
            (0.45, 70, 60, "mr.severe"),
            (0.30, 45, 40, "mr.review"),
            (0.45, 70, None, "mr.review"),
        ],
    )
    def test_mr_only_common_extreme_categories(self, eroa: float, rvol: float, rf: float | None, expected: str) -> None:
        draft = build_conclusion(_regurg_snapshot("mr", eroa, rvol, rf), sex="M")
        assert _one(draft, "mv.regurgitation").text_key.endswith(expected)

    def test_combined_ar_mr_suppresses_individual_grades(self) -> None:
        ar = _regurg_snapshot("ar", 0.35, 70, 60)
        mr = _regurg_snapshot("mr", 0.45, 70, 60)
        combined = replace(
            ar,
            calculations=CalculationsSnapshot(results=ar.calculations.results + mr.calculations.results),
        )
        draft = build_conclusion(combined, sex="M")
        assert {finding.id for finding in draft.findings} == {"regurgitation.combined"}
        assert _one(draft, "regurgitation.combined").text_key.endswith("regurgitation.combined_review")


def _ms_snapshot(area: float | None, gradient: float | None, *, pisa: float | None = None) -> MeasurementSnapshot:
    outputs = []
    if area is not None:
        outputs.append(_output("mva_pht", area, "cm²"))
    if pisa is not None:
        outputs.append(_output("mva_pisa", pisa, "cm²"))
    doppler = (
        DopplerResults(flow_results=(DopplerFlowResult(site="MV", pgmean_mmhg=gradient),))
        if gradient is not None
        else None
    )
    return MeasurementSnapshot(
        doppler=doppler,
        calculations=CalculationsSnapshot(results=(_result("mitral_valve_area", tuple(outputs)),)),
    )


class TestMitralStenosis:
    @pytest.mark.parametrize(
        ("area", "gradient", "expected"),
        [(3.0, 3, "ms.mild"), (2.0, 7, "ms.moderate"), (1.2, 12, "ms.severe"), (1.2, 4, "ms.review")],
    )
    def test_area_and_gradient_must_agree(self, area: float, gradient: float, expected: str) -> None:
        draft = build_conclusion(_ms_snapshot(area, gradient), sex="M")
        assert _one(draft, "mv.stenosis").text_key.endswith(expected)

    def test_area_alone_or_conflicting_areas_are_review(self) -> None:
        assert _one(build_conclusion(_ms_snapshot(1.2, None), sex="M"), "mv.stenosis").text_key.endswith("ms.review")
        conflict = _ms_snapshot(1.2, 12, pisa=2.2)
        assert _one(build_conclusion(conflict, sex="M"), "mv.stenosis").text_key.endswith("ms.review")


class TestPulmonaryHypertension:
    @pytest.mark.parametrize(
        ("tr_vmax", "expected"),
        [(3.5, "ph.high"), (3.4, "ph.intermediate"), (2.9, "ph.intermediate")],
    )
    def test_tr_probability_not_pasp_severity(self, tr_vmax: float, expected: str) -> None:
        snapshot = MeasurementSnapshot(
            calculations=CalculationsSnapshot(inputs=(InputValue("tr_vmax", tr_vmax, SOURCE_MEASURED),))
        )
        assert _one(build_conclusion(snapshot, sex="M"), "ph.probability").text_key.endswith(expected)

    def test_low_tr_velocity_does_not_exclude_ph_and_pasp_alone_is_silent(self) -> None:
        low = MeasurementSnapshot(
            calculations=CalculationsSnapshot(inputs=(InputValue("tr_vmax", 2.5, SOURCE_MEASURED),))
        )
        assert build_conclusion(low, sex="M").findings == ()
        pasp_only = MeasurementSnapshot(
            calculations=CalculationsSnapshot(results=(_result("pulmonary_pressure", (_output("pasp", 60),)),))
        )
        assert build_conclusion(pasp_only, sex="M").findings == ()


class TestRenderingAndMerge:
    def test_both_languages_are_qualitative_and_carry_review_notice(self) -> None:
        snapshot = MeasurementSnapshot(lvef=LvefResult(lvef_percent=25, method="simpson_biplan"))
        draft = build_conclusion(snapshot, sex="M")
        for language in ("ru", "en"):
            text = render_conclusion(draft, language)
            assert text.startswith("• ")
            assert re.search(r"\d", text) is None
            assert "report.conclusion." not in text
        assert "report.conclusion.notice.review" in draft.notices

    def test_append_update_idempotence_and_edited_block_protection(self) -> None:
        first = merge_conclusion("Ручной текст.", "• A")
        assert first.text == "Ручной текст.\n\n• A"
        assert first.status_key.endswith("added")
        again = merge_conclusion(first.text, "• A", first.generated_block)
        assert again.changed is False
        assert again.text == first.text
        updated = merge_conclusion(first.text, "• B", first.generated_block)
        assert updated.text == "Ручной текст.\n\n• B"
        assert updated.status_key.endswith("updated")
        edited = merge_conclusion("Ручной текст.\n\n• A изменено", "• B", "• A")
        assert edited.text == "Ручной текст.\n\n• A изменено\n\n• B"
        assert edited.preserved_edited_block is True
        assert edited.status_key.endswith("appended_after_edit")

    def test_no_data_leaves_text_unchanged(self) -> None:
        merged = merge_conclusion("Ручной текст.", "", "• old")
        assert merged.text == "Ручной текст."
        assert merged.changed is False
        assert merged.status_key.endswith("no_data")

    def test_application_adds_edited_block_notice_and_uses_ui_language(self) -> None:
        snapshot = MeasurementSnapshot(lvef=LvefResult(lvef_percent=60, method="simpson_biplan"))
        result = autofill_conclusion(
            snapshot,
            sex="M",
            language="en",
            existing="Manual text.\n\n• old edited",
            previous_generated="• old",
        )
        assert result.changed is True
        assert "Manual text.\n\n• old edited" in result.text
        assert "no longer managed" in result.text
        assert result.status_key.endswith("appended_after_edit")


class TestAgeParsing:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            (45, 45.0),
            ("45", 45.0),
            ("045Y", 45.0),
            ("003M", 0.25),
            ("020D", 20 / 365.25),
            ("6 мес", 0.5),
            ("18 years", 18.0),
            ("", None),
            ("unknown", None),
            ("45 kg", None),
        ],
    )
    def test_unit_aware_age_parsing(self, raw: object, expected: float | None) -> None:
        value = age_years_from_text(raw)
        if expected is None:
            assert value is None
        else:
            assert value == pytest.approx(expected)
