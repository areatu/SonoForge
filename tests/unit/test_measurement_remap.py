"""QH-1c: complete, unambiguous local-media import; never DICOM fuzzy matching."""

from copy import deepcopy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from echo_personal_tool.domain.models.result_provenance import (
    CalibrationRef,
    MethodIdentity,
    ResultProvenance,
    SourceIdentity,
)
from echo_personal_tool.infrastructure.measurement_codec import FIELDS, MeasurementStorageError, dumps, loads
from echo_personal_tool.infrastructure.measurement_remap import INSTANCE_FIELDS, prepare_import
from tests.unit.test_measurement_repository import SOP, SOURCES, complete_data, record

OLD = "local:" + "a" * 16
NEW = "local:" + "b" * 16
TARGET = "2.25.new-opaque-id"


def case():
    original = record(complete_data())
    original["study_uid"] = OLD
    prov = ResultProvenance(
        "result-stable",
        MethodIdentity("test"),
        source=SourceIdentity(OLD, SOP, "old-series", frame_index=0, fingerprint="a" * 64),
        calibration=(CalibrationRef("pixel", source_instance_uid=SOP),),
    )
    original["data"] = replace(original["data"], result_provenance=(prov,))
    study = SimpleNamespace(
        study_uid=NEW,
        series=(
            SimpleNamespace(
                instances=(SimpleNamespace(sop_instance_uid=TARGET, media_format="png", series_uid="new-series"),)
            ),
        ),
    )
    return original, study, {TARGET: deepcopy(SOURCES[SOP])}


def test_all_source_fields_and_provenance_remap_without_touching_inputs():
    original, study, sources = case()
    before = deepcopy(original)
    output, count = prepare_import(original, study, sources)
    assert count == 1 and output["study_uid"] == NEW
    assert output["sources"] == sources
    data = output["data"]
    for field in ("contours", "linear_measurements", "vessel_measurements"):
        assert getattr(data, field)[0].sop_instance_uid == TARGET
        assert replace(getattr(data, field)[0], sop_instance_uid=SOP) == getattr(before["data"], field)[0]
    assert set(INSTANCE_FIELDS) == {f for f in FIELDS if "by_instance" in f or f == "simpson_area_by_frame"}
    for field in INSTANCE_FIELDS:
        assert getattr(data, field)[0][0] == TARGET
        assert getattr(data, field)[0][1:] == getattr(before["data"], field)[0][1:]
    prov = data.result_provenance[0]
    assert prov.source == replace(
        before["data"].result_provenance[0].source, study_uid=NEW, sop_instance_uid=TARGET, series_uid="new-series"
    )
    assert prov.calibration[0].source_instance_uid == TARGET
    assert prov.result_id == "result-stable"
    assert data.strain == before["data"].strain
    assert loads(dumps(output)) == output
    assert original == before


@pytest.mark.parametrize(
    "fault",
    [
        "foreign-dicom",
        "target-dicom",
        "mixed",
        "missing",
        "hash",
        "frames",
        "spacing",
        "duplicate-old",
        "duplicate-live",
        "empty",
        "foreign-provenance",
        "dangling-calibration",
        "wrong-provenance-hash",
    ],
)
def test_refuses_unsafe_remap(fault):
    original, study, sources = case()
    if fault == "foreign-dicom":
        original["study_uid"] = "1.2.3"
    elif fault == "target-dicom":
        study.study_uid = "1.2.3"
    elif fault == "mixed":
        study.series[0].instances[0].media_format = "dicom"
    elif fault == "missing":
        sources.clear()
    elif fault in ("hash", "frames", "spacing"):
        key, value = {"hash": ("fingerprint", "b" * 64), "frames": ("frames", 4), "spacing": ("spacing", None)}[fault]
        sources[TARGET][key] = value
    elif fault == "duplicate-old":
        original["sources"] = {**original["sources"], "duplicate": SOURCES[SOP]}
    elif fault == "duplicate-live":
        sources["duplicate"] = sources[TARGET]
        study.series[0].instances += (SimpleNamespace(sop_instance_uid="duplicate", media_format="png"),)
    elif fault == "empty":
        original["sources"] = {}
    else:
        prov = original["data"].result_provenance[0]
        if fault == "foreign-provenance":
            prov = replace(prov, source=replace(prov.source, study_uid="1.2.999"))
        elif fault == "dangling-calibration":
            prov = replace(prov, calibration=(CalibrationRef("pixel", source_instance_uid="missing"),))
        else:
            prov = replace(prov, source=replace(prov.source, fingerprint="b" * 64))
        original["data"] = replace(original["data"], result_provenance=(prov,))
    before = deepcopy(original)
    with pytest.raises(MeasurementStorageError):
        prepare_import(original, study, sources)
    assert before == original
