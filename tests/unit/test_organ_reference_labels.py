"""Organ measurements meet the handbook (item 11 of the 2026-11-06 list).

The renal, abdominal and thyroid profiles added measurements that the report
shows with a reference link.  A link is only useful if the handbook really has
the parameter, in *both* display languages, and if the two similar kidney sizes
(«толщина почки» and «толщина паренхимы») do not collapse into one entry — the
owner asked for them as separate values.
"""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.measurement_catalog import MEASUREMENTS
from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore
from echo_personal_tool.domain.services.report_builder import _LABEL_TO_PARAM_ID

#: Measurement id → handbook parameter id, for the measurements the organ
#: profiles added (and the ones they share with the abdominal study).
ORGAN_PARAMETERS: tuple[tuple[str, str], ...] = (
    ("kidney.right_length", "kidney_length"),
    ("kidney.right_width", "kidney_width"),
    ("kidney.right_thickness", "kidney_thickness"),
    ("kidney.right_parenchyma", "kidney_cortex_thickness"),
    ("kidney.right_sinus", "kidney_sinus"),
    ("kidney.left_length", "kidney_length"),
    ("kidney.left_width", "kidney_width"),
    ("kidney.left_thickness", "kidney_thickness"),
    ("kidney.left_parenchyma", "kidney_cortex_thickness"),
    ("kidney.left_sinus", "kidney_sinus"),
    ("bladder.length", "bladder_length"),
    ("bladder.width", "bladder_width"),
    ("bladder.depth", "bladder_depth"),
    ("bladder.wall", "bladder_wall_thickness"),
    ("bladder.volume", "bladder_volume"),
    ("liver.llt", "liver_left_lobe_thickness"),
    ("liver.rlt", "liver_right_lobe_thickness"),
    ("liver.kvr", "liver_size"),
    ("gallbladder.length", "gallbladder_length"),
    ("gallbladder.width", "gallbladder_width"),
    ("gallbladder.wall", "gallbladder_wall_thickness"),
    ("portal_vein.diameter", "portal_vein_diameter"),
    ("bile_duct.diameter", "common_bile_duct_diameter"),
    ("pancreas.head", "pancreas_head_diameter"),
    ("pancreas.body", "pancreas_body_diameter"),
    ("pancreas.tail", "pancreas_tail_diameter"),
    ("pancreas.duct", "pancreatic_duct_width"),
    ("abd_aorta.diameter", "aorta_diameter_ant"),
    ("thyroid.r_thick", "thyroid_lobe_thickness"),
    ("thyroid.r_width", "thyroid_lobe_width"),
    ("thyroid.r_height", "thyroid_lobe_length"),
    ("thyroid.l_thick", "thyroid_lobe_thickness"),
    ("thyroid.l_width", "thyroid_lobe_width"),
    ("thyroid.l_height", "thyroid_lobe_length"),
    ("thyroid.isthmus", "thyroid_isthmus_thickness"),
    ("thyroid.volume", "thyroid_volume"),
)

_LANGUAGES = ("ru", "en")


@pytest.fixture(scope="module")
def stores() -> dict[str, ReferenceDataStore]:
    return {language: ReferenceDataStore(language=language).load() for language in _LANGUAGES}


def _param_ids(store: ReferenceDataStore, param_id: str) -> set[str]:
    return {param.id for _topic, _pathology, _gradation, param in store.search(param_id)}


@pytest.mark.parametrize("measurement_id,param_id", ORGAN_PARAMETERS, ids=[pair[0] for pair in ORGAN_PARAMETERS])
def test_each_organ_measurement_links_to_its_handbook_parameter(
    measurement_id: str, param_id: str, stores: dict[str, ReferenceDataStore]
) -> None:
    measurement = MEASUREMENTS[measurement_id]
    for language in _LANGUAGES:
        label = measurement.label(language).short
        assert _LABEL_TO_PARAM_ID.get(label.casefold()) == param_id, (measurement_id, language, label)
        assert param_id in _param_ids(stores[language], param_id), (measurement_id, language)


def test_kidney_thickness_is_not_the_parenchyma() -> None:
    """Two different sizes of the same organ must not share one handbook entry."""
    thickness = _LABEL_TO_PARAM_ID[MEASUREMENTS["kidney.right_thickness"].label("ru").short.casefold()]
    parenchyma = _LABEL_TO_PARAM_ID[MEASUREMENTS["kidney.right_parenchyma"].label("ru").short.casefold()]
    sinus = _LABEL_TO_PARAM_ID[MEASUREMENTS["kidney.right_sinus"].label("ru").short.casefold()]
    assert len({thickness, parenchyma, sinus}) == 3


def test_the_organ_parameters_carry_a_unit_in_both_languages(stores: dict[str, ReferenceDataStore]) -> None:
    for language in _LANGUAGES:
        store = stores[language]
        for _measurement_id, param_id in ORGAN_PARAMETERS:
            params = [param for *_rest, param in store.search(param_id) if param.id == param_id]
            assert params, (language, param_id)
            assert params[0].unit, (language, param_id)


def test_the_bladder_wall_has_the_three_millimetre_limit(stores: dict[str, ReferenceDataStore]) -> None:
    for language in _LANGUAGES:
        params = [param for *_rest, param in stores[language].search("bladder_wall_thickness")]
        norm = params[0].norm_male
        assert norm is not None
        assert norm.high == pytest.approx(3.0)
