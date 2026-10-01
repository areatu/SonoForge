"""Domain model of the Multiview session: two different clips side by side.

Multiview is *not* an ED/ES viewer for a single clip and not a comparison of
previous studies: it shows two different echocardiographic clips of the same
study (A4C + A2C, A4C + A3C, A4C + PLAX, stress-echo projections, ...).

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
    #: Study the clip belongs to; Multiview never mixes two studies.
    study_uid: str | None = None
    current_frame: int = 0
    markers: list[EventMarker] = field(default_factory=list)
    #: Bumped on every clip replacement; stale loader responses are dropped.
    generation: int = 0
    #: Last error message shown in the pane header (kept so the header can
    #: offer a retry instead of showing the previous clip under a new name).
    load_error: str | None = None

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
        """True when both panes hold a clip from the same study."""
        left = self.pane(PaneId.LEFT)
        right = self.pane(PaneId.RIGHT)
        if left.instance is None or right.instance is None:
            return False
        if not left.study_uid or not right.study_uid:
            # Unknown study: allow, the presenter decides before loading.
            return True
        return left.study_uid == right.study_uid
