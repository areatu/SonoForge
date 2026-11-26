"""ML.5 study context is bounded, Qt-free and subordinate to physician choices."""

from dataclasses import replace

import pytest

from echo_personal_tool.application.study_measurement_session import StudyMeasurementData
from echo_personal_tool.application.study_view_context import study_measurement_cues
from echo_personal_tool.domain.models import Contour, LinearMeasurement
from echo_personal_tool.domain.models.view_recognition import TTE_STANDARD_VIEWS as V
from echo_personal_tool.domain.models.view_recognition import ViewDecision
from echo_personal_tool.domain.models.view_recognition import ViewDecisionSource as Source
from echo_personal_tool.domain.services.study_view_resolver import (
    StudyViewClip,
    StudyViewCue,
    acquisition_seconds,
    resolve_study_views,
)
from echo_personal_tool.domain.services.view_recognition_workflow import ViewRecognitionWorkflow
from echo_personal_tool.infrastructure.view_decision_store import JsonViewDecisionStore
from tests.unit.test_view_recognition_workflow import InMemoryDecisionStore, StubRecognizer


def probabilities(**values):
    return tuple(float(values.get(v, 0)) for v in V)


def clip(series="ambiguous", **values):
    return StudyViewClip(series, probabilities(**(values or {"PLAX": 0.45, "A4C": 0.55})))


def manual(series, view="A2C"):
    return ViewDecision("study", series, view, Source.MANUAL, 1.0, None)


def test_measurements_can_resolve_an_ambiguous_view_but_cannot_count_repeats_as_evidence():
    item = clip()
    before = resolve_study_views([item])[0]
    cue = StudyViewCue(item.series_uid, "plax_linear")
    after = resolve_study_views([item], cues=[cue])[0]
    assert before.view == "UNKNOWN" and before.confidence == pytest.approx(0.55)
    assert after.view == "PLAX" and after.confidence >= 0.6
    assert after.source is Source.AUTO_STUDY_CONTEXT
    assert resolve_study_views([item], cues=[cue] * 100) == (after,)
    rv = clip(A4C=0.45, RV_A4C=0.45, PLAX=0.1)
    assert resolve_study_views([rv], cues=[StudyViewCue(rv.series_uid, "rv_measurement")])[0].view == "UNKNOWN"


def test_chronology_uses_time_then_instance_metadata_and_never_guesses_file_order():
    sequence = [
        replace(clip("first", PLAX=1.0), acquisition_time="093000", instance_number=3),
        replace(clip("middle", PSAX=0.56, A3C=0.44), acquisition_time="093010", instance_number=2),
        replace(clip("last", A4C=1.0), acquisition_time="093020", instance_number=1),
    ]
    result = resolve_study_views(sequence)
    assert result[1].view == "PSAX" and result[1].confidence > 0.6
    reversed_input = resolve_study_views(sequence[::-1])
    assert reversed_input == result[::-1]
    by_number = [replace(c, acquisition_time=None, instance_number=i) for i, c in enumerate(sequence)]
    assert resolve_study_views(by_number)[1].view == "PSAX"
    no_order = [replace(c, acquisition_time=None, instance_number=None) for c in sequence]
    assert resolve_study_views(no_order)[1].view == "UNKNOWN"


@pytest.mark.parametrize("view", ["UNKNOWN", "A2C", "TEE"])
def test_manual_decisions_are_hard_immutable_boundaries_even_outside_tte_taxonomy(view):
    item = clip()
    choice = manual(item.series_uid, view)
    result = resolve_study_views(
        [item], manual_decisions={item.series_uid: choice}, cues=[StudyViewCue(item.series_uid, "plax_linear")]
    )[0]
    assert result.view == view and result.confidence == 1 and result.source is Source.MANUAL
    assert choice == manual(item.series_uid, view)


@pytest.mark.parametrize("confidence", [0.6, 0.75, 0.95])
def test_confident_visual_views_survive_reversed_protocol_and_contradictory_measurements(confidence):
    items = [
        replace(clip("later", SUBCOSTAL=1.0), instance_number=1),
        replace(clip("middle", A3C=confidence, PLAX=1 - confidence), instance_number=2),
        replace(clip("earlier", PLAX=1.0), instance_number=3),
    ]
    result = resolve_study_views(items, cues=[StudyViewCue("middle", "plax_linear")])[1]
    assert result.view == "A3C" and result.confidence == confidence and result.source is Source.AUTO


@pytest.mark.parametrize(
    "item",
    [
        clip(PLAX=1 / 7, PSAX=1 / 7, A4C=1 / 7, RV_A4C=1 / 7, A2C=1 / 7, A3C=1 / 7, SUBCOSTAL=1 / 7),
        replace(clip(), visual_view="UNKNOWN"),
        replace(clip(), out_of_distribution=True),
    ],
)
def test_unknown_and_ood_are_never_promoted_even_with_measurements_and_manual_neighbours(item):
    series = [
        replace(clip("left", PLAX=1.0), instance_number=0),
        replace(item, instance_number=1),
        replace(clip("right", PLAX=1.0), instance_number=2),
    ]
    result = resolve_study_views(
        series,
        manual_decisions={"left": manual("left", "PLAX"), "right": manual("right", "PLAX")},
        cues=[StudyViewCue(item.series_uid, "plax_linear")],
    )[1]
    assert result.view == "UNKNOWN" and result.reason == "visual_unknown"


def test_study_workflow_and_json_store_do_not_overwrite_manual_decisions(tmp_path):
    store = JsonViewDecisionStore(tmp_path)
    choice = manual("ambiguous")
    store.save(choice)
    original = next(tmp_path.iterdir()).read_bytes()
    workflow = ViewRecognitionWorkflow(StubRecognizer("PLAX", 1.0), store)
    decisions = workflow.suggest_study([clip()], study_uid="study", cues=[StudyViewCue("ambiguous", "plax_linear")])
    assert decisions == (choice,) and next(tmp_path.iterdir()).read_bytes() == original
    automatic = replace(choice, view="PLAX", source=Source.AUTO_STUDY_CONTEXT)
    workflow.save_decision(automatic)
    store.save(automatic)
    assert store.load("study", "ambiguous") == choice
    contextual = replace(automatic, series_uid="new-series")
    store.save(contextual)
    assert store.load("study", "new-series") == contextual
    store.save(replace(choice, view="RV_A4C"))
    assert store.load("study", "ambiguous").view == "RV_A4C"
    empty = InMemoryDecisionStore()
    suggestions = ViewRecognitionWorkflow(StubRecognizer("PLAX", 1.0), empty).suggest_study(
        [clip()], study_uid="study", cues=[StudyViewCue("ambiguous", "plax_linear")]
    )
    assert suggestions[0].source is Source.AUTO_STUDY_CONTEXT and empty.load("study", "ambiguous") is None


def test_measurement_projection_is_series_bound_and_ignores_pending_and_unbound_values():
    measurements = (
        LinearMeasurement("LVIDd", 10.0, 5.0, start=(1, 2), end=(3, 4), sop_instance_uid="one"),
        LinearMeasurement("TAPSE", 10.0, 5.0, start=(1, 2), end=(3, 4), sop_instance_uid="two"),
        LinearMeasurement("TAPSE", 10.0, 5.0, sop_instance_uid="unbound"),
    )
    contours = (
        Contour("ES", chamber="LA", view="A4C", points=[(1, 2)] * 3, sop_instance_uid="one"),
        Contour("ES", chamber="LA", view="A2C", points=[(1, 2)] * 3, sop_instance_uid="three"),
        Contour("ED", chamber="RV", sop_instance_uid="four", review_pending=True),
    )
    data = StudyMeasurementData(linear_measurements=measurements, contours=contours)
    mapping = {"one": "series-one", "two": "series-two", "three": "series-three", "four": "series-four"}
    result = set(study_measurement_cues(data, mapping))
    assert result == {
        StudyViewCue("series-one", "plax_linear"),
        StudyViewCue("series-two", "rv_measurement"),
        StudyViewCue("series-one", "la_biplane"),
        StudyViewCue("series-three", "la_biplane"),
    }


@pytest.mark.parametrize(
    "time,seconds",
    [
        ("093012.125", 34212.125),
        ("23", 82800.0),
        ("0930", 34200.0),
        ("240001", None),
        ("12:30:00", None),
        ("090099", None),
        (None, None),
    ],
)
def test_dicom_time_validation(time, seconds):
    assert acquisition_seconds(time) == seconds


def test_invalid_probability_or_manual_identity_cannot_silently_change_the_study():
    for values in ((1.0, 2.0), (float("nan"),) * 7, (0.0,) * 7, (-1.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0)):
        with pytest.raises(ValueError):
            resolve_study_views([replace(clip(), probabilities=values)])
    with pytest.raises(ValueError):
        resolve_study_views([clip(), clip()])
    with pytest.raises(ValueError):
        resolve_study_views([clip()], manual_decisions={"wrong": manual("ambiguous")})
    assert resolve_study_views([]) == ()
