"""Prototype fix: process-wide session keyed by resolved path (instead of threading.local).

Rationale (measured): PySide6 QThreadPool runnables get a fresh Python thread state per
invocation, so `threading.local()` never survives -> every frame decode re-reads and
re-extracts the whole DICOM file.
"""

from __future__ import annotations

import threading
import sys
from pathlib import Path

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

from echo_personal_tool.infrastructure import dicom_session as ds  # noqa: E402


def apply(*, keep_warm: bool = True, verbose: bool = False) -> None:
    lock = threading.RLock()
    holder: dict = {"session": None}

    def get_shared_session() -> ds.DicomSession:
        with lock:
            if holder["session"] is None:
                holder["session"] = ds.DicomSession()
            return holder["session"]

    class LockedSession:
        """Thin proxy that serialises open/decode across worker threads."""

        def __init__(self):
            self._s = get_shared_session()

        def __getattr__(self, name):
            attr = getattr(self._s, name)
            if callable(attr) and name in ("open", "decode_single_frame", "decode_first_frame",
                                           "decode_all_frames", "read_frame", "release", "release_heavy"):
                def wrapped(*a, **kw):
                    with lock:
                        return attr(*a, **kw)
                return wrapped
            return attr

    def factory():
        return LockedSession()

    # patch every module that imported the helper directly
    ds.get_thread_dicom_session = factory
    for mod in ("echo_personal_tool.application.workers.frame_loader_worker",
                "echo_personal_tool.application.workers.dicom_decode_worker",
                "echo_personal_tool.application.workers.dicom_loader_worker",
                "echo_personal_tool.application.workers.thumbnail_loader_worker",
                "echo_personal_tool.application.workers.video_decode_worker",
                "echo_personal_tool.application.frame_cache"):
        m = sys.modules.get(mod)
        if m is not None and hasattr(m, "get_thread_dicom_session"):
            m.get_thread_dicom_session = factory
    if keep_warm:
        # keep the active file's pixel buffer alive; open() releases it on file switch
        ds.DicomSession.release_heavy = lambda self: None
    # same problem for the MP4 reader: thread-local VideoReader is lost per runnable
    from echo_personal_tool.infrastructure import video_reader as vr
    vlock = threading.RLock()
    vholder = {"r": None}

    class LockedReader:
        """Serialise access to the single cv2.VideoCapture (it is not thread-safe)."""

        def __init__(self):
            with vlock:
                if vholder["r"] is None:
                    vholder["r"] = vr.VideoReader()
            self._r = vholder["r"]

        def __getattr__(self, name):
            attr = getattr(self._r, name)
            if callable(attr):
                def wrapped(*a, **kw):
                    with vlock:
                        return attr(*a, **kw)
                return wrapped
            return attr

    def get_shared_reader():
        return LockedReader()

    vr.get_thread_video_reader = get_shared_reader
    for mod in ("echo_personal_tool.application.workers.frame_loader_worker",
                "echo_personal_tool.application.workers.video_decode_worker",
                "echo_personal_tool.application.frame_cache"):
        m = sys.modules.get(mod)
        if m is not None and hasattr(m, "get_thread_video_reader"):
            m.get_thread_video_reader = get_shared_reader

    if verbose:
        print(f"[patch] shared session installed (keep_warm={keep_warm})")
