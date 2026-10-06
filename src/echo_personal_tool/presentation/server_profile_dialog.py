"""Server profile selection dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.server_settings import (
    ServerSettings,
    delete_profile,
    list_profiles,
    load_profile,
    save_profile,
)


class ServerProfileDialog(QDialog):
    """Dialog for managing named server profiles."""

    def __init__(
        self,
        current_settings: ServerSettings,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("server_settings.profiles_title"))
        self.setMinimumWidth(420)
        self.setMinimumHeight(350)
        self._current_settings = current_settings
        self._selected_name: str | None = None

        self._list = QListWidget()
        self._list.currentItemChanged.connect(self._on_selection_changed)

        self._btn_load = QPushButton(tr("server_settings.profile_load"))
        self._btn_load.setEnabled(False)
        self._btn_load.clicked.connect(self._on_load)

        self._btn_save = QPushButton(tr("server_settings.profile_save"))
        self._btn_save.clicked.connect(self._on_save_as)

        self._btn_delete = QPushButton(tr("server_settings.profile_delete"))
        self._btn_delete.setEnabled(False)
        self._btn_delete.clicked.connect(self._on_delete)

        btn_row = QHBoxLayout()
        btn_row.addWidget(self._btn_load)
        btn_row.addWidget(self._btn_save)
        btn_row.addWidget(self._btn_delete)
        btn_row.addStretch()

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        from echo_personal_tool.presentation.styled_dialogs import localize_dialog_button_box

        localize_dialog_button_box(buttons)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(tr("server_settings.profiles_label")))
        layout.addWidget(self._list, stretch=1)
        layout.addLayout(btn_row)
        layout.addWidget(buttons)

        self._refresh_list()

    def _refresh_list(self) -> None:
        self._list.clear()
        profiles = list_profiles()
        for name in sorted(profiles.keys()):
            item = QListWidgetItem(name)
            item.setData(256, name)  # UserRole
            self._list.addItem(item)

    def _on_selection_changed(self, current: QListWidgetItem | None, _prev) -> None:  # noqa: ANN001
        has = current is not None
        self._btn_load.setEnabled(has)
        self._btn_delete.setEnabled(has)
        self._selected_name = current.data(256) if current else None

    def _on_load(self) -> None:
        if not self._selected_name:
            return
        loaded = load_profile(self._selected_name)
        if loaded is None:
            QMessageBox.warning(self, tr("server_settings.profiles_title"), tr("server_settings.profile_not_found"))
            return
        self._current_settings = loaded
        self.accept()

    def _on_save_as(self) -> None:
        name, ok = QInputDialog.getText(
            self,
            tr("server_settings.profile_save_as"),
            tr("server_settings.profile_name_label"),
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        profiles = list_profiles()
        if name in profiles:
            reply = QMessageBox.question(
                self,
                tr("server_settings.profiles_title"),
                tr("server_settings.profile_overwrite_confirm", name=name),
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        save_profile(name, self._current_settings)
        self._refresh_list()

    def _on_delete(self) -> None:
        if not self._selected_name:
            return
        reply = QMessageBox.question(
            self,
            tr("server_settings.profiles_title"),
            tr("server_settings.profile_delete_confirm", name=self._selected_name),
        )
        if reply == QMessageBox.StandardButton.Yes:
            delete_profile(self._selected_name)
            self._refresh_list()

    @property
    def selected_settings(self) -> ServerSettings:
        return self._current_settings
