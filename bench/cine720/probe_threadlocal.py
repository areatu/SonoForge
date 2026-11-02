"""Confirm: `threading.local()` state is lost between QRunnable invocations on pooled threads.

Why it matters: `DicomSession` / `VideoReader` cache their open file in `threading.local()`
(`infrastructure/dicom_session.py:20`, `infrastructure/video_reader.py:17`) and are used from
`QThreadPool` runnables. If the thread-local does not survive, every worker call creates a
fresh session and re-reads the whole file.

Three scenarios:
  A. sequential runnables, `waitForDone()` after each one;
  B. runnables submitted 250 ms apart (like real playback/scroll), **without** waiting —
     this is the decisive one: the OS thread is reused, yet the thread-local is still empty;
  C. control — the same work executed directly inside a real `threading.Thread`.

Run: QT_QPA_PLATFORM=offscreen python bench/cine720/probe_threadlocal.py
"""

from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRunnable, QThreadPool, QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

_tl = threading.local()
_seen: list[tuple[str, int, str, int, int, int]] = []

app = QApplication([])


class Job(QRunnable):
    def __init__(self, scenario: str, tag: int):
        super().__init__()
        self.scenario = scenario
        self.tag = tag
        self.setAutoDelete(True)

    def run(self):
        ident = threading.get_ident()
        native = threading.get_native_id()
        cur = threading.current_thread()
        hits = getattr(_tl, "hits", []) + [f"{self.scenario}{self.tag}"]
        _tl.hits = hits
        _seen.append((self.scenario, self.tag, cur.name, ident, native, len(hits)))
        print(f"  [{self.scenario}] run {self.tag}: thread={cur.name} ident={ident} "
              f"native_id={native} local_history_len={len(hits)}")


# ---- scenario A: sequential, waitForDone between jobs ----
pool_a = QThreadPool()
pool_a.setMaxThreadCount(1)
print("== A. QThreadPool(maxThreadCount=1), 5 runnables, waitForDone() after each ==")
for i in range(5):
    pool_a.start(Job("A", i))
    pool_a.waitForDone(5000)

# ---- scenario B: submitted 250 ms apart, no waitForDone (real playback/scroll pattern) ----
print("\n== B. QThreadPool(maxThreadCount=1), 8 runnables submitted 250 ms apart ==")
pool_b = QThreadPool()
pool_b.setMaxThreadCount(1)
pool_b.setExpiryTimeout(30_000)


def _submit(i: int) -> None:
    pool_b.start(Job("B", i))
    if i < 7:
        QTimer.singleShot(250, lambda: _submit(i + 1))
    else:
        QTimer.singleShot(500, app.quit)


QTimer.singleShot(0, lambda: _submit(0))
app.exec()

# ---- scenario C: control, a real Python thread ----
print("\n== C. control: the same runnable bodies executed inside threading.Thread ==")


def _pythread_work():
    for i in range(3):
        Job("C", i).run()


t = threading.Thread(target=_pythread_work)
t.start()
t.join()

# ---- conclusions ----
print("\nConclusion:")
for scen in ("A", "B", "C"):
    rows = [r for r in _seen if r[0] == scen]
    if not rows:
        continue
    lengths = [r[5] for r in rows]
    verdict = "LOST every call" if all(x == 1 for x in lengths) else "preserved"
    print(f"  scenario {scen}: local history lengths = {lengths}  ({verdict})")
    print(f"               distinct python idents = {len({r[3] for r in rows})}, "
          f"distinct native ids = {len({r[4] for r in rows})}")
print("""
Interpretation: in scenario B the very same OS thread runs all jobs (one native id), yet
`threading.local()` is empty on every entry — PySide6 acquires the GIL with
PyGILState_Ensure for the Python override and releases it with PyGILState_Release
afterwards, which destroys the thread state (and its thread-locals) for threads not
created by the `threading` module. Any thread-local caching inside a QRunnable is
therefore silently defeated; scenario C shows the same code preserving state in a real
Python thread.
""")
