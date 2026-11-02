"""Explicit PHI storage controls; all repository I/O stays on the serial worker."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
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

from echo_personal_tool.application.localization import tr, tr_plural
from echo_personal_tool.application.user_preferences import load_user_preferences, save_user_preferences
from echo_personal_tool.presentation.dark_theme import get_theme_palette


class MeasurementStorageDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.persistence = controller.measurement_persistence
        self._alive = True
        # Set when the dialog itself rewrites the stored autosave preference
        # (delete-all disables it «now and next launch»); the settings dialog
        # syncs its checkbox only then, keeping the user's pending edit otherwise.
        self.preferences_changed = False
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

    @staticmethod
    def _row_text(record) -> str:
        """One list row: date/counts for readable records, status for the rest."""
        if record.status == "readable":
            measurements = tr_plural("persistence.record_measurements", record.measurement_count)
            return tr(
                "persistence.record_row",
                name=record.key[:12],
                size=f"{record.size_bytes / 1024:.1f}",
                measurements=measurements,
            )
        status_key = "persistence.record_status." + str(record.status)
        status = tr(status_key)
        return tr(
            "persistence.record_row_unreadable",
            name=record.key[:12],
            size=f"{record.size_bytes / 1024:.1f}",
            status=str(record.status) if status == status_key else status,
        )

    def refresh(self, on_done=None):
        """Read record summaries through the application API (QH-1a).

        The dialog used to stat the repository itself and show only a size, which
        made a damaged record indistinguishable from a healthy one. It now shows
        the shared projection: dates and counts, the status of unreadable rows,
        and an explicit failure text instead of a silently empty list.
        """

        def apply(listing):
            if not self._alive:
                return
            if on_done is not None:
                on_done()
            self._render(listing)

        self.persistence.list_saved_records(apply)

    def _render(self, listing) -> None:
        self.records.clear()
        if listing.failed:
            # Never present "could not read" as "nothing stored" (S-07).
            self.summary.setText(tr("persistence.records_failed"))
            self.message(listing.error or "io")
            return
        for record in listing.records:
            item = QListWidgetItem(self._row_text(record))
            item.setData(Qt.ItemDataRole.UserRole, record.key)
            if not record.readable:
                item.setForeground(QColor(get_theme_palette()["text_dim"]))
                item.setToolTip(tr("persistence.record_unreadable_tip"))
            self.records.addItem(item)
        text = tr_plural(
            "persistence.stats",
            len(listing.records),
            size=f"{listing.size_bytes / 1024**2:.1f}",
        )
        if listing.unreadable:
            text += " · " + tr_plural("persistence.stats_unreadable", listing.unreadable)
        self.summary.setText(text)

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
        self.setEnabled(False)
        uid = self.controller.resolve_study_uid()

        def previewed(preview):
            if not self._alive:
                return
            self.setEnabled(True)
            category_counts = getattr(preview, "category_counts", ())
            categories = ", ".join(
                tr("persistence.import_category." + category) + f" ({count})" for category, count in category_counts
            ) or ", ".join(tr("persistence.import_category." + category) for category in preview.categories)
            if not preview.compatible:
                QMessageBox.warning(
                    self,
                    tr("persistence.import_preview_title"),
                    tr("persistence.import_preview_incompatible", unavailable=preview.unavailable_sources)
                    + "\n"
                    + tr("persistence.import_preview_contents", categories=categories),
                )
                return
            text = tr(
                "persistence.import_preview",
                categories=categories,
                sources=preview.source_count,
                unavailable=preview.unavailable_sources,
                additional=preview.additional_live_sources,
            )
            if getattr(preview, "remapped_sources", 0):
                text += "\n" + tr("persistence.import_preview_remap", count=preview.remapped_sources)
            if (
                QMessageBox.question(
                    self,
                    tr("persistence.import_preview_title"),
                    text,
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

            self.persistence.import_study(uid, Path(path), applied, preview=preview)

        self.persistence.preview_import(uid, Path(path), previewed)

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
                self.preferences_changed = True
            self.message(error)

        self.persistence.delete_all(applied)
