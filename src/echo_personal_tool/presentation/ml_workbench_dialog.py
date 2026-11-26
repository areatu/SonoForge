"""Local ML collection and transfer desk. Does not claim a training/release wizard."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import Qt, QThreadPool, Slot
from PySide6.QtGui import QCloseEvent, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QSplitter,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.localization import tr
from echo_personal_tool.application.ml_workbench import (
    LocalMLWorkbench,
    collection_settings,
    configure_collection,
    workbench_available,
)
from echo_personal_tool.application.training_archive import MeasurementArchiveCapture
from echo_personal_tool.application.workers.ml_workbench_worker import MLWorkbenchWorker


def _preview_pixmap(pixels: np.ndarray, points: list[list[float]], *, closed: bool = False) -> QPixmap:
    image = np.asarray(pixels, dtype=float)
    low, high = float(image.min()), float(image.max())
    image = np.ascontiguousarray(np.clip((image - low) * 255 / max(high - low, 1), 0, 255), dtype=np.uint8)
    if image.ndim == 3 and image.shape[2] == 1:
        image = image[..., 0].copy()
    height, width = image.shape[:2]
    fmt = QImage.Format.Format_Grayscale8 if image.ndim == 2 else QImage.Format.Format_RGB888
    if image.ndim == 3 and image.shape[2] == 4:
        fmt = QImage.Format.Format_RGBA8888
    result = QPixmap.fromImage(QImage(image.data, width, height, image.strides[0], fmt).copy())
    painter = QPainter(result)
    painter.setPen(QPen(Qt.GlobalColor.green, 2))
    drawn = [*points, points[0]] if closed and points else points
    for first, second in zip(drawn, drawn[1:]):
        painter.drawLine(round(first[0]), round(first[1]), round(second[0]), round(second[1]))
    painter.end()
    return result.scaled(600, 420, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


class MLWorkbenchDialog(QDialog):
    def __init__(self, parent: QWidget | None = None, *, capture: MeasurementArchiveCapture | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("ml.title"))
        self.resize(1100, 750)
        self._capture = capture
        self._generation = 0
        self._closed = False
        self._job: MLWorkbenchWorker | None = None
        self._records: list[dict[str, Any]] = []
        self._bench: LocalMLWorkbench | None = None
        layout = QVBoxLayout(self)
        privacy = QLabel(tr("ml.privacy"))
        privacy.setWordWrap(True)
        layout.addWidget(privacy)
        self._tabs = QTabWidget()
        layout.addWidget(self._tabs)
        self._build_settings()
        self._build_archive()
        self._report = QTextEdit()
        self._report.setReadOnly(True)
        self._tabs.addTab(self._report, tr("ml.evidence"))
        self._directory.textChanged.connect(self._invalidate_workspace)
        self._status = QLabel(tr("ml.not_training"))
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        close = QPushButton(tr("ml.close"))
        close.clicked.connect(self.close)
        layout.addWidget(close)

    def _build_settings(self) -> None:
        page = QWidget()
        form = QFormLayout(page)
        try:
            settings = collection_settings()
        except (OSError, ValueError):
            settings = {"enabled": False}
        self._enabled = QCheckBox(tr("ml.enable"))
        self._enabled.setChecked(settings["enabled"])
        self._directory = QLineEdit(str(settings.get("directory", "")))
        browse = QPushButton(tr("ml.browse"))
        browse.clicked.connect(self._choose_directory)
        row = QHBoxLayout()
        row.addWidget(self._directory)
        row.addWidget(browse)
        form.addRow(self._enabled)
        form.addRow(tr("ml.directory"), row)
        self._quota = QSpinBox()
        self._quota.setRange(16, 1024 * 1024)
        self._quota.setValue(int(settings.get("quota_bytes", 4096 * 1024**2)) // 1024**2)
        form.addRow(tr("ml.quota"), self._quota)
        save = QPushButton(tr("ml.save_settings"))
        save.clicked.connect(self._save_settings)
        form.addRow(save)
        self._pause = QCheckBox(tr("ml.pause"))
        self._pause.setEnabled(self._capture is not None)
        self._pause.setChecked(self._capture.paused if self._capture else False)
        self._pause.toggled.connect(self._pause_capture)
        form.addRow(self._pause)
        self._tabs.addTab(page, tr("ml.collection"))

    def _build_archive(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        tools = QHBoxLayout()
        actions = (
            ("ml.refresh", self._refresh),
            ("ml.export", lambda: self._transfer("export")),
            ("ml.import", lambda: self._transfer("import")),
            ("ml.export_key", lambda: self._transfer("export_key")),
            ("ml.import_key", lambda: self._transfer("import_key")),
            ("ml.export_report", lambda: self._transfer("report")),
        )
        for key, action in actions:
            button = QPushButton(tr(key))
            button.clicked.connect(action)
            tools.addWidget(button)
        layout.addLayout(tools)
        self._filter = QLineEdit()
        self._filter.setPlaceholderText(tr("ml.filter"))
        self._filter.textChanged.connect(self._filter_rows)
        filters = QHBoxLayout()
        self._chamber_filter = QComboBox()
        self._chamber_filter.addItem(tr("ml.all_chambers"), "")
        for chamber in ("LV", "LA", "RV", "RA"):
            self._chamber_filter.addItem(chamber, chamber)
        self._chamber_filter.currentIndexChanged.connect(self._filter_rows)
        filters.addWidget(self._chamber_filter)
        filters.addWidget(self._filter)
        layout.addLayout(filters)
        splitter = QSplitter()
        self._table = QTableWidget(0, 7)
        self._table.setHorizontalHeaderLabels(
            [tr(f"ml.col_{k}") for k in ("chamber", "view", "phase", "origin", "kind", "revision", "state")]
        )
        self._table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._table.itemSelectionChanged.connect(self._preview)
        splitter.addWidget(self._table)
        self._image = QLabel(tr("ml.select_preview"))
        self._image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        splitter.addWidget(self._image)
        layout.addWidget(splitter)
        decisions = QHBoxLayout()
        for key, excluded, reviewed in (
            ("ml.exclude", True, False),
            ("ml.restore", False, False),
            ("ml.review", False, True),
        ):
            button = QPushButton(tr(key))
            button.clicked.connect(lambda _checked=False, e=excluded, r=reviewed: self._decide(e, r))
            decisions.addWidget(button)
        layout.addLayout(decisions)
        self._tabs.addTab(page, tr("ml.archive"))

    def _invalidate_workspace(self) -> None:
        self._generation += 1
        self._job = None
        self._tabs.setEnabled(True)
        self._records = []
        self._bench = None
        self._table.setRowCount(0)
        self._image.setText(tr("ml.select_preview"))
        self._report.clear()

    def _choose_directory(self) -> None:
        value = QFileDialog.getExistingDirectory(self, tr("ml.directory"))
        if value:
            self._directory.setText(value)

    def _save_settings(self) -> None:
        try:
            configure_collection(
                enabled=self._enabled.isChecked(),
                directory=Path(self._directory.text()),
                quota_bytes=self._quota.value() * 1024**2,
            )
        except (OSError, ValueError):
            self._status.setText(tr("ml.failed"))
            return
        self._status.setText(tr("ml.restart"))

    def _pause_capture(self, paused: bool) -> None:
        if self._capture is not None:
            self._capture.set_paused(paused)

    def _workbench(self) -> LocalMLWorkbench:
        return LocalMLWorkbench(Path(self._directory.text()))

    def _run(self, action: Callable[[], Any]) -> None:
        if self._job is not None:
            return
        self._generation += 1
        job = MLWorkbenchWorker(self._generation, action)
        self._job = job
        job.signals.completed.connect(self._completed)
        job.signals.failed.connect(self._failed)
        self._tabs.setEnabled(False)
        self._status.setText(tr("ml.busy"))
        QThreadPool.globalInstance().start(job)

    @Slot(int, object)
    def _completed(self, generation: int, result: Any) -> None:
        if self._closed or generation != self._generation:
            return
        self._job = None
        self._tabs.setEnabled(True)
        self._status.setText(tr("ml.not_training"))
        if isinstance(result, dict) and "records" in result:
            self._show_inventory(result)
        elif isinstance(result, tuple) and len(result) == 2:
            pixels, record = result
            self._image.setPixmap(_preview_pixmap(pixels, record["points"], closed=record["mitral_annulus"] is None))
        else:
            self._refresh()

    @Slot(int)
    def _failed(self, generation: int) -> None:
        if self._closed or generation != self._generation:
            return
        self._job = None
        self._tabs.setEnabled(True)
        self._status.setText(tr("ml.failed"))

    def _refresh(self) -> None:
        try:
            bench = self._workbench()
        except (OSError, ValueError):
            self._status.setText(tr("ml.failed"))
            return
        self._bench = bench
        self._run(bench.inventory)

    def _show_inventory(self, inventory: dict[str, Any]) -> None:
        self._records = inventory["records"]
        self._image.setText(tr("ml.select_preview"))
        self._table.blockSignals(True)
        self._table.setRowCount(len(self._records))
        for row, record in enumerate(self._records):
            state = (
                tr("ml.state_excluded")
                if record["excluded"] or record["curation"].get("excluded")
                else tr("ml.state_included")
            )
            if record["curation"].get("reviewed"):
                state += " / " + tr("ml.state_reviewed")
            if record["sample_id"] in inventory["conflicts"]:
                state += " / " + tr("ml.state_conflict")
            values = [record[k] for k in ("chamber", "view", "phase_semantics", "origin", "geometry_kind", "revision")]
            for col, value in enumerate([*values, state]):
                self._table.setItem(row, col, QTableWidgetItem(str(value)))
        self._table.blockSignals(False)
        self._filter_rows()
        self._report.setPlainText(
            tr("ml.report_guide") + "\n\n" + json.dumps(inventory["report"], ensure_ascii=False, indent=2)
        )
        counts = (self._capture.saved_count, self._capture.skipped_count) if self._capture else (0, 0)
        self._status.setText(
            tr(
                "ml.counts",
                saved=counts[0],
                skipped=counts[1],
                free=inventory["disk"]["free_bytes"] // 1024**2,
                size=inventory["disk"]["archive_bytes"] // 1024**2,
            )
        )

    def _filter_rows(self) -> None:
        query = self._filter.text().casefold()
        for row in range(self._table.rowCount()):
            items = (self._table.item(row, col) for col in range(self._table.columnCount()))
            values = " ".join(item.text() for item in items if item is not None)
            chamber = self._chamber_filter.currentData()
            matches_chamber = not chamber or self._records[row]["chamber"] == chamber
            self._table.setRowHidden(row, not matches_chamber or query not in values.casefold())

    def _preview(self) -> None:
        row, bench = self._table.currentRow(), self._bench
        if not 0 <= row < len(self._records) or bench is None or self._job is not None:
            return
        record = dict(self._records[row])
        self._run(lambda: (bench.preview(record["origins"][0], record["frame_hash"]), record))

    def _decide(self, excluded: bool, reviewed: bool) -> None:
        bench = self._bench
        rows = sorted({index.row() for index in self._table.selectedIndexes()})
        if bench is None or not rows:
            return
        fingerprints = [self._records[row]["fingerprint"] for row in rows]

        def action() -> dict[str, Any]:
            for fingerprint in fingerprints:
                bench.decide(fingerprint, excluded=excluded, reviewed=reviewed)
            return bench.inventory()

        self._run(action)

    def _transfer(self, mode: str) -> None:
        answer = QMessageBox.question(
            self,
            tr("ml.title"),
            tr("ml.transfer_warning"),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            bench = self._workbench()
        except (OSError, ValueError):
            self._status.setText(tr("ml.failed"))
            return
        if mode == "import":
            value = QFileDialog.getExistingDirectory(self, tr("ml.import"))
        elif mode == "import_key":
            value, _ = QFileDialog.getOpenFileName(self, tr("ml.import_key"))
        else:
            value, _ = QFileDialog.getSaveFileName(self, tr("ml.new_destination"))
        if not value:
            return
        destination = Path(value)
        actions = {
            "export": bench.export_material,
            "import": bench.import_material,
            "export_key": bench.export_identity,
            "import_key": bench.import_identity,
            "report": bench.export_report,
        }
        self._bench = bench
        self._run(lambda: actions[mode](destination))

    def closeEvent(self, event: QCloseEvent) -> None:
        # I/O may finish atomically; no late result is allowed to touch this UI.
        self._closed = True
        self._generation += 1
        super().closeEvent(event)


def show_ml_workbench(parent: QWidget, capture: MeasurementArchiveCapture | None = None) -> None:
    MLWorkbenchDialog(parent, capture=capture).exec()


def populate_local_tools_menu(
    parent: QWidget, menu: QMenu, settings: Callable[[], None], profile: str, controller: object
) -> None:
    from echo_personal_tool.application.composition import services_of

    menu.addAction(tr("app_menu.settings")).triggered.connect(settings)
    if workbench_available(profile):

        def open_desk() -> None:
            services = services_of(controller)
            capture = getattr(services, "training_archive", None)
            show_ml_workbench(parent, capture)

        action = menu.addAction(tr("ml.title"))
        action.setObjectName("localMLWorkbench")
        action.triggered.connect(open_desk)
