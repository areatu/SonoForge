"""Tests for ReferenceDataStore."""

from __future__ import annotations

import pytest

from echo_personal_tool.domain.services.reference_data_store import (
    NormRange,
    ReferenceDataStore,
)

_SAMPLE_YAML = """
topics:
  - name: Аортальный клапан
    slug: aortic_valve
    pathologies:
      - name: Недостаточность (АН)
        slug: aortic_regurgitation
        image_path: pisa_ar.png
        gradations:
          - name: Лёгкая
            parameters:
              - id: ar_eroa
                name: EROA
                unit: см²
                norm_male: {low: null, high: 0.10}
                pathology_desc: "<0.10"
                source: "ASE 2017"
          - name: Тяжёлая
            parameters:
              - id: ar_eroa
                name: EROA
                unit: см²
                norm_male: {low: 0.30, high: null}
                pathology_desc: "≥0.30"
                source: "ASE 2017"
      - name: Стеноз (АС)
        slug: aortic_stenosis
        gradations:
          - name: Умеренный
            parameters:
              - id: as_vmax
                name: Vmax
                unit: м/с
                norm_male: {low: null, high: 2.5}
                pathology_desc: "3.0-3.9"
                source: "ESC 2021"
  - name: Левый желудочек
    slug: left_ventricle
    pathologies:
      - name: Норма
        slug: normal
        parameters:
          - id: lvef
            name: Фракция выброса (LVEF)
            unit: "%"
            norm_male: {low: 52, high: 72}
            norm_female: {low: 54, high: 74}
            source: "ASE 2015"
          - id: lvedvi
            name: Конечно-диастолический объём
            unit: мл/м²
            norm_male: {low: 37, high: 97}
            norm_female: {low: 32, high: 87}
            source: "ASE 2015"
"""


@pytest.fixture
def store(tmp_path):
    path = tmp_path / "test_refs.yaml"
    path.write_text(_SAMPLE_YAML, encoding="utf-8")
    return ReferenceDataStore(str(path)).load()


def test_loads_topics(store):
    topics = store.get_topics()
    assert len(topics) == 2
    assert topics[0].slug == "aortic_valve"
    assert topics[1].slug == "left_ventricle"


def test_get_topic(store):
    topic = store.get_topic("aortic_valve")
    assert topic is not None
    assert topic.name == "Аортальный клапан"


def test_get_topic_missing(store):
    assert store.get_topic("nonexistent") is None


def test_get_pathology(store):
    patho = store.get_pathology("aortic_valve", "aortic_regurgitation")
    assert patho is not None
    assert patho.name == "Недостаточность (АН)"
    assert patho.image_path == "pisa_ar.png"


def test_get_pathology_missing_topic(store):
    assert store.get_pathology("nonexistent", "norm") is None


def test_get_pathology_missing_pathology(store):
    assert store.get_pathology("aortic_valve", "nonexistent") is None


def test_gradations_loaded(store):
    patho = store.get_pathology("aortic_valve", "aortic_regurgitation")
    assert patho.gradations is not None
    assert len(patho.gradations) == 2
    assert patho.gradations[0].name == "Лёгкая"
    assert patho.gradations[1].name == "Тяжёлая"


def test_parameters_in_gradation(store):
    patho = store.get_pathology("aortic_valve", "aortic_regurgitation")
    grad = patho.gradations[0]
    assert len(grad.parameters) == 1
    assert grad.parameters[0].id == "ar_eroa"
    assert grad.parameters[0].norm_male.low is None
    assert grad.parameters[0].norm_male.high == 0.10


def test_parameters_no_gradation(store):
    patho = store.get_pathology("left_ventricle", "normal")
    assert patho.gradations is None
    assert patho.parameters is not None
    assert len(patho.parameters) == 2


def test_lookup_by_param_id(store):
    result = store.lookup("ar_eroa")
    assert result is not None
    topic, patho, grad = result
    assert topic.slug == "aortic_valve"
    assert patho.slug == "aortic_regurgitation"
    assert grad is not None
    assert grad.name == "Лёгкая"


def test_lookup_missing(store):
    assert store.lookup("nonexistent") is None


def test_search(store):
    results = store.search("eroa")
    assert len(results) >= 1
    topic, patho, grad, param = results[0]
    assert param.id == "ar_eroa"


def test_search_empty(store):
    assert store.search("zzznotfound") == []


def test_norm_range_none():
    nr = NormRange(low=None, high=35.0)
    assert nr.low is None
    assert nr.high == 35.0
