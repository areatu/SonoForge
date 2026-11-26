"""Application composition root: assemble runtime services outside constructors.

``MainWindow`` and ``AppController`` previously constructed their own object
graph inside ``__init__`` — reading user preferences from disk, probing
physical RAM via ``psutil``, resolving host directories and instantiating
``OnnxInferenceEngine`` regardless of the active product profile.

This module centralises that assembly into :class:`AppServices` and
:func:`build_app_services` (without importing Qt widgets), so:

* ``main.py`` and ``__main_presenter__.py`` are the only production entry
  points that build the service graph;
* the Presenter profile is expressed directly as a differently wired
  :class:`AppServices` instance (disabled AI segmenter, disabled recent-folder
  history, profile-clamped preferences and capability record);
* tests construct ``AppController`` hermetically via ``app_services(tmp_path)``
  or :func:`in_memory_app_services` without touching user settings or the home
  directory.
"""

from __future__ import annotations

import os
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TypeVar
from weakref import WeakKeyDictionary

import numpy as np
import psutil

from echo_personal_tool.application.analysis_jobs import AnalysisJobs
from echo_personal_tool.application.calculator_inputs import CalculatorInputStore
from echo_personal_tool.application.ctmr_slice_requests import CtMrSliceRequests
from echo_personal_tool.application.frame_cache import FrameCache
from echo_personal_tool.application.fusion_jobs import AssistJobs, FusionJobs
from echo_personal_tool.application.key_images import KeyImageService
from echo_personal_tool.application.measurement_persistence import MeasurementPersistence
from echo_personal_tool.application.preferences_contract import UserPreferences
from echo_personal_tool.application.profile_settings import (
    ProfileCapabilities,
    active_profile_name,
    get_profile_capabilities,
    profile_display_name,
)
from echo_personal_tool.application.recent_folders import (
    RecentFolderEntry,
    RecentFolderStore,
    make_recent_folder_store,
)
from echo_personal_tool.application.segmentation_jobs import SegmentationJobs
from echo_personal_tool.application.server_io import OrthancCache, make_orthanc_session_cache
from echo_personal_tool.application.state_manager import StateManager
from echo_personal_tool.application.study_measurement_session import StudyMeasurementSessionStore
from echo_personal_tool.application.user_preferences import (
    default_user_preferences,
    load_user_preferences,
    save_user_preferences,
)
from echo_personal_tool.application.user_session import UserSessionService
from echo_personal_tool.domain.models.audit import AuditAction
from echo_personal_tool.domain.models.user import Permission
from echo_personal_tool.domain.models.view_recognition import RecognizedView
from echo_personal_tool.domain.ports import IOnnxSegmenter, IViewRecognizer
from echo_personal_tool.domain.services.view_recognition_workflow import (
    ViewRecognitionWorkflow,
)
from echo_personal_tool.infrastructure.system_profiler import (
    PlaybackConfig,
    detect_playback_config,
)
from echo_personal_tool.infrastructure.view_decision_store import JsonViewDecisionStore


def make_ctmr_slice_requests() -> CtMrSliceRequests:
    """Compose the opt-in CT/MR lazy reader; caller owns its lifecycle."""
    from echo_personal_tool.infrastructure.ctmr_slice_reader import read_ctmr_slice, source_is_current

    return CtMrSliceRequests(read_ctmr_slice, source_is_current)


PROFILE_FULL = "full"
PROFILE_PRESENTER = "presenter"

#: Fallback RAM cap (2 GiB) when ``psutil.virtual_memory()`` is unavailable.
FALLBACK_RAM_CAP_BYTES = 2 * 1024 * 1024 * 1024

#: Default per-preference floor (64 MiB) when a minimal preference stub omits ``playback_max_cache_mb``.
DEFAULT_PLAYBACK_CACHE_MB = 64

#: Deterministic playback tuning for hermetic in-memory controller construction.
DEFAULT_HERMETIC_PLAYBACK_CONFIG = PlaybackConfig(
    prefetch_radius=10,
    min_buffer=5,
    batch_size=8,
    max_lag_frames=4,
    evict_window=20,
    scroll_debounce_ms=50,
    scroll_batch_size=8,
    prefetch_seconds=1.5,
)


@dataclass(frozen=True)
class AppPaths:
    """Filesystem locations injected into the application service graph."""

    measurements_dir: Path
    orthanc_cache_root: Path
    models_dir: Path
    settings_ini: Path | None = None
    users_dir: Path | None = None

    @classmethod
    def under(cls, root: Path) -> AppPaths:
        """Place every data/cache/model directory inside ``root`` (for tests and sandboxes)."""
        base = Path(root)
        return cls(
            measurements_dir=base / "measurements",
            orthanc_cache_root=base / "orthanc-cache",
            models_dir=base / "models",
            settings_ini=base / "preferences.ini",
            users_dir=base / "users",
        )

    @classmethod
    def for_host(cls) -> AppPaths:
        """Resolve production directories from the profile-aware path adapter."""
        from echo_personal_tool.infrastructure import paths as host_paths

        return cls(
            measurements_dir=host_paths.measurements_dir(),
            orthanc_cache_root=host_paths.orthanc_cache_root(),
            models_dir=host_paths.models_dir(),
            settings_ini=None,
            users_dir=host_paths.users_dir(),
        )


@dataclass(frozen=True)
class UnifiedMemoryBudget:
    """Global concurrent memory accounting for cache, decode, render, and tracking."""

    playback_config: PlaybackConfig
    ram_cap_bytes: int
    max_cache_bytes: int
    full_cine_bytes: int
    comparison_bytes: int
    decode_gate_bytes: int
    clinical_bytes: int = 0

    @property
    def tracking_render_overhead(self) -> int:
        used = (
            self.max_cache_bytes
            + self.full_cine_bytes
            + self.comparison_bytes
            + self.decode_gate_bytes
            + self.clinical_bytes
        )
        return max(0, self.ram_cap_bytes - used)


@dataclass(frozen=True)
class FrameCacheBudget:
    """Legacy compatibility: delegates to UnifiedMemoryBudget."""

    playback_config: PlaybackConfig
    ram_cap_bytes: int
    max_cache_bytes: int

    @classmethod
    def from_unified(cls, unified: UnifiedMemoryBudget) -> FrameCacheBudget:
        return cls(
            playback_config=unified.playback_config,
            ram_cap_bytes=unified.ram_cap_bytes,
            max_cache_bytes=unified.max_cache_bytes,
        )


@dataclass(frozen=True)
class DisabledOnnxSegmenter:
    """No-op :class:`IOnnxSegmenter` for Presenter builds and hermetic tests."""

    def is_available(self) -> bool:
        return False

    def segment(self, frame: np.ndarray) -> np.ndarray:
        del frame
        raise RuntimeError("AI segmentation is disabled in the active profile")


@dataclass(frozen=True)
class DisabledViewRecognizer:
    """No-op :class:`IViewRecognizer` until the ONNX classifier (step 2) lands.

    Returns ``UNKNOWN`` with zero confidence, so the step-4 UI hook stays
    wired end-to-end (badge, override, persist) without a trained model.
    """

    def recognize(self, frames: Sequence[np.ndarray]) -> RecognizedView:
        del frames
        return RecognizedView("UNKNOWN", 0.0)


@dataclass(frozen=True)
class _HermeticRecentEntry:
    path: str
    pinned: bool = False

    @property
    def exists(self) -> bool:
        try:
            return Path(self.path).is_dir()
        except OSError:
            return False


class _InMemoryRecentFolderStore:
    """Hermetic :class:`RecentFolderStore` that never touches ``QSettings`` or disk."""

    def __init__(self, *, enabled: bool = False) -> None:
        self._enabled = enabled
        self._items: list[_HermeticRecentEntry] = []

    @property
    def enabled(self) -> bool:
        return self._enabled

    def entries(self) -> Sequence[RecentFolderEntry]:
        return tuple(self._items) if self._enabled else ()

    def last_folder(self) -> str:
        if not self._enabled or not self._items:
            return ""
        return self._items[0].path

    def reload(self) -> None:
        return None

    def record(self, path: str | Path) -> None:
        if not self._enabled:
            return
        normalized = os.path.normpath(str(path).strip())
        if not normalized:
            return
        pinned = self.is_pinned(normalized)
        self._items = [item for item in self._items if item.path != normalized]
        self._items.insert(0, _HermeticRecentEntry(path=normalized, pinned=pinned))

    def is_pinned(self, path: str | Path) -> bool:
        normalized = os.path.normpath(str(path).strip())
        return any(item.path == normalized and item.pinned for item in self._items)

    def toggle_pinned(self, path: str | Path) -> bool:
        if not self._enabled:
            return False
        normalized = os.path.normpath(str(path).strip())
        updated: list[_HermeticRecentEntry] = []
        result = False
        for item in self._items:
            if item.path == normalized:
                result = not item.pinned
                updated.append(_HermeticRecentEntry(path=item.path, pinned=result))
            else:
                updated.append(item)
        self._items = updated
        return result

    def remove(self, path: str | Path) -> None:
        normalized = os.path.normpath(str(path).strip())
        self._items = [item for item in self._items if item.path != normalized]

    def clear(self, *, keep_pinned: bool = False) -> None:
        if keep_pinned:
            self._items = [item for item in self._items if item.pinned]
        else:
            self._items.clear()


@dataclass(frozen=True)
class AppIoFacades:
    """Application-owned I/O facades wired for the active profile and paths."""

    recent_folders: RecentFolderStore
    orthanc_cache: OrthancCache
    load_preferences: Callable[[], UserPreferences]
    save_preferences: Callable[[UserPreferences], None]
    dicom_io_module: type | object
    dicom_export_module: type | object
    report_export_module: type | object
    saved_records_module: type | object
    server_io_module: type | object


@dataclass(frozen=True)
class AppServices:
    """Immutable bundle of application state stores, budgets and I/O facades."""

    profile: str
    display_name: str
    capabilities: ProfileCapabilities
    preferences: UserPreferences
    paths: AppPaths
    state_manager: StateManager
    measurement_store: StudyMeasurementSessionStore
    calculator_inputs: CalculatorInputStore
    persistence: MeasurementPersistence
    key_images: KeyImageService
    unified_budget: UnifiedMemoryBudget
    frame_cache: FrameCache
    segmenter: IOnnxSegmenter
    io: AppIoFacades
    a2c_segmenter: IOnnxSegmenter = field(default_factory=DisabledOnnxSegmenter)
    user_session: UserSessionService | None = None
    analysis_jobs: AnalysisJobs = field(default_factory=AnalysisJobs)
    segmentation_jobs: SegmentationJobs = field(default_factory=SegmentationJobs)
    fusion_jobs: FusionJobs = field(default_factory=FusionJobs)
    assist_jobs: AssistJobs = field(default_factory=AssistJobs)
    #: View classifier behind the ``IViewRecognizer`` port (PR-A). Disabled
    #: until the ONNX adapter (#639 step 2) lands.
    view_recognizer: IViewRecognizer = field(default_factory=DisabledViewRecognizer)
    #: Step-4 workflow: suggest / override / restore view decisions.
    view_workflow: ViewRecognitionWorkflow = field(
        default_factory=lambda: ViewRecognitionWorkflow(
            DisabledViewRecognizer(), JsonViewDecisionStore(Path(tempfile.gettempdir()))
        )
    )
    #: Persistence directory of the view-decision store.
    view_decisions_dir: Path | None = None

    @property
    def cache_budget(self) -> FrameCacheBudget:
        """Legacy compatibility property for tests (P1.1 #545)."""
        return FrameCacheBudget.from_unified(self.unified_budget)


_CONTROLLER_SERVICES: WeakKeyDictionary[object, AppServices] = WeakKeyDictionary()


def bind_controller_services(controller: object, services: AppServices) -> None:
    """Associate ``services`` with ``controller`` without adding instance attributes."""
    _CONTROLLER_SERVICES[controller] = services


def services_of(controller: object) -> AppServices | None:
    """Return the :class:`AppServices` bound to ``controller``, if any."""
    try:
        return _CONTROLLER_SERVICES.get(controller)
    except TypeError:
        return None


def segmenter_for_view(controller: object, view: str, fallback: IOnnxSegmenter) -> IOnnxSegmenter:
    """Return the active view segmenter (A2C when available, else fallback)."""
    bound = services_of(controller)
    if view.upper() == "A2C" and bound is not None and bound.a2c_segmenter.is_available():
        return bound.a2c_segmenter
    return fallback


def analysis_jobs_of(controller: object) -> AnalysisJobs:
    """The composition-owned publication ledger for a bound controller."""
    services = services_of(controller)
    if services is None:
        raise RuntimeError("Controller services are not bound")
    return services.analysis_jobs


def segmentation_jobs_of(controller: object) -> SegmentationJobs:
    """The composition-owned auto-segmentation publication ledger."""
    services = services_of(controller)
    if services is None:
        raise RuntimeError("Controller services are not bound")
    return services.segmentation_jobs


def fusion_jobs_of(controller: object) -> FusionJobs:
    """The composition-owned temporal-fusion publication ledger."""
    services = services_of(controller)
    if services is None:
        raise RuntimeError("Controller services are not bound")
    return services.fusion_jobs


def assist_jobs_of(controller: object) -> AssistJobs:
    """The composition-owned LA-assist publication ledger."""
    services = services_of(controller)
    if services is None:
        raise RuntimeError("Controller services are not bound")
    return services.assist_jobs


def user_session_of(controller: object) -> UserSessionService | None:
    """Return the local user-session service bound to ``controller``, if any."""
    services = services_of(controller)
    return services.user_session if services is not None else None


def _make_persistence_audit_hook(user_session: UserSessionService) -> Callable[[str, str, int], None]:
    def _hook(kind: str, study_key: str, revision: int) -> None:
        if kind == "saved":
            user_session.record_study_audit(
                AuditAction.STUDY_SAVED,
                study_key=study_key,
                details={"revision": revision},
            )
        elif kind == "deleted":
            user_session.record_study_audit(AuditAction.STUDY_DELETED, study_key=study_key)
        elif kind == "delete_all":
            user_session.record_study_audit(AuditAction.STUDY_DELETE_ALL)

    return _hook


def normalize_profile_name(profile: str | None) -> str:
    """Normalise ``profile`` to ``'presenter'`` or ``'full'``."""
    raw = (profile or "").strip().lower()
    return PROFILE_PRESENTER if raw == PROFILE_PRESENTER else PROFILE_FULL


def display_name_for_profile(profile: str) -> str:
    """Human-visible application title for ``profile``."""
    return "SonoForge Presenter" if normalize_profile_name(profile) == PROFILE_PRESENTER else "SonoForge"


def clamp_preferences_for_capabilities(
    preferences: UserPreferences,
    capabilities: ProfileCapabilities,
) -> UserPreferences:
    """Enforce profile capability restrictions on an in-memory preferences object."""
    if not capabilities.tabs and hasattr(preferences, "tabs_enabled"):
        preferences.tabs_enabled = False
    if not capabilities.measurement_storage and hasattr(preferences, "measurement_persistence_enabled"):
        preferences.measurement_persistence_enabled = False
    return preferences


def compute_frame_cache_budget(
    preferences: object,
    *,
    available_ram_bytes: int | None = None,
    playback_config: PlaybackConfig | None = None,
) -> FrameCacheBudget:
    """Compute the adaptive frame-cache memory cap and initial byte budget."""
    resolved_config = playback_config if playback_config is not None else detect_playback_config()
    if available_ram_bytes is not None:
        ram_cap_bytes = max(1, int(available_ram_bytes * 0.08))
    else:
        try:
            available = int(psutil.virtual_memory().available)
            ram_cap_bytes = int(available * 0.08)
        except Exception:  # noqa: BLE001 - fallback when /proc or OS memory query is unavailable
            ram_cap_bytes = FALLBACK_RAM_CAP_BYTES

    configured_mb = int(getattr(preferences, "playback_max_cache_mb", DEFAULT_PLAYBACK_CACHE_MB))
    max_cache_bytes = min(configured_mb * 1024 * 1024, ram_cap_bytes)
    return FrameCacheBudget(
        playback_config=resolved_config,
        ram_cap_bytes=ram_cap_bytes,
        max_cache_bytes=max_cache_bytes,
    )


def compute_unified_memory_budget(
    preferences: object,
    *,
    available_ram_bytes: int | None = None,
    playback_config: PlaybackConfig | None = None,
) -> UnifiedMemoryBudget:
    """Register the concurrent memory consumers against one RAM share (P1.1 #545).

    The frame-cache ceiling keeps its legacy value so playback sizing does not
    change; the other consumers get explicit reservations from the same share
    instead of owning isolated hard-coded caps.
    """
    cache = compute_frame_cache_budget(
        preferences,
        available_ram_bytes=available_ram_bytes,
        playback_config=playback_config,
    )
    ram_cap_bytes = cache.ram_cap_bytes
    full_cine_bytes = int(ram_cap_bytes * 0.4)
    comparison_bytes = int(ram_cap_bytes * 0.05)
    decode_gate_bytes = int(ram_cap_bytes * 0.05)
    return UnifiedMemoryBudget(
        playback_config=cache.playback_config,
        ram_cap_bytes=ram_cap_bytes,
        max_cache_bytes=cache.max_cache_bytes,
        full_cine_bytes=full_cine_bytes,
        comparison_bytes=comparison_bytes,
        decode_gate_bytes=decode_gate_bytes,
    )


def _build_io_facades(
    *,
    capabilities: ProfileCapabilities,
    resolved_paths: AppPaths,
    hermetic: bool,
    preferences_holder: UserPreferences,
) -> AppIoFacades:
    from echo_personal_tool.application import (
        dicom_export,
        dicom_io,
        report_export,
        saved_records,
        server_io,
    )

    if hermetic:
        if resolved_paths.settings_ini is not None:
            recent_store: RecentFolderStore = _InMemoryRecentFolderStore(enabled=capabilities.recent_folders)
        else:
            recent_store = make_recent_folder_store(enabled=capabilities.recent_folders)

        def _load_hermetic_preferences() -> UserPreferences:
            return preferences_holder

        load_prefs: Callable[[], UserPreferences] = _load_hermetic_preferences
        save_prefs: Callable[[UserPreferences], None] = save_user_preferences
    else:
        recent_store = make_recent_folder_store(enabled=capabilities.recent_folders)
        load_prefs = load_user_preferences
        save_prefs = save_user_preferences

    return AppIoFacades(
        recent_folders=recent_store,
        orthanc_cache=make_orthanc_session_cache(resolved_paths.orthanc_cache_root),
        load_preferences=load_prefs,
        save_preferences=save_prefs,
        dicom_io_module=dicom_io,
        dicom_export_module=dicom_export,
        report_export_module=report_export,
        saved_records_module=saved_records,
        server_io_module=server_io,
    )


def build_app_services(
    profile: str = PROFILE_FULL,
    *,
    preferences: UserPreferences | None = None,
    paths: AppPaths | Path | None = None,
    available_ram_bytes: int | None = None,
    playback_config: PlaybackConfig | None = None,
    segmenter: IOnnxSegmenter | None = None,
) -> AppServices:
    """Assemble the complete application service graph for ``profile``.

    When ``paths`` is provided (for example ``tmp_path`` in tests), neither
    ``load_user_preferences()`` nor ``infrastructure.paths`` host directories
    are touched unless ``preferences`` was omitted and host paths were requested.
    """
    profile_name = normalize_profile_name(profile)
    capabilities = get_profile_capabilities(profile_name)
    hermetic = paths is not None

    if isinstance(paths, Path):
        resolved_paths = AppPaths.under(paths)
    elif paths is not None:
        resolved_paths = paths
    else:
        resolved_paths = AppPaths.for_host()

    if preferences is not None:
        resolved_prefs = preferences
    elif hermetic:
        resolved_prefs = default_user_preferences()
        resolved_prefs.measurement_persistence_enabled = capabilities.measurement_storage_default
    else:
        resolved_prefs = load_user_preferences()

    clamp_preferences_for_capabilities(resolved_prefs, capabilities)

    cache_budget = compute_unified_memory_budget(
        resolved_prefs,
        available_ram_bytes=available_ram_bytes,
        playback_config=playback_config,
    )
    state_manager = StateManager()
    measurement_store = StudyMeasurementSessionStore()
    calculator_inputs = CalculatorInputStore()
    users_root = resolved_paths.users_dir or (resolved_paths.measurements_dir.parent / "users")
    user_session = UserSessionService(users_root, scope_paths=not hermetic)
    persistence_enabled = bool(
        getattr(resolved_prefs, "measurement_persistence_enabled", capabilities.measurement_storage_default)
    )
    persistence = MeasurementPersistence(
        resolved_paths.measurements_dir,
        measurement_store,
        enabled=persistence_enabled,
        author_provider=lambda: user_session.active_user_id,
        can_write=lambda: user_session.can(Permission.EDIT_MEASUREMENTS),
        can_delete=lambda: user_session.can(Permission.DELETE_MEASUREMENTS),
        audit_callback=_make_persistence_audit_hook(user_session),
    )
    frame_cache = FrameCache(
        evict_window=cache_budget.playback_config.evict_window,
        max_cache_bytes=cache_budget.max_cache_bytes,
        max_full_cine_bytes=cache_budget.ram_cap_bytes,
    )
    key_images = KeyImageService(resolved_paths.measurements_dir / "key-images")

    if segmenter is not None:
        resolved_segmenter = segmenter
        resolved_a2c_segmenter: IOnnxSegmenter = segmenter
    elif capabilities.ai_segmentation:
        from echo_personal_tool.infrastructure.onnx_engine import OnnxInferenceEngine

        resolved_segmenter = OnnxInferenceEngine(models_dir=resolved_paths.models_dir)
        resolved_a2c_segmenter = OnnxInferenceEngine(
            models_dir=resolved_paths.models_dir,
            manifest_section="a2c_inference",
        )
    else:
        resolved_segmenter = DisabledOnnxSegmenter()
        resolved_a2c_segmenter = DisabledOnnxSegmenter()

    # View recognition (#639 step 2): the ONNX classifier adapter is used
    # when a trained model is present in the models dir; otherwise the workflow
    # falls back to the disabled recognizer, but the full suggest/override/
    # persist flow stays wired end-to-end either way.
    from echo_personal_tool.infrastructure.view_recognition_onnx import (
        OnnxViewRecognizer,
    )

    view_recognizer_impl = OnnxViewRecognizer(models_dir=resolved_paths.models_dir)
    view_recognizer: IViewRecognizer = (
        view_recognizer_impl if view_recognizer_impl.is_available() else DisabledViewRecognizer()
    )
    view_decisions_dir = resolved_paths.measurements_dir / "view-decisions"
    view_decision_store = JsonViewDecisionStore(view_decisions_dir)
    view_workflow = ViewRecognitionWorkflow(view_recognizer, view_decision_store)

    io_facades = _build_io_facades(
        capabilities=capabilities,
        resolved_paths=resolved_paths,
        hermetic=hermetic,
        preferences_holder=resolved_prefs,
    )

    return AppServices(
        profile=profile_name,
        display_name=display_name_for_profile(profile_name),
        capabilities=capabilities,
        preferences=resolved_prefs,
        paths=resolved_paths,
        state_manager=state_manager,
        measurement_store=measurement_store,
        calculator_inputs=calculator_inputs,
        persistence=persistence,
        key_images=key_images,
        unified_budget=cache_budget,
        frame_cache=frame_cache,
        segmenter=resolved_segmenter,
        a2c_segmenter=resolved_a2c_segmenter,
        io=io_facades,
        user_session=user_session,
        view_recognizer=view_recognizer,
        view_workflow=view_workflow,
        view_decisions_dir=view_decisions_dir,
    )


def in_memory_app_services(
    *,
    preferences: UserPreferences | None = None,
    segmenter: IOnnxSegmenter | None = None,
) -> AppServices:
    """Build hermetic default services without host settings, ``Path.home()`` or ``psutil``."""
    capabilities = get_profile_capabilities(PROFILE_FULL)
    resolved_prefs = preferences if preferences is not None else default_user_preferences()
    if preferences is None:
        resolved_prefs.measurement_persistence_enabled = False
    clamp_preferences_for_capabilities(resolved_prefs, capabilities)

    scratch_root = Path(tempfile.gettempdir()) / f"sonoforge-inmem-{os.getpid()}"
    resolved_paths = AppPaths.under(scratch_root)

    configured_mb = int(getattr(resolved_prefs, "playback_max_cache_mb", DEFAULT_PLAYBACK_CACHE_MB))
    max_cache_bytes = min(configured_mb * 1024 * 1024, FALLBACK_RAM_CAP_BYTES)
    unified_budget = UnifiedMemoryBudget(
        playback_config=DEFAULT_HERMETIC_PLAYBACK_CONFIG,
        ram_cap_bytes=FALLBACK_RAM_CAP_BYTES,
        max_cache_bytes=max_cache_bytes,
        full_cine_bytes=int(FALLBACK_RAM_CAP_BYTES * 0.4),
        comparison_bytes=int(FALLBACK_RAM_CAP_BYTES * 0.05),
        decode_gate_bytes=int(FALLBACK_RAM_CAP_BYTES * 0.05),
    )
    cache_budget = FrameCacheBudget.from_unified(unified_budget)
    state_manager = StateManager()
    measurement_store = StudyMeasurementSessionStore()
    calculator_inputs = CalculatorInputStore()
    inmem_users_root = resolved_paths.users_dir or (scratch_root / "users")
    inmem_user_session = UserSessionService(inmem_users_root, scope_paths=False)
    persistence = MeasurementPersistence(
        resolved_paths.measurements_dir,
        measurement_store,
        enabled=bool(getattr(resolved_prefs, "measurement_persistence_enabled", False)),
        author_provider=lambda: inmem_user_session.active_user_id,
        can_write=lambda: inmem_user_session.can(Permission.EDIT_MEASUREMENTS),
        can_delete=lambda: inmem_user_session.can(Permission.DELETE_MEASUREMENTS),
        audit_callback=_make_persistence_audit_hook(inmem_user_session),
    )
    frame_cache = FrameCache(
        evict_window=cache_budget.playback_config.evict_window,
        max_cache_bytes=cache_budget.max_cache_bytes,
        max_full_cine_bytes=unified_budget.ram_cap_bytes,
    )
    key_images = KeyImageService(resolved_paths.measurements_dir / "key-images")
    resolved_segmenter: IOnnxSegmenter = segmenter if segmenter is not None else DisabledOnnxSegmenter()
    io_facades = _build_io_facades(
        capabilities=capabilities,
        resolved_paths=resolved_paths,
        hermetic=True,
        preferences_holder=resolved_prefs,
    )
    return AppServices(
        profile=PROFILE_FULL,
        display_name=display_name_for_profile(PROFILE_FULL),
        capabilities=capabilities,
        preferences=resolved_prefs,
        paths=resolved_paths,
        state_manager=state_manager,
        measurement_store=measurement_store,
        calculator_inputs=calculator_inputs,
        persistence=persistence,
        key_images=key_images,
        unified_budget=unified_budget,
        frame_cache=frame_cache,
        segmenter=resolved_segmenter,
        a2c_segmenter=resolved_segmenter,
        io=io_facades,
        user_session=inmem_user_session,
    )


@dataclass(frozen=True)
class WindowDependencies:
    """Resolved profile, preferences, and I/O stores handed to ``MainWindow``."""

    profile: str
    display_name: str
    capabilities: ProfileCapabilities
    preferences: UserPreferences
    recent_folders: RecentFolderStore
    orthanc_cache: OrthancCache


_ControllerT = TypeVar("_ControllerT")


def resolve_window_dependencies(
    controller: _ControllerT | None,
    *,
    services: AppServices | None = None,
    user_preferences: UserPreferences | None = None,
) -> tuple[_ControllerT, WindowDependencies]:
    """Resolve ``MainWindow`` collaborators from ``services`` or ``controller``."""
    if controller is None:
        raise TypeError(
            "MainWindow requires an explicit controller; construct AppController in the entrypoint or test fixture"
        )
    resolved = services if services is not None else services_of(controller)
    if resolved is not None:
        capabilities = resolved.capabilities
        profile = resolved.profile
        title = resolved.display_name
        prefs = user_preferences if user_preferences is not None else resolved.preferences
        recent_folders = resolved.io.recent_folders
        orthanc_cache = resolved.io.orthanc_cache
    else:
        capabilities = get_profile_capabilities()
        profile = active_profile_name()
        title = profile_display_name()
        prefs = user_preferences if user_preferences is not None else load_user_preferences()
        recent_folders = make_recent_folder_store(enabled=capabilities.recent_folders)
        orthanc_cache = make_orthanc_session_cache()
    clamp_preferences_for_capabilities(prefs, capabilities)
    return (
        controller,
        WindowDependencies(
            profile=profile,
            display_name=title,
            capabilities=capabilities,
            preferences=prefs,
            recent_folders=recent_folders,
            orthanc_cache=orthanc_cache,
        ),
    )


__all__ = [
    "DEFAULT_HERMETIC_PLAYBACK_CONFIG",
    "AppIoFacades",
    "AppPaths",
    "AppServices",
    "DisabledOnnxSegmenter",
    "FrameCacheBudget",
    "PROFILE_FULL",
    "PROFILE_PRESENTER",
    "WindowDependencies",
    "bind_controller_services",
    "build_app_services",
    "clamp_preferences_for_capabilities",
    "compute_frame_cache_budget",
    "display_name_for_profile",
    "in_memory_app_services",
    "make_ctmr_slice_requests",
    "normalize_profile_name",
    "resolve_window_dependencies",
    "services_of",
]
