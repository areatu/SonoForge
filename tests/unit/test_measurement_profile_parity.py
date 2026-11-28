"""Full/Presenter measurement parity gate (audit 2026-11-27, follow-up).

SonoForge ships two build profiles from one source tree
(``infrastructure/profile.py``).  Presenter hides the ONNX/AI tools
(``measures_menu._AI_ONNX_ACTIONS``) and moves data to portable storage, but
every measurement that both builds offer must produce **bit-identical**
results: same formulas, same rounding, same fail-closed behaviour.  A profile
branch inside the measurement core would make a Presenter demo disagree with
a Full workstation on the same cine — this file turns that into a loud
failure instead of a support ticket.

The gate pins three facts:

1. The shared pure measurement core (Teichholz, Simpson biplane, Bernoulli,
   Doppler derived metrics, BSA, the #418 validation metrics) computes
   byte-identical results under ``SONOFORGE_PROFILE=full`` and
   ``=presenter``.  The domain layer must not read the profile; if a future
   change makes it do so, the two batteries diverge and this fails.
2. The presenter measurements menu is exactly the full menu minus the
   documented AI/ONNX actions — no other tool may silently disappear from a
   shipped build.
3. The capability matrix keeps the accuracy-relevant features (calculators,
   measurement storage) enabled in both profiles; the only documented
   accuracy-related difference is ``ai_segmentation``.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.calculations.bernoulli import pressure_gradient_mmhg
from echo_personal_tool.domain.calculations.body_surface import bsa_du_bois_m2
from echo_personal_tool.domain.calculations.doppler_metrics import compute
from echo_personal_tool.domain.calculations.lvef_simpson import calculate
from echo_personal_tool.domain.calculations.teichholz import from_linear_measurements
from echo_personal_tool.domain.models.contour import Contour
from echo_personal_tool.domain.models.doppler import DopplerMeasurementDTO, DopplerPeakMarker, DopplerTrace
from echo_personal_tool.domain.models.linear_measurement import LinearMeasurement
from echo_personal_tool.domain.validation import metrics


def _rectangle(phase: str, view: str, width_px: float, height_px: float) -> Contour:
    return Contour(
        phase=phase,
        view=view,
        points=[(0.0, 0.0), (width_px, 0.0), (width_px, height_px), (0.0, height_px)],
    )


def _doppler_dto() -> DopplerMeasurementDTO:
    trace = DopplerTrace(
        label="LVOT VTI",
        points=((0.0, 0.0), (150.0, 133.33333333333334), (300.0, 0.0)),
        measurement_id="l0",
    )
    peaks = (
        DopplerPeakMarker("LVOT Vmax", 10.0, 100.0, "lp0", "PW"),
        DopplerPeakMarker("AV Vmax", 20.0, -450.0, "ap0", "CW"),
    )
    return DopplerMeasurementDTO(peaks=peaks, intervals=(), traces=(trace,))


def _measurement_battery() -> dict[str, str]:
    """Representative pure measurement computations, keyed and repr-stable.

    ``repr`` gives bit-exact comparison for floats (including ``None`` and
    NaN spellings), so any change in precision, order of operations or
    fail-closed behaviour shows up as a string difference.
    """
    battery: dict[str, str] = {}
    calibrated = (
        LinearMeasurement(label="LVEDD", pixel_length=100.0, millimeter_length=50.0),
        LinearMeasurement(label="LVESD", pixel_length=60.0, millimeter_length=30.0),
    )
    battery["teichholz"] = repr(from_linear_measurements(calibrated, spacing_calibrated=True))
    # Fail-closed parity: uncalibrated calipers must yield None in both builds.
    battery["teichholz_uncalibrated"] = repr(from_linear_measurements(calibrated, spacing_calibrated=False))
    contours = (
        _rectangle("ed", "a4c", 100.0, 50.0),
        _rectangle("es", "a4c", 80.0, 40.0),
    )
    battery["simpson_biplane"] = repr(calculate(contours, (0.5, 0.5)))
    battery["bernoulli"] = repr(pressure_gradient_mmhg(400.0))
    battery["bernoulli_nonfinite"] = repr(pressure_gradient_mmhg(float("inf")))
    battery["doppler_metrics"] = repr(compute(_doppler_dto()))
    battery["bsa_du_bois"] = repr(bsa_du_bois_m2(172.0, 74.0))
    reference = (58.0, 30.0, 47.0, 22.0, 61.0)
    predicted = (55.0, 35.0, 44.0, 25.0, 60.0)
    battery["ef_validation_mae"] = repr(metrics.mean_absolute_error(reference, predicted))
    battery["ef_validation_bias"] = repr(metrics.bias(reference, predicted))
    battery["ef_validation_bland_altman"] = repr(metrics.bland_altman_limits(reference, predicted))
    battery["ef_validation_pearson"] = repr(metrics.pearson_r(reference, predicted))
    battery["ef_validation_sens_spec"] = repr(metrics.sensitivity_specificity(reference, predicted, threshold=40.0))
    battery["ef_validation_confusion"] = repr(metrics.confusion_counts(reference, predicted, threshold=40.0))
    return battery


def test_measurement_core_is_bit_identical_between_profiles(monkeypatch: pytest.MonkeyPatch) -> None:
    """The shared measurement battery computes identical results in both builds."""
    monkeypatch.setenv("SONOFORGE_PROFILE", "full")
    full_battery = _measurement_battery()
    monkeypatch.setenv("SONOFORGE_PROFILE", "presenter")
    presenter_battery = _measurement_battery()

    # Non-triviality guard: the battery must carry real results (the parity
    # comparison alone would silently pass on an all-None battery).
    assert full_battery["teichholz"] != "None"
    assert full_battery["simpson_biplane"] != "None"
    assert full_battery["bernoulli"] == "64.0"
    assert full_battery["bsa_du_bois"] != "None"
    assert len(full_battery) == 13

    assert full_battery == presenter_battery, (
        "Full and Presenter builds disagree on the shared measurement core:\n"
        + "\n".join(
            f"  {key}: full={full_battery[key]!r} presenter={presenter_battery[key]!r}"
            for key in full_battery
            if full_battery[key] != presenter_battery[key]
        )
    )


def test_presenter_menu_differs_from_full_only_by_ai_actions(monkeypatch: pytest.MonkeyPatch) -> None:
    """The only tools a Presenter build lacks are the documented ONNX/AI ones."""
    from echo_personal_tool.presentation.measures_menu import _AI_ONNX_ACTIONS, _MENU, _filter_menu

    def _values(profile: str) -> set[str]:
        monkeypatch.setenv("SONOFORGE_PROFILE", profile)
        filtered = _filter_menu(_MENU, None)
        return {str(btn.action) for _, buttons in filtered for btn in buttons}

    full_values = _values("full")
    presenter_values = _values("presenter")

    assert presenter_values <= full_values
    assert full_values - presenter_values == set(_AI_ONNX_ACTIONS), (
        "Presenter lost tools beyond the documented AI/ONNX set: "
        f"{sorted(full_values - presenter_values - set(_AI_ONNX_ACTIONS))}"
    )
    # The AI set itself is exactly what ships only with ONNX segmentation.
    assert _AI_ONNX_ACTIONS  # non-empty: the gate must compare a real set


def test_capability_matrix_keeps_accuracy_features_in_both_profiles() -> None:
    """Calculators and measurement storage ship in both profiles; AI does not."""
    from echo_personal_tool.infrastructure.profile import PROFILE_CAPABILITY_MATRIX

    full = PROFILE_CAPABILITY_MATRIX["full"]
    presenter = PROFILE_CAPABILITY_MATRIX["presenter"]
    assert full.calculators is True
    assert presenter.calculators is True
    assert full.measurement_storage is True
    assert presenter.measurement_storage is True
    # The one documented accuracy difference: Presenter has no ONNX runtime.
    assert full.ai_segmentation is True
    assert presenter.ai_segmentation is False
