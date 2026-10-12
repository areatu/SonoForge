"""Domain model of the Multiview session: two different clips side by side.

Multiview is *not* an ED/ES viewer for a single clip and not a comparison of
previous studies: it shows two different echocardiographic clips side by side
(A4C + A2C, A4C + A3C, A4C + PLAX, stress-echo projections, ...).  Since Э10
(spec 2026-10-07 §6) the two clips may come from different studies/tabs when
their frame size and frame rate match (±5 %).

The module is intentionally Qt-free so the whole session/sync model can be
unit-tested without a QApplication.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from echo_personal_tool.domain.models.metadata import InstanceMetadata


class PaneId(str, Enum):
    """The two panes of a Multiview session."""

    LEFT = "left"
    RIGHT = "right"


class PlaybackMode(str, Enum):
    """How the two clips advance.

    ``INDEPENDENT``   – each clip is scrolled/played on its own.
    ``COMMON_WINDOW`` – both clips start together and run for the shorter of
                       the two remaining durations (time-based, not phase).
    ``EVENT_CYCLE``   – both clips are normalised between manually placed event
                       markers (phase-based).
    """

    INDEPENDENT = "independent"
    COMMON_WINDOW = "common_window"
    EVENT_CYCLE = "event_cycle"


class SyncBasis(str, Enum):
    """What the current playback mode actually guarantees."""

    INDEPENDENT = "independent"
    TIME = "time"
    PHASE = "phase"
    #: Frame-index fallback: panes step frame-by-frame together, but the
    #: phase of the cardiac cycle is NOT preserved — the UI must show the
    #: «без синхронизации по фазе» note (Э10 §6.4).
    INDEX = "index"


#: Relative fps tolerance for «одинаковая частота кадров» (±5 %, Э10 §6.1).
FPS_TOLERANCE = 0.05


class ClipComparison(Enum):
    """Geometry-based comparability of the two pane clips (Э10 §6.1).

    Clips are comparable when their decoded frames share the same size and
    their frame rates are within :data:`FPS_TOLERANCE` — NOT when they belong
    to the same study.  The same clip in both panes trivially compares equal.
    """

    MISSING = "missing"
    SAME_CLIP = "same_clip"
    OK = "ok"
    FPS_MISMATCH = "fps_mismatch"
    SIZE_MISMATCH = "size_mismatch"
    #: Geometry not measured yet (no decoded frame): do not block anything.
    UNKNOWN = "unknown"


def instance_fps(instance: InstanceMetadata | None) -> float | None:
    """Average frames per second of a clip, or None when timing is unknown."""
    if instance is None:
        return None
    if instance.frame_time_ms:
        return 1000.0 / instance.frame_time_ms
    vector = instance.frame_time_vector or ()
    if len(vector) > 1:
        total = sum(vector)
        if total > 0:
            return 1000.0 * len(vector) / total
    return None


#: Default event label: mitral valve closure. The user may rename it.
DEFAULT_EVENT_LABEL = "MK"

#: Longest event label accepted from the rename dialog.
MAX_EVENT_LABEL = 24

#: Global playback rate bounds of the shared transport (0.5×–2.0×).
MIN_GLOBAL_RATE = 0.5
MAX_GLOBAL_RATE = 2.0
DEFAULT_GLOBAL_RATE = 1.0

#: Pause held on the second marker of a cycle before looping back (ms).
ENDPOINT_HOLD_MS = 150

#: Rate outside this band is a heavy retiming: warn, never silently clamp.
SOFT_RATE_WARNING_BAND = 0.25


@dataclass(frozen=True)
class EventMarker:
    """A manually placed frame marker inside one pane.

    Markers are strictly ordered in time and local to the SOP Instance they
    were placed on; replacing the clip of a pane drops its markers.
    """

    frame_index: int
    label: str = DEFAULT_EVENT_LABEL

    def describe(self) -> str:
        return f"{self.label}#{self.frame_index + 1}"


@dataclass
class MultiViewPaneState:
    """Everything Multiview owns about one pane.

    The second pane receives pixels through its own loader request, so the
    ``generation`` counter guards against a late reply for a clip that has
    already been replaced (see the spec, §6.2 and §11).
    """

    instance: InstanceMetadata | None = None
    #: Study the clip belongs to; kept for the pane badge and diagnostics.
    study_uid: str | None = None
    current_frame: int = 0
    markers: list[EventMarker] = field(default_factory=list)
    #: Bumped on every clip replacement; stale loader responses are dropped.
    generation: int = 0
    #: Last error message shown in the pane header (kept so the header can
    #: offer a retry instead of showing the previous clip under a new name).
    load_error: str | None = None
    #: True while this pane runs its own playback in ``INDEPENDENT`` mode
    #: (spec §8.1).  Synchronised modes keep a single session-wide flag.
    playing: bool = False
    #: Decoded frame size as (width, height); None until the first frame lands.
    frame_size: tuple[int, int] | None = None
    #: Presentation badge «вкладка N · дата · модальность/вид» (Э10 §6.3).
    badge_text: str = ""

    @property
    def has_clip(self) -> bool:
        return self.instance is not None

    @property
    def total_frames(self) -> int:
        if self.instance is None:
            return 0
        return int(self.instance.number_of_frames or 0)

    @property
    def instance_uid(self) -> str | None:
        return None if self.instance is None else self.instance.sop_instance_uid

    def clear_markers(self) -> None:
        self.markers = []

    def marker_frames(self) -> list[int]:
        return [marker.frame_index for marker in self.markers]


@dataclass
class MultiViewSession:
    """Session-wide Multiview state (see spec §11)."""

    panes: dict[PaneId, MultiViewPaneState] = field(
        default_factory=lambda: {PaneId.LEFT: MultiViewPaneState(), PaneId.RIGHT: MultiViewPaneState()}
    )
    active_pane: PaneId | None = None
    playback_mode: PlaybackMode = PlaybackMode.INDEPENDENT
    #: 1 → ``MK1→MK2``; 2 → ``MK0→MK1→MK2``.
    selected_cycle_count: int = 1
    global_rate: float = DEFAULT_GLOBAL_RATE
    #: Start frame each pane contributes to the common window.
    common_start: dict[PaneId, int] = field(default_factory=lambda: {PaneId.LEFT: 0, PaneId.RIGHT: 0})
    is_playing: bool = False

    def pane(self, pane_id: PaneId) -> MultiViewPaneState:
        return self.panes[pane_id]

    def other(self, pane_id: PaneId) -> PaneId:
        return PaneId.RIGHT if pane_id is PaneId.LEFT else PaneId.LEFT

    def reset_common_starts(self) -> None:
        for pane_id in self.common_start:
            self.common_start[pane_id] = self.panes[pane_id].current_frame

    def clips_are_comparable(self) -> bool:
        """True when both clips are geometrically comparable (Э10 §6.1)."""
        return self.compare_clips() in (
            ClipComparison.OK,
            ClipComparison.SAME_CLIP,
            ClipComparison.UNKNOWN,
        )

    def compare_clips(self) -> ClipComparison:
        """Why the two pane clips are (not) comparable (Э10 §6.1).

        Comparability is about the pixels and the clock — same frame size and
        frame rate within ±5 % — not about the study the clips come from.
        Clips from two tabs/studies are therefore comparable when their
        geometry matches, which is what opens Multiview из двух вкладок.
        """
        left = self.pane(PaneId.LEFT)
        right = self.pane(PaneId.RIGHT)
        if left.instance is None or right.instance is None:
            return ClipComparison.MISSING
        if left.instance.sop_instance_uid == right.instance.sop_instance_uid:
            return ClipComparison.SAME_CLIP
        left_fps = instance_fps(left.instance)
        right_fps = instance_fps(right.instance)
        if left_fps is not None and right_fps is not None:
            mid = (left_fps + right_fps) / 2.0
            if mid > 0 and abs(left_fps - right_fps) > FPS_TOLERANCE * mid:
                return ClipComparison.FPS_MISMATCH
        if left.frame_size is not None and right.frame_size is not None:
            if left.frame_size != right.frame_size:
                return ClipComparison.SIZE_MISMATCH
            return ClipComparison.OK
        # Size not measured on both sides yet: nothing to complain about.
        return ClipComparison.UNKNOWN

    def sync_basis(self) -> SyncBasis:
        """What the selected playback mode actually guarantees (Э10 §6.4)."""
        if self.playback_mode is PlaybackMode.INDEPENDENT:
            return SyncBasis.INDEPENDENT
        if self.playback_mode is PlaybackMode.EVENT_CYCLE:
            return SyncBasis.PHASE
        left = self.pane(PaneId.LEFT).instance
        right = self.pane(PaneId.RIGHT).instance
        if instance_fps(left) is not None and instance_fps(right) is not None:
            return SyncBasis.TIME
        return SyncBasis.INDEX
