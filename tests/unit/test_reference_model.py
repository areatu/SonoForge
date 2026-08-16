"""Tests for constructor reference models."""

from echo_personal_tool.constructor.models.reference_model import (
    NormRangeModel,
    ParameterGradationModel,
    ParameterModel,
    ReferenceModel,
)


def test_parameter_gradation_model_roundtrip():
    param = ParameterModel(
        id="lvm",
        name="LVM",
        unit="г",
        norm_male=NormRangeModel(low=88, high=224),
        gradations=[
            ParameterGradationModel(
                name="Норма",
                range_male=NormRangeModel(low=88, high=224),
                range_female=NormRangeModel(low=66, high=150),
            ),
            ParameterGradationModel(
                name="Лёгкое увеличение",
                range_male=NormRangeModel(low=225, high=258),
                range_female=NormRangeModel(low=151, high=171),
            ),
        ],
    )
    d = param.to_dict()
    assert d["gradations"][0]["name"] == "Норма"
    assert d["gradations"][0]["range_male"]["low"] == 88
    assert d["gradations"][1]["range_female"]["low"] == 151


def test_parameter_gradation_from_dict():
    d = {
        "id": "lvm",
        "name": "LVM",
        "unit": "г",
        "gradations": [
            {"name": "Норма", "range_male": {"low": 88, "high": 224}},
            {"name": "Тяжёлое", "range_male": {"low": 293}},
        ],
    }
    param = ParameterModel.from_dict(d)
    assert len(param.gradations) == 2
    assert param.gradations[0].name == "Норма"
    assert param.gradations[1].range_male.low == 293


def test_reference_model_yaml_roundtrip():
    model = ReferenceModel.from_yaml(
        """topics:
- name: Test
  slug: test
  pathologies:
  - name: P1
    slug: p1
    parameters:
    - id: param1
      name: Param 1
      gradations:
      - name: Норма
        range_male: {low: 1, high: 10}
"""
    )
    topic = model.topics[0]
    param = topic.pathologies[0].parameters[0]
    assert len(param.gradations) == 1
    assert param.gradations[0].range_male.low == 1

    yaml_out = model.to_yaml()
    assert "gradations" in yaml_out
    assert "range_male" in yaml_out
