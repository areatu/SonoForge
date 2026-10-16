"""UI-5 PR-0 / UA-14: linear-method LVM, not a mixture with 2D ranges.

Source: ASE/EACVI 2015 and the bundled references/images/01-LV.png,
row «ММ ЛЖ (г), М-режим». Indexed mass and other rows are outside this fix.
"""

import json

import jsonschema
import pytest
import yaml

from echo_personal_tool.constructor.models.reference_model import ParameterModel
from echo_personal_tool.domain.services.reference_data_store import ReferenceDataStore, _param_to_dict
from echo_personal_tool.domain.services.report_builder import is_pathological


def _lvm(store):
    return next(param for *_, param in store.search("lvm") if param.id == "lvm")


@pytest.mark.parametrize("language", ["en", "ru"])
def test_linear_mass_ranges_method_and_roundtrip(language, tmp_path):
    store = ReferenceDataStore(language=language).load()
    param = _lvm(store)
    assert (param.norm_female.low, param.norm_female.high) == (67, 162)
    assert (param.norm_male.low, param.norm_male.high) == (88, 224)
    assert [(g.range_female.low, g.range_female.high) for g in param.gradations] == [
        (67, 162),
        (163, 186),
        (187, 210),
        (211, None),
    ]
    assert [(g.range_male.low, g.range_male.high) for g in param.gradations] == [
        (88, 224),
        (225, 258),
        (259, 292),
        (293, None),
    ]
    assert param.method and ("М-режим" if language == "ru" else "M-mode") in param.method
    wire = _param_to_dict(param)
    schema_path = store._yaml_path.parent / "references_schema.json"
    schema = json.loads(schema_path.read_text())
    jsonschema.validate(wire, {"$ref": "#/$defs/ParameterRef", "$defs": schema["$defs"]})
    assert ParameterModel.from_dict(wire).to_dict()["method"] == param.method
    # An unrelated edit/save must not silently drop the method from the handbook.
    path = tmp_path / "refs.yaml"
    path.write_text(store._yaml_path.read_text(), encoding="utf-8")
    edited = ReferenceDataStore(path).load()
    edited.update_param("lvm", "name", "LVM edited")
    assert _lvm(ReferenceDataStore(path).load()).method == param.method
    assert yaml.safe_load(path.read_text())["topics"]


@pytest.mark.parametrize(
    "sex,value,outside",
    [
        ("F", 66, True),
        ("F", 67, False),
        ("F", 150, False),
        ("F", 162, False),
        ("F", 163, True),
        ("M", 87, True),
        ("M", 88, False),
        ("M", 224, False),
        ("M", 225, True),
    ],
)
def test_report_mass_boundaries(sex, value, outside):
    assert is_pathological("lvm", value, sex) == (outside, "67–162" if sex == "F" else "88–224")
