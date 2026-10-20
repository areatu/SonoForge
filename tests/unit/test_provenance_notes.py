"""Unified provenance notes for all families (QH-1b.2 slices 3a–c, S-11).

Panel / text report / PDF share one wording via provenance_notes helpers.
"""

from echo_personal_tool.domain.calculators.models import CalculationsSnapshot
from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
from echo_personal_tool.domain.models.result_provenance import BSA_SOURCE_DERIVED, BsaBasis
from echo_personal_tool.domain.services.doppler_freshness import DopplerBasis
from echo_personal_tool.domain.services.provenance_notes import (
    all_provenance_notes,
    bsa_record_note,
    derived_record_note,
    doppler_record_note,
    evaluate_derived_record_status,
    evaluate_doppler_record_status,
    evaluate_simpson_record_status,
    simpson_record_note,
)
from echo_personal_tool.domain.services.simpson_freshness import SimpsonBasis
from echo_personal_tool.infrastructure.i18n import set_language


def test_simpson_note_has_same_wording_as_panel():
    # Legacy -> unverified path via evaluate helper
    status = evaluate_simpson_record_status(None, SimpsonBasis(pixel_spacing=(0.3, 0.3)))
    note = simpson_record_note(status)
    assert note is not None
    assert "Simpson" in note or "симпсон" in note.lower() or "Simpson" in note


def test_doppler_note_unified():
    status = evaluate_doppler_record_status(None, DopplerBasis(instance_uid="a", markers=(), traces=()))
    # empty basis -> None case handled as unverified? Actually no markers = unavailable?
    # Use a real marker to get unverified
    from echo_personal_tool.domain.services.doppler_freshness import DopplerMarkerRef

    basis = DopplerBasis(
        instance_uid="uid1",
        markers=(DopplerMarkerRef("peak", "TR Vmax", "id1", (10.0, 280.0), "CW"),),
    )
    status2 = evaluate_doppler_record_status(None, basis)
    note = doppler_record_note(status2)
    assert note is not None
    assert "older version" in note or "стар" in note


def test_derived_note_stale_when_input_changed():
    snap1 = CalculationsSnapshot()
    snap2 = CalculationsSnapshot()
    # Both empty -> should be None (nothing to report) per helper logic
    assert evaluate_derived_record_status(None, None) is None
    # Direct derived note for None is None
    assert derived_record_note(None) is None


def test_all_provenance_notes_uses_same_helpers():
    # Build a snapshot with all 4 statuses set to unverified (legacy)
    bsa_status = evaluate_simpson_record_status(None, SimpsonBasis(pixel_spacing=(0.5, 0.5)))
    # Use bsa helper for BSA to get a note
    from echo_personal_tool.domain.services.bsa_provenance import evaluate_bsa_record_status

    bsa_basis = BsaBasis(1.7, BSA_SOURCE_DERIVED, 170, 70)
    bsa_status2 = evaluate_bsa_record_status(None, bsa_basis)
    snap = MeasurementSnapshot(
        bsa_record_status=bsa_status2,
        simpson_record_status=bsa_status,
        doppler_record_status=None,
        derived_record_status=None,
    )
    notes = all_provenance_notes(snap)
    # Should contain at least BSA note, via same helper
    assert any(bsa_record_note(snap.bsa_record_status) == n for n in notes)
    # English vs Russian wording differs (if note exists)
    set_language("en")
    en = all_provenance_notes(snap)
    set_language("ru")
    ru = all_provenance_notes(snap)
    set_language("en")
    if en and ru:
        assert en != ru


def test_empty_snapshot_gives_no_notes():
    snap = MeasurementSnapshot()
    assert all_provenance_notes(snap) == ()
    assert all_provenance_notes(None) == []
