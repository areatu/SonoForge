"""Explicit PHI storage controls; all repository I/O stays on the serial worker."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.user_preferences import load_user_preferences, save_user_preferences


class MeasurementStorageDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.persistence = controller.measurement_persistence
        self._alive = True
        self.setWindowTitle(tr("persistence.title"))
        self.resize(700, 430)
        layout = QVBoxLayout(self)
        info = QLabel(tr("persistence.privacy") + "\n" + str(self.persistence.repository.root))
        info.setWordWrap(True)
        layout.addWidget(info)
        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.records = QListWidget()
        layout.addWidget(self.records)
        buttons = QHBoxLayout()
        layout.addLayout(buttons)
        for key, action in (
            ("retry", self.retry),
            ("export", self.export_current),
            ("import", self.import_current),
            ("delete_all", self.delete_all),
        ):
            button = QPushButton(tr("persistence." + key))
            button.clicked.connect(action)
            buttons.addWidget(button)
        extras = QHBoxLayout()
        layout.addLayout(extras)
        for key, action in (
            ("delete_selected", self.delete_selected),
            ("discard", self.discard),
            ("dicom_metrics", self.dicom_metrics),
        ):
            button = QPushButton(tr("persistence." + key))
            button.clicked.connect(action)
            extras.addWidget(button)
        close = QPushButton(tr("persistence.close"))
        close.clicked.connect(self.accept)
        layout.addWidget(close)
        self.refresh()

    def done(self, result):
        self._alive = False
        super().done(result)

    def closeEvent(self, event):
        self._alive = False
        super().closeEvent(event)

    @staticmethod
    def _code_text(code):
        """Localised label for a storage error code, falling back to the raw code."""
        key = "persistence.code." + str(code)
        text = tr(key)
        return str(code) if text == key else text

    def refresh(self, on_done=None):
        def read():
            repository = self.persistence.repository
            return [(path.stem, path.stat().st_size) for path in repository.entries()]

        def apply(rows, error):
            if not self._alive:
                return
            if on_done is not None:
                on_done()
            if error:
                self.message(error)
                return
            self.records.clear()
            for key, size in rows:
                item = QListWidgetItem(tr("persistence.record_size", name=key[:12], size=f"{size / 1024:.1f}"))
                item.setData(Qt.ItemDataRole.UserRole, key)
                self.records.addItem(item)
            self.summary.setText(
                tr("persistence.stats", count=str(len(rows)), size=f"{sum(row[1] for row in rows) / 1024**2:.1f}")
            )

        self.persistence.submit(read, apply)

    def message(self, error=None):
        if not self._alive:
            return
        if error:
            QMessageBox.warning(self, tr("persistence.title"), tr("persistence.error", code=self._code_text(error)))
        else:
            self.refresh()

    def retry(self):
        if not self.persistence.flush():
            self.message("io")
        self.setEnabled(False)
        self.refresh(on_done=lambda: self.setEnabled(True))

    def export_current(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            tr("persistence.export"),
            tr("persistence.export_filename"),
            tr("persistence.file_filter"),
        )
        if not path:
            return
        self.setEnabled(False)

        def exported(error):
            if not self._alive:
                return
            self.setEnabled(True)
            self.message(error)

        self.persistence.export_study(self.controller.resolve_study_uid(), Path(path), exported)

    def import_current(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("persistence.import"), "", tr("persistence.file_filter"))
        if not path:
            return
        if (
            QMessageBox.question(
                self,
                tr("persistence.title"),
                tr("persistence.replace_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.setEnabled(False)

        def applied(error):
            if not self._alive:
                return
            self.setEnabled(True)
            if not error:
                instance = self.controller.state_manager.snapshot.instance
                if instance:
                    self.controller.load_instance(instance)
            self.message(error)

        self.persistence.import_study(self.controller.resolve_study_uid(), Path(path), applied)

    def delete_selected(self):
        item = self.records.currentItem()
        if item is None:
            return
        if (
            QMessageBox.warning(
                self,
                tr("persistence.title"),
                tr("persistence.delete_selected_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.setEnabled(False)

        def applied(error):
            if not self._alive:
                return
            self.setEnabled(True)
            self.message(error)

        self.persistence.delete_record(item.data(Qt.ItemDataRole.UserRole), applied)

    def discard(self):
        if (
            QMessageBox.warning(
                self,
                tr("persistence.title"),
                tr("persistence.discard_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        if not self.persistence.discard_pending():
            self.message("busy")

    def dicom_metrics(self):
        if (
            QMessageBox.question(
                self,
                tr("persistence.title"),
                tr("persistence.dicom_metrics_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        ):
            self.controller.use_dicom_patient_metrics()

    def delete_all(self):
        if (
            QMessageBox.warning(
                self,
                tr("persistence.title"),
                tr("persistence.delete_confirm"),
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            != QMessageBox.StandardButton.Yes
        ):
            return
        self.setEnabled(False)

        def applied(error):
            if not self._alive:
                return
            self.setEnabled(True)
            if error is None:
                # No resurrection from RAM: delete disables autosave now AND next launch.
                preferences = load_user_preferences()
                preferences.measurement_persistence_enabled = False
                save_user_preferences(preferences)
            self.message(error)

        self.persistence.delete_all(applied)
