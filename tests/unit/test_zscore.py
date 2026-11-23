"""Z-score machinery (plan А.12, issue #650) — the honest reference engine.

A paediatric reference is a function of body size, not a fixed adult range.
These tests pin the mechanics: piecewise-linear band interpolation, the
refusal to extrapolate beyond the anchored range, the percentile mapping
and the report-friendly formatting.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.zscore import (
    BsaBand,
    BsaBandModel,
    GaBand,
    GaBandModel,
    format_z,
    percentile_curve,
    percentile_label,
    percentile_to_z,
    z_to_percentile,
)


class TestBsaModel:
    @staticmethod
    def _model() -> BsaBandModel:
        return BsaBandModel(
            bands=(
                BsaBand(0.5, 20.0, 4.0),
                BsaBand(1.0, 30.0, 5.0),
                BsaBand(1.5, 40.0, 5.0),
            ),
            source="test table",
        )

    def test_the_anchor_band_solves_exactly(self) -> None:
        result = self._model().zscore(30.0, 1.0)
        assert result is not None
        assert result.z == pytest.approx(0.0)
        assert result.percentile == pytest.approx(50.0)
        assert result.on_edge is False
        assert result.display() == "+0.00 (P50)"

    def test_interpolation_between_anchors(self) -> None:
        model = self._model()
        result = model.zscore(35.0, 1.25)  # halfway: mean 35, sd 5.0
        assert result is not None
        assert result.z == pytest.approx(0.0)
        high = model.zscore(40.0, 1.25)  # +1 sd at the interpolated mean
        assert high is not None
        assert high.z == pytest.approx(1.0)
        assert high.percentile == pytest.approx(84.13, rel=1e-2)

    def test_outside_the_anchored_range_is_none(self) -> None:
        model = self._model()
        assert model.zscore(30.0, 0.4) is None
        assert model.zscore(30.0, 1.6) is None

    def test_a_nonfinite_value_is_none(self) -> None:
        model = self._model()
        assert model.zscore(float("nan"), 1.0) is None
        assert model.zscore(30.0, 0.0) is None

    def test_value_at_z_round_trips(self) -> None:
        model = self._model()
        result = model.zscore(37.5, 1.0)
        assert result is not None
        assert model.value_at_z(result.z, 1.0) == pytest.approx(37.5)
        assert model.value_at_z(-1.96, 1.0) == pytest.approx(30.0 - 1.96 * 5.0)

    def test_curve_covers_only_the_anchored_range(self) -> None:
        points = percentile_curve(self._model(), 0.0)  # z = 0 → the mean curve
        assert points[0][0] == pytest.approx(0.5)
        assert points[-1][0] == pytest.approx(1.5)
        assert points[0][1] == pytest.approx(20.0)
        assert points[-1][1] == pytest.approx(40.0)

    def test_malformed_models_are_rejected(self) -> None:
        with pytest.raises(ValueError, match="two anchors"):
            BsaBandModel(bands=(BsaBand(1.0, 30.0, 5.0),), source="x")
        with pytest.raises(ValueError, match="positive"):
            BsaBandModel(
                bands=(BsaBand(0.5, 30.0, 0.0), BsaBand(1.0, 30.0, 5.0)),
                source="x",
            )


class TestGaModel:
    def test_fetal_bands_interpolate_and_refuse_extrapolation(self) -> None:
        model = GaBandModel(
            bands=(GaBand(20.0, 3.0, 0.5), GaBand(40.0, 6.0, 0.8)),
            source="test fetal",
        )
        at_20 = model.zscore(3.0, 20.0)
        assert at_20 is not None
        assert at_20.z == pytest.approx(0.0)
        at_30 = model.zscore(4.5, 30.0)  # halfway: mean 4.5
        assert at_30 is not None
        assert at_30.z == pytest.approx(0.0)
        assert model.zscore(3.0, 42.0) is None

    def test_anchors_must_grow(self) -> None:
        with pytest.raises(ValueError, match="grow"):
            GaBandModel(bands=(GaBand(30.0, 3.0, 0.5), GaBand(20.0, 6.0, 0.8)), source="x")


class TestFormatting:
    def test_the_sign_is_kept_and_visible(self) -> None:
        assert format_z(1.234) == "+1.23"
        assert format_z(-0.5) == "-0.50"
        assert format_z(0.0) == "+0.00"

    def test_percentile_tag_is_clamped(self) -> None:
        assert percentile_label(0.0001) == "P1"
        assert percentile_label(99.6) == "P99"
        assert percentile_label(50.0) == "P50"

    def test_the_round_trip_is_monotone(self) -> None:
        assert percentile_to_z(50.0) == pytest.approx(0.0)
        low, high = percentile_to_z(3.0), percentile_to_z(97.0)
        assert z_to_percentile(low) == pytest.approx(3.0, rel=1e-2)
        assert z_to_percentile(high) == pytest.approx(97.0, rel=1e-2)
