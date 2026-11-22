"""Unified phase-source routing for cine ED/ES/HR (plan А.4, issue #642).

One port that answers a single question for every phase consumer — STE/strain,
diastology, myocardial work, the cycle services — *which source gated this
clip, and what are its ED/ES frames*: a valid ECG waveform (preferred, per the
clinical doctrine that tags beat image inference), the А.3 image phase field
(:mod:`phase_field`, built from the clip's own periodicity), or a hybrid of
the two when they agree. The output is one :class:`PhaseDecision` carrying a
frame-domain :class:`EcEDFrameMapping`, heart rate, confidence and the
warnings that explain the route — so switching sources is transparent: the
decision says *why* it went the way it went, and ``forced`` lets the user pin
a source in the UI without the router silently second-guessing.

Routing rules (the issue's step 2):

* valid ECG tags (R-peaks at/above the mapper's confidence threshold, frames
  mappable — ``frame_time_ms`` known) → ``ecg``;
* otherwise → ``image`` (the А.3 field; unusable input degrades to the
  mapper's sentinel mapping with confidence 0, never raises);
* ECG valid *and* the image field confident *and* both place the ED within
  ``_ED_AGREEMENT_FRAMES`` frames → ``hybrid``: ED/ES stay the ECG's (ECG
  wins on disagreement), confidence gets a modest agreement bonus, and the
  field travels along for consumers that want φ(t), not just two frames;
* ``forced`` overrides all of the above and *fails honestly*: forcing ECG
  without a usable waveform falls back to image with a
  ``forced_ecg_unavailable`` warning; forcing image ignores a usable ECG and
  says so (``ecg_ignored``).

The Doppler cycle service (``cardiac_cycle_service``) uses this contract for
its own ms-domain routing; cine consumers call :func:`resolve_phase_source`
directly.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Protocol

import numpy as np

from echo_personal_tool.domain.models.ecg import (
    EcEDFrameMapping,
    EcgWaveform,
    RPeakResult,
)
from echo_personal_tool.domain.services.ecg_ed_es_mapper import (
    map_rpeaks_to_frames,
)
from echo_personal_tool.domain.services.ecg_rpeak_detector import (
    detect_r_peaks_from_waveform,
)
from echo_personal_tool.domain.services.phase_field import (
    DEFAULT_MIN_CONFIDENCE,
    PhaseField,
    build_phase_field,
    phase_field_to_ed_es_mapping,
)

#: The force-source vocabulary — what ``PhaseRequest.forced`` accepts.
SOURCE_AUTO = "auto"
SOURCE_ECG = "ecg"
SOURCE_IMAGE = "image"
SOURCE_HYBRID = "hybrid"
FORCED_SOURCES = frozenset({SOURCE_AUTO, SOURCE_ECG, SOURCE_IMAGE})

#: Same gate as the ECG mapper's R-peak acceptance (its private default).
DEFAULT_ECG_CONFIDENCE_THRESHOLD = 0.4

#: ED agreement window (frames) for the hybrid route.
_ED_AGREEMENT_FRAMES = 1

#: Confidence bonus when the ECG and the image field agree on the ED.
_HYBRID_BONUS = 0.1


@dataclass(frozen=True)
class PhaseRequest:
    """Everything the router may need — consumers pass what they have.

    ``ecg`` / ``r_peak_result`` drive the ECG path; ``area_curve`` /
    ``frames`` / ``lv_masks`` drive the А.3 image field (any subset; the
    field fuses what it gets). ``forced`` is the UI's force-source choice.
    """

    n_frames: int
    frame_time_ms: float | None = None
    ecg: EcgWaveform | None = None
    r_peak_result: RPeakResult | None = None
    area_curve: np.ndarray | None = None
    frames: np.ndarray | None = None
    lv_masks: np.ndarray | None = None
    forced: str | None = None
    confidence_threshold: float = DEFAULT_ECG_CONFIDENCE_THRESHOLD
    min_image_confidence: float = DEFAULT_MIN_CONFIDENCE


@dataclass(frozen=True)
class PhaseDecision:
    """The one contract every phase consumer receives.

    ``mapping`` speaks the ``ecg_ed_es_mapper`` vocabulary (frame-domain
    ED/ES/cycle bounds; ``mapping.source`` mirrors the winning route).
    ``confidence`` is the route's own quality (R-peak confidence for ECG, the
    field's multiplicative confidence for image); ``heart_rate_bpm`` comes
    from the ECG R-R train or the field's median complete cycle.
    """

    source: str
    mapping: EcEDFrameMapping
    confidence: float
    heart_rate_bpm: float | None = None
    warnings: tuple[str, ...] = ()
    phase_field: PhaseField | None = None


class IPhaseSource(Protocol):
    """The routing seam: consumers depend on this, never on a concrete router."""

    def resolve(self, request: PhaseRequest) -> PhaseDecision: ...


class CinePhaseSource:
    """Default router: valid ECG tags → ecg, else the А.3 image field."""

    def resolve(self, request: PhaseRequest) -> PhaseDecision:
        warnings: list[str] = []
        forced = str(request.forced or SOURCE_AUTO).strip().lower()
        if forced not in FORCED_SOURCES:
            warnings.append("unknown_force_source")
            forced = SOURCE_AUTO
        n = int(request.n_frames)
        if n <= 0:
            warnings.append("no_frames")
            return PhaseDecision(
                source=SOURCE_IMAGE,
                mapping=EcEDFrameMapping(0, 0, 0, 0, source=SOURCE_IMAGE),
                confidence=0.0,
                heart_rate_bpm=None,
                warnings=tuple(sorted(set(warnings))),
            )

        peaks = self._usable_peaks(request)

        if forced == SOURCE_ECG:
            if peaks is None:
                warnings.append("forced_ecg_unavailable")
                return self._image_decision(request, warnings)
            return self._ecg_decision(peaks, request, n, warnings)

        # Probe the image route only when the caller actually supplied image
        # signals: probing nothing and calling it "unavailable" would make
        # every plain ECG clip carry a warning it did not earn.
        field = self._image_field(request)

        if forced == SOURCE_IMAGE:
            if peaks is not None:
                warnings.append("ecg_ignored")
            return self._image_decision(request, warnings, field)

        if peaks is None:
            warnings.append("no_usable_ecg")
            return self._image_decision(request, warnings, field)

        if field is None:
            if request.area_curve is not None or request.frames is not None or request.lv_masks is not None:
                warnings.append("image_unavailable")
            return self._ecg_decision(peaks, request, n, warnings)

        image_mapping = phase_field_to_ed_es_mapping(field)
        ecg_map = _ecg_mapping(peaks, request, n)
        if abs(image_mapping.ed_frame_index - int(ecg_map.ed_frame_index)) <= _ED_AGREEMENT_FRAMES:
            warnings.append("hybrid_agreement")
            bonus = _HYBRID_BONUS * float(field.confidence)
            confidence = min(1.0, (float(peaks.confidence) + float(field.confidence)) / 2 + bonus)
            warnings.extend(field.warnings)
            return PhaseDecision(
                source=SOURCE_HYBRID,
                mapping=ecg_map,
                confidence=confidence,
                heart_rate_bpm=_ecg_heart_rate(peaks),
                warnings=tuple(sorted(set(warnings))),
                phase_field=field,
            )
        warnings.append("image_disagrees")
        return self._ecg_decision(peaks, request, n, warnings)

    def _usable_peaks(self, request: PhaseRequest) -> RPeakResult | None:
        """R-peak train the ECG route can act on, or ``None``.

        "Usable" mirrors the ECG mapper: R-peaks exist, confidence clears the
        threshold, and the clip's time base is known (without it the R-peak
        milliseconds cannot become frame indices).
        """
        peaks = request.r_peak_result
        if peaks is None and request.ecg is not None:
            peaks = detect_r_peaks_from_waveform(request.ecg)
        if peaks is None or len(peaks.r_peak_indices) == 0:
            return None
        if float(peaks.confidence) < float(request.confidence_threshold):
            return None
        if request.frame_time_ms is None or float(request.frame_time_ms) <= 0:
            return None
        return peaks

    def _image_field(self, request: PhaseRequest) -> PhaseField | None:
        """А.3 field from the supplied signals, ``None`` when it is unusable.

        Unusable means: no accepted cycles (the field itself zeroes them on
        low confidence) or nothing to build from at all. The field's own
        warnings still travel on the decision — the consumer sees *why*.
        """
        has_input = request.area_curve is not None or request.frames is not None or request.lv_masks is not None
        if not has_input:
            return None
        field = build_phase_field(
            n_frames=int(request.n_frames),
            frame_time_ms=request.frame_time_ms,
            frames=request.frames,
            area_curve=request.area_curve,
            lv_masks=request.lv_masks,
            min_confidence=float(request.min_image_confidence),
        )
        if not field.cycles:
            return None
        return field

    def _image_decision(
        self,
        request: PhaseRequest,
        warnings: list[str],
        field: PhaseField | None = None,
    ) -> PhaseDecision:
        """Decision for the image route, degrading honestly without a field."""
        if field is None:
            field = self._image_field(request)
        if field is None:
            warnings.append("no_phase_source")
            warnings.append("no_periodic_signal")
            n = int(request.n_frames)
            return PhaseDecision(
                source=SOURCE_IMAGE,
                mapping=EcEDFrameMapping(
                    ed_frame_index=0,
                    es_frame_index=max(1, n // 3),
                    cycle_start_frame=0,
                    cycle_end_frame=max(0, n - 1),
                    source=SOURCE_IMAGE,
                ),
                confidence=0.0,
                heart_rate_bpm=None,
                warnings=tuple(sorted(set(warnings))),
            )
        warnings.extend(field.warnings)
        return PhaseDecision(
            source=SOURCE_IMAGE,
            mapping=phase_field_to_ed_es_mapping(field),
            confidence=float(field.confidence),
            heart_rate_bpm=field.heart_rate_bpm,
            warnings=tuple(sorted(set(warnings))),
            phase_field=field,
        )

    def _ecg_decision(
        self,
        peaks: RPeakResult,
        request: PhaseRequest,
        n: int,
        warnings: list[str],
    ) -> PhaseDecision:
        """Decision for the ECG route (the mapper's ED ≈ R-peak convention)."""
        return PhaseDecision(
            source=SOURCE_ECG,
            mapping=_ecg_mapping(peaks, request, n),
            confidence=float(peaks.confidence),
            heart_rate_bpm=_ecg_heart_rate(peaks),
            warnings=tuple(sorted(set(warnings))),
        )


def _ecg_mapping(peaks: RPeakResult, request: PhaseRequest, n: int) -> EcEDFrameMapping:
    """Frame-domain mapping of the R-peak train (the mapper's ED ≈ R rule)."""
    frame_time = float(request.frame_time_ms or 0.0)
    return replace(
        map_rpeaks_to_frames(peaks, frame_time, n),
        r_peak_result=peaks,
    )


def _ecg_heart_rate(peaks: RPeakResult) -> float | None:
    rate = float(peaks.heart_rate_bpm)
    return rate if rate > 0 else None


# --- Session force-source store (the А.4 UI's choice) -----------------------
#
# ``MainWindow`` and ``AppController`` are line/field-ratcheted (issue #474),
# so the STE dialog's force-source choice is kept here — the one module every
# layer may import — instead of another tracked instance attribute. The store
# is session-scoped by design: it resets to "auto" on restart.
_FORCED_PREFS = (SOURCE_AUTO, SOURCE_ECG, SOURCE_IMAGE)
_last_forced: str | None = None


def get_forced_phase_source() -> str | None:
    """The session's force-source choice ("auto"/"ecg"/"image"); None = unset."""
    return _last_forced


def store_forced_phase_source(pref: str | None) -> str:
    """Persist the dialog's choice; returns the canonical stored value."""
    global _last_forced
    value = str(pref or SOURCE_AUTO).strip().lower()
    _last_forced = value if value in _FORCED_PREFS else SOURCE_AUTO
    return _last_forced


def resolve_phase_source(
    *,
    n_frames: int,
    frame_time_ms: float | None = None,
    ecg: EcgWaveform | None = None,
    r_peak_result: RPeakResult | None = None,
    area_curve: np.ndarray | None = None,
    frames: np.ndarray | None = None,
    lv_masks: np.ndarray | None = None,
    forced: str | None = None,
    confidence_threshold: float = DEFAULT_ECG_CONFIDENCE_THRESHOLD,
    min_image_confidence: float = DEFAULT_MIN_CONFIDENCE,
) -> PhaseDecision:
    """Build a :class:`PhaseRequest` from keyword arguments and route it.

    The thin entry point consumers call; arguments are exactly
    :class:`PhaseRequest`'s fields.
    """
    request = PhaseRequest(
        n_frames=n_frames,
        frame_time_ms=frame_time_ms,
        ecg=ecg,
        r_peak_result=r_peak_result,
        area_curve=area_curve,
        frames=frames,
        lv_masks=lv_masks,
        forced=forced,
        confidence_threshold=confidence_threshold,
        min_image_confidence=min_image_confidence,
    )
    return CinePhaseSource().resolve(request)
