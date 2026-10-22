"""Repeatable synthetic UI probe for pre-release step 4 (no PACS/DICOM required).

QT_QPA_PLATFORM=offscreen python bench/tab_switch_probe.py --output build/tabs-before.json

Three folder tabs and three server-cache tabs, six switches per scenario, with
an 80ms simulated study-load delay. Counts actual Qt events, not Python update()
calls (which miss updates originating in C++). No pixel grabs in measured runs:
grabs themselves generate paint events. This does NOT replace native video
acceptance with real PACS/local studies.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from collections import Counter
from contextlib import ExitStack
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from PySide6.QtCore import QEvent, QEventLoop, QObject, QSettings, QTimer
from PySide6.QtWidgets import QApplication

from echo_personal_tool.application.app_controller import AppController
from echo_personal_tool.application.tab_session import TAB_ORIGIN_FOLDER, TAB_ORIGIN_SERVER
from echo_personal_tool.domain.models.metadata import InstanceMetadata, SeriesMetadata, StudyMetadata
from echo_personal_tool.infrastructure.user_preferences import UserPreferences
from echo_personal_tool.presentation.main_window import MainWindow


class Events(QObject):
    def __init__(self, widgets):
        super().__init__()
        self.names = {id(widget): name for name, widget in widgets.items()}
        self.counts = {name: Counter() for name in widgets}
        for widget in widgets.values():
            widget.installEventFilter(self)

    def eventFilter(self, watched, event):
        if event.type() in (
            QEvent.Type.Paint,
            QEvent.Type.UpdateRequest,
            QEvent.Type.LayoutRequest,
            QEvent.Type.Resize,
            QEvent.Type.Show,
            QEvent.Type.Hide,
        ):
            self.counts[self.names[id(watched)]][event.type().name] += 1
        return False


def settle(ms=120):
    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def study(n):
    instance = InstanceMetadata(
        sop_instance_uid=f"probe.{n}.clip",
        series_uid=f"probe.{n}.series",
        modality="US",
        number_of_frames=1,
        pixel_spacing=(0.5, 0.5),
        frame_time_ms=33.3,
        series_description=f"Synthetic {n}",
        path=None,
    )
    series = SeriesMetadata(
        series_uid=instance.series_uid,
        study_uid=f"probe.{n}",
        modality="US",
        description=instance.series_description,
        instances=(instance,),
    )
    return StudyMetadata(study_uid=series.study_uid, study_datetime=datetime(2026, 10, 9), series=(series,))


def probe(origin):
    with tempfile.TemporaryDirectory() as directory, ExitStack() as stack:
        root = Path(directory)
        settings = QSettings(str(root / "prefs.ini"), QSettings.Format.IniFormat)
        stack.enter_context(
            patch("echo_personal_tool.infrastructure.user_preferences._settings_store", lambda: settings)
        )
        stack.enter_context(
            patch("echo_personal_tool.infrastructure.paths.measurements_dir", lambda: root / "measurements")
        )
        stack.enter_context(
            patch("echo_personal_tool.infrastructure.profile.orthanc_cache_root", lambda: root / "cache")
        )
        controller = AppController()
        window = MainWindow(controller=controller, user_preferences=UserPreferences())
        # Isolate chrome/layout from filesystem, preview decoding and clinical inputs.
        stack.enter_context(patch.object(window, "_on_instance_selected"))
        stack.enter_context(patch.object(window._gallery, "request_visible_previews"))
        stack.enter_context(patch.object(controller, "load_thumbnail"))
        stack.enter_context(
            patch.object(
                controller,
                "load_pre_scanned_studies",
                lambda studies: QTimer.singleShot(80, lambda: controller.studies_loaded.emit(studies)),
            )
        )
        window._tabs.close_tab(window._tabs.active_tab_id)
        for n in range(3):
            window._tabs.open_tab(
                origin=origin,
                root=f"/synthetic/{n}" if origin == TAB_ORIGIN_FOLDER else "",
                cache_session_id=f"synthetic-{n}" if origin == TAB_ORIGIN_SERVER else "",
                studies=[study(n)],
            )
        window._refresh_tab_strip()
        controller.studies_loaded.emit(window._tabs.active.studies)
        window.resize(1200, 800)
        window.show()
        settle(250)
        events = Events(
            {
                "window": window,
                "system_bar": window._system_bar,
                "tab_strip": window._tab_strip,
                "tab_bar": window._tab_strip._bar,
                "tools": window._tool_panel,
                "status": window.statusBar(),
                "content": window._content_widget,
                "viewer": window._viewer,
                "gallery": window._gallery,
            }
        )
        pages = []
        window._main_stack.currentChanged.connect(pages.append)
        bar = window._tab_strip._bar
        with (
            patch.object(bar, "addTab", wraps=bar.addTab) as add,
            patch.object(bar, "removeTab", wraps=bar.removeTab) as remove,
        ):
            heights = []
            for tab in window._tabs.tabs * 2:
                heights.append(window._tab_strip.height())
                window._switch_to_tab(tab.tab_id)
                settle()
                heights.append(window._tab_strip.height())
            result = {
                "switches": 6,
                "addTab": add.call_count,
                "removeTab": remove.call_count,
                "height_min": min(heights),
                "height_max": max(heights),
                "stack_transitions": pages,
                "events": {name: dict(counts) for name, counts in events.counts.items()},
            }
        window.close()
        window.deleteLater()
        settle()
        return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    app = QApplication.instance() or QApplication([])
    results = {
        "platform": app.platformName(),
        "scenarios": {origin: probe(origin) for origin in (TAB_ORIGIN_FOLDER, TAB_ORIGIN_SERVER)},
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results, indent=2))


if __name__ == "__main__":
    main()
