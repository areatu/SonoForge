"""Explicit PHI storage controls; all repository I/O stays on the serial worker."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.application.composition import user_session_of
from echo_personal_tool.application.localization import tr, tr_plural
from echo_personal_tool.application.saved_records import filter_saved_records
from echo_personal_tool.application.user_preferences import load_user_preferences, save_user_preferences
from echo_personal_tool.domain.models.user import Permission
from echo_personal_tool.presentation.dark_theme import get_theme_tokens
from echo_personal_tool.presentation.display_formats import format_storage_unit_value


class MeasurementStorageDialog(QDialog):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self.persistence = controller.measurement_persistence
        self._user_session = user_session_of(controller)
        self._last_listing = None
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

        self._filter_bar = QWidget(self)
        filter_row = QHBoxLayout(self._filter_bar)
        filter_row.setContentsMargins(0, 0, 0, 0)
        filter_row.addWidget(QLabel(tr("persistence.filter_label"), self._filter_bar))
        self.filter_combo = QComboBox(self._filter_bar)
        self.filter_combo.setObjectName("savedRecordsScopeCombo")
        self.filter_combo.addItem(tr("persistence.filter_all"), "all")
        self.filter_combo.addItem(tr("persistence.filter_mine"), "mine")
        self.filter_combo.currentIndexChanged.connect(self._on_scope_changed)
        filter_row.addWidget(self.filter_combo)
        filter_row.addStretch(1)
        self._filter_bar.setVisible(bool(self._user_session and self._user_session.is_multi_user_enabled()))
        layout.addWidget(self._filter_bar)

        self.summary = QLabel()
        layout.addWidget(self.summary)
        self.records = QListWidget()
        layout.addWidget(self.records)
        self._action_buttons: dict[str, QPushButton] = {}
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
            self._action_buttons[key] = button
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
            self._action_buttons[key] = button
            extras.addWidget(button)
        self._apply_role_permissions()
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

    def _apply_role_permissions(self) -> None:
        session = self._user_session
        if session is None:
            return
        can_edit = session.can(Permission.EDIT_MEASUREMENTS)
        can_delete = session.can(Permission.DELETE_MEASUREMENTS)
        can_export = session.can(Permission.EXPORT_DATA)
        for key in ("retry", "import", "discard", "dicom_metrics"):
            if key in self._action_buttons:
                self._action_buttons[key].setEnabled(can_edit)
        for key in ("delete_all", "delete_selected"):
            if key in self._action_buttons:
                self._action_buttons[key].setEnabled(can_delete)
        if "export" in self._action_buttons:
            self._action_buttons["export"].setEnabled(can_export)

    def set_filter_scope(self, scope: str) -> None:
        """Select ``'all'`` (all workstation studies) or ``'mine'`` (authored by active user)."""
        idx = self.filter_combo.findData(scope)
        if idx >= 0:
            self.filter_combo.setCurrentIndex(idx)

    def _on_scope_changed(self) -> None:
        if self._last_listing is not None:
            self._render(self._last_listing)

    @staticmethod
    def _author_suffix(record: object, user_names: dict[str, str]) -> str:
        created_by = getattr(record, "created_by", "")
        updated_by = getattr(record, "updated_by", "")
        if not created_by and not updated_by:
            return ""
        author_id = created_by or updated_by
        author_name = user_names.get(author_id, author_id[:8])
        if updated_by and created_by and updated_by != created_by:
            editor_name = user_names.get(updated_by, updated_by[:8])
            return tr("persistence.author_edited_suffix", author=author_name, editor=editor_name)
        return tr("persistence.author_suffix", author=author_name)

    @staticmethod
    def _row_text(record: object, user_names: dict[str, str] | None = None) -> str:
        """One list row: date/counts for readable records, status for the rest."""
        status_val = str(getattr(record, "status", ""))
        key_val = str(getattr(record, "key", ""))
        size_val = int(getattr(record, "size_bytes", 0))
        if status_val == "readable":
            measurements = tr_plural("persistence.record_measurements", int(getattr(record, "measurement_count", 0)))
            base = tr(
                "persistence.record_row",
                name=key_val[:12],
                size=format_storage_unit_value(size_val / 1024),
                measurements=measurements,
            )
            if user_names is not None:
                return base + MeasurementStorageDialog._author_suffix(record, user_names)
            return base
        status_key = "persistence.record_status." + status_val
        status = tr(status_key)
        return tr(
            "persistence.record_row_unreadable",
            name=key_val[:12],
            size=format_storage_unit_value(size_val / 1024),
            status=status_val if status == status_key else status,
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
        self._last_listing = listing
        self.records.clear()
        if listing.failed:
            # Never present "could not read" as "nothing stored" (S-07).
            self.summary.setText(tr("persistence.records_failed"))
            self.message(listing.error or "io")
            return
        scope = str(self.filter_combo.currentData() or "all")
        active_uid = self._user_session.active_user_id if self._user_session is not None else ""
        visible_records = filter_saved_records(listing.records, scope=scope, user_id=active_uid)
        user_names = (
            self._user_session.user_display_map()
            if (self._user_session is not None and self._user_session.has_users())
            else None
        )
        for record in visible_records:
            item = QListWidgetItem(self._row_text(record, user_names))
            item.setData(Qt.ItemDataRole.UserRole, record.key)
            if not record.readable:
                item.setForeground(QColor(get_theme_tokens()["text.2"]))
                item.setToolTip(tr("persistence.record_unreadable_tip"))
            self.records.addItem(item)
        total_bytes = sum(record.size_bytes for record in visible_records)
        text = tr_plural(
            "persistence.stats",
            len(visible_records),
            size=format_storage_unit_value(total_bytes / 1024**2),
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
