"""The paediatric/fetal norms table (plan А.12, issue #650).

The shipped YAML is a *seed*: approximate, labelled, physician-editable.
These tests pin the loader contract (schema, sources, band parsing), the
routing of :func:`zscore_for` (BSA models for children, GA models for
fetal, ``None`` when the needed input is absent) and the honesty of the
shipped data itself: every entry names its seed source and every table
interpolates to the values the report will print.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.pediatric_norms import (
    DEFAULT_NORMS_PATH,
    PediatricNorms,
    PediatricNormsError,
    load_norms,
    parse_norms,
)
from echo_personal_tool.domain.services.zscore import BsaBandModel, GaBandModel

SEED_KEYS = ("lv.lvedd", "lv.lvesd", "lv.ivsd", "lv.lvpwd", "ao.annulus", "ao.sinus", "lv.edvi", "lv.mass_i", "la.lavi")
FETAL_KEYS = ("fetal.ao_root", "fetal.pa", "fetal.lv_dia", "fetal.rv_dia")


@pytest.fixture(scope="module")
def shipped() -> PediatricNorms:
    return load_norms()


class TestShippedSeed:
    def test_every_keyed_index_has_a_table(self, shipped: PediatricNorms) -> None:
        for mid in (*SEED_KEYS, *FETAL_KEYS):
            assert shipped.model_for(mid) is not None, mid

    def test_pediatric_tables_are_bsa_models(self, shipped: PediatricNorms) -> None:
        for mid in SEED_KEYS:
            assert isinstance(shipped.model_for(mid), BsaBandModel), mid

    def test_fetal_tables_are_ga_models(self, shipped: PediatricNorms) -> None:
        for mid in FETAL_KEYS:
            assert isinstance(shipped.model_for(mid), GaBandModel), mid

    def test_every_seed_names_its_unverified_source(self, shipped: PediatricNorms) -> None:
        for mid in shipped.measurement_ids():
            model = shipped.model_for(mid)
            assert model is not None and "seed" in model.source and "первоисточник" in model.source

    def test_the_seed_is_honestly_flagged_in_the_yaml(self) -> None:
        import yaml

        data = yaml.safe_load(DEFAULT_NORMS_PATH.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1
        for raw in data["models"].values():
            assert raw.get("verified") is False

    def test_the_seed_tables_are_monotone_in_body_size(self, shipped: PediatricNorms) -> None:
        """LV/aortic growth with BSA must not dip — a seed typo would show."""
        for mid in ("lv.lvedd", "lv.lvesd", "ao.annulus", "ao.sinus"):
            model = shipped.model_for(mid)
            assert isinstance(model, BsaBandModel)
            means = [band.mean for band in model.bands]
            assert means == sorted(means), mid
            assert all(band.sd > 0 for band in model.bands)


class TestRouting:
    def test_a_bsa_model_without_bsa_is_none(self, shipped: PediatricNorms) -> None:
        assert shipped.zscore_for("lv.lvedd", 34.0) is None
        assert shipped.zscore_for("lv.lvedd", 34.0, gestational_weeks=30.0) is None

    def test_a_ga_model_without_weeks_is_none(self, shipped: PediatricNorms) -> None:
        assert shipped.zscore_for("fetal.ao_root", 4.3) is None
        assert shipped.zscore_for("fetal.ao_root", 4.3, bsa_m2=1.0) is None

    def test_an_unknown_measurement_is_none(self, shipped: PediatricNorms) -> None:
        assert shipped.zscore_for("aorta.vti", 1.4, bsa_m2=1.0) is None

    def test_out_of_band_values_stay_none(self, shipped: PediatricNorms) -> None:
        assert shipped.zscore_for("lv.lvedd", 34.0, bsa_m2=3.0) is None


class TestParsing:
    def test_a_missing_source_is_rejected(self) -> None:
        with pytest.raises(PediatricNormsError, match="source"):
            parse_norms(
                {
                    "schema_version": 1,
                    "models": {"lv.lvedd": {"kind": "bsa_bands", "bands": [{"bsa": 0.5, "mean": 20, "sd": 4}]}},
                }
            )

    def test_an_unknown_kind_is_rejected(self) -> None:
        with pytest.raises(PediatricNormsError, match="kind"):
            parse_norms(
                {
                    "schema_version": 1,
                    "models": {"lv.lvedd": {"kind": "lms", "source": "x"}},
                }
            )

    def test_an_unsupported_schema_is_rejected(self) -> None:
        with pytest.raises(PediatricNormsError, match="schema_version"):
            parse_norms({"schema_version": 2, "models": {}})

    def test_missing_models_is_rejected(self) -> None:
        with pytest.raises(PediatricNormsError, match="models"):
            parse_norms({"schema_version": 1})
