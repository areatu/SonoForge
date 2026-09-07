"""Why is the thread-local DicomSession cold on every worker call?"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

CINE = Path(sys.argv[1]).resolve()
FRAMES = int(sys.argv[2])
WARM = "--warm" in sys.argv

from PySide6.QtCore import QThreadPool, QRunnable  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication.instance() or QApplication([])

from echo_personal_tool.infrastructure import dicom_session as ds  # noqa: E402

if WARM:
    ds.DicomSession.release_heavy = lambda self: None
    print("### warm mode: release_heavy disabled")

_orig_open = ds.DicomSession.open
_orig_rel = ds.DicomSession.release
_orig_relh = ds.DicomSession.release_heavy
_orig_rss = ds.release_stale_sessions


def open_traced(self, path):
    resolved = Path(path).resolve()
    same = self._open_path == resolved
    branch = "EARLY-RETURN" if (same and self._metadata is not None and self._has_loadable_pixels()) else "FULL-RELOAD"
    t0 = time.perf_counter()
    _orig_open(self, path)
    dt = (time.perf_counter() - t0) * 1000
    print(f"  [open ] {threading.current_thread().name} sid={id(self)%10000:5d} same_path={same} "
          f"meta={self._metadata is not None} pixels={self._has_loadable_pixels()} -> {branch} {dt:7.1f} ms")


def release_traced(self):
    import traceback
    caller = traceback.extract_stack()[-2]
    print(f"  [REL  ] {threading.current_thread().name} sid={id(self)%10000:5d} full release from {caller.name}:{caller.lineno}")
    _orig_rel(self)


def relh_traced(self):
    import traceback
    caller = traceback.extract_stack()[-2]
    print(f"  [relh ] {threading.current_thread().name} sid={id(self)%10000:5d} release_heavy from {caller.name}:{caller.lineno}")
    _orig_relh(self)


def rss_traced(exclude=None):
    import traceback
    caller = traceback.extract_stack()[-2]
    print(f"  [stale] {threading.current_thread().name} release_stale_sessions(exclude={id(exclude)%10000 if exclude else None}) from {caller.name}:{caller.lineno}")
    _orig_rss(exclude)


ds.DicomSession.open = open_traced
ds.DicomSession.release = release_traced
ds.DicomSession.release_heavy = relh_traced if not WARM else (lambda self: print(f"  [relh ] {threading.current_thread().name} sid={id(self)%10000:5d} PATCHED no-op"))
ds.release_stale_sessions = rss_traced


class Job(QRunnable):
    def __init__(self, idx, size):
        super().__init__()
        self.idx = idx
        self.size = size
        self.setAutoDelete(True)

    def run(self):
        print(f" JOB start={self.idx} size={self.size} on {threading.current_thread().name}")
        s = ds.get_thread_dicom_session()
        print(f"   session id={id(s)%10000:5d}")
        s.open(CINE)
        t0 = time.perf_counter()
        for i in range(self.idx, self.idx + self.size):
            s.decode_single_frame(i)
        print(f"   decode {self.size} frame(s): {(time.perf_counter()-t0)*1000:.1f} ms")
        s.release_heavy()


pool = QThreadPool()
pool.setMaxThreadCount(1)
for idx, size in ((0, 1), (5, 1), (20, 3), (40, 1)):
    pool.start(Job(idx, size))
    pool.waitForDone(20000)
    app.processEvents()
print("done")
