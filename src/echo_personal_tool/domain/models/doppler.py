"""Domain models for Doppler measurements."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class DopplerPeakMarker:
    """One measured peak velocity.

    ``measurement_id`` identifies the *measurement act*, not the patient: it
    lets repeated measurements of the same parameter live side by side in one
    document (decision D-23) while an edit of an existing marker updates it in
    place.  Legacy records written before D-23 have an empty id and keep the
    old replace-by-label behavior.

    ``mode`` captures the acquisition mode the marker was measured in
    (``CW`` | ``PW`` | ``TDI``, empty when unknown): the viewer resolves it
    from the DICOM ``RegionDataType`` with an explicit manual override winning
    (Э2).  Storage stays in cm/s; the mode only selects display units
    (CW → m/s, PW/TDI → cm/s, unknown → by magnitude).

    ``sop_instance_uid`` and ``frame_index`` are the clip and frame the marker
    was drawn on (issue 555).  The marker is primary data; the report aggregates
    several markers into one Vmax/VTI row and must still be able to answer
    «откуда значение», so the identity travels with the marker instead of being
    dropped at the compute boundary.  Legacy records leave both empty.

    ``accepted`` is the explicit repeat-selection decision (issue 559): a bad
    or extrasystolic beat stays visible and stored, but its value is excluded
    from the mean, SD and CV.  It defaults to ``True`` so every legacy marker
    and every document written before the flag existed keeps contributing.
    """

    label: str
    time_ms: float
    velocity_cm_s: float
    measurement_id: str = ""
    mode: str = ""
    sop_instance_uid: str = ""
    frame_index: int | None = None
    accepted: bool = True


@dataclass(frozen=True)
class DopplerIntervalMarker:
    label: str
    start_time_ms: float
    end_time_ms: float
    measurement_id: str = ""
    #: Clip and frame of the interval (issue 555); empty on legacy records.
    sop_instance_uid: str = ""
    frame_index: int | None = None
    #: Explicit repeat selection (issue 559), see :class:`DopplerPeakMarker`.
    accepted: bool = True


@dataclass(frozen=True)
class DopplerTrace:
    """One traced VTI envelope.

    ``mode`` is the acquisition mode captured at trace time (see
    :class:`DopplerPeakMarker`); it feeds the display units of the
    trace-derived Vmax fallback.
    """

    label: str
    points: tuple[tuple[float, float], ...]
    measurement_id: str = ""
    mode: str = ""
    #: Clip and frame of the traced envelope (issue 555); empty on legacy records.
    sop_instance_uid: str = ""
    frame_index: int | None = None
    #: Explicit repeat selection (issue 559), see :class:`DopplerPeakMarker`.
    accepted: bool = True


@dataclass(frozen=True)
class DopplerMeasurementDTO:
    peaks: tuple[DopplerPeakMarker, ...]
    intervals: tuple[DopplerIntervalMarker, ...]
    traces: tuple[DopplerTrace, ...]
