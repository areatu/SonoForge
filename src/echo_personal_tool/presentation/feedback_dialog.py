"""Report-a-problem dialog (Q-13): prefilled GitHub issue plus local diagnostics.

The dialog is deliberately small and explicit about what leaves the machine:
the link carries the allowlisted environment block shown in the preview, and
logs travel only as a ZIP the user attaches to the issue themselves.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from echo_personal_tool.infrastructure.i18n import tr
from echo_personal_tool.infrastructure.support_report import (
    build_issue_url,
    default_bundle_path,
    environment_text,
)

logger = logging.getLogger(__name__)

_PREVIEW_LINES = 9


class SupportFeedbackDialog(QDialog):
    """Collect nothing; show exactly what a report will contain."""

    def __init__(self, parent: QWidget | None = None, *, bundle_path: Path | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("feedback.title"))
        self._bundle_path = Path(bundle_path) if bundle_path is not None else default_bundle_path()

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        intro = QLabel(tr("feedback.intro"))
        intro.setWordWrap(True)
        layout.addWidget(intro)

        privacy = QLabel(tr("feedback.privacy"))
        privacy.setWordWrap(True)
        privacy.setObjectName("feedbackPrivacy")
        layout.addWidget(privacy)

        self._bundle_checkbox = QCheckBox(tr("feedback.bundle_checkbox"))
        self._bundle_checkbox.setChecked(True)
        self._bundle_checkbox.setObjectName("feedbackBundle")
        self._bundle_checkbox.toggled.connect(self._refresh_preview)
        layout.addWidget(self._bundle_checkbox)

        destination_row = QHBoxLayout()
        destination_row.setSpacing(6)
        self._destination_label = QLabel()
        self._destination_label.setObjectName("feedbackDestination")
        self._destination_label.setWordWrap(True)
        destination_row.addWidget(self._destination_label, 1)
        self._browse_button = QPushButton(tr("feedback.bundle_browse"))
        self._browse_button.setObjectName("feedbackBrowse")
        self._browse_button.clicked.connect(self._choose_destination)
        destination_row.addWidget(self._browse_button)
        layout.addLayout(destination_row)

        layout.addWidget(QLabel(tr("feedback.environment_title")))
        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setObjectName("feedbackPreview")
        self._preview.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self._preview.setPlainText(self._compose_environment())
        self._preview.setFixedHeight(self._preview.fontMetrics().lineSpacing() * _PREVIEW_LINES)
        layout.addWidget(self._preview, 1)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._open_button = QPushButton(tr("feedback.open_form"))
        self._open_button.setObjectName("feedbackOpen")
        self._open_button.setDefault(True)
        self._open_button.clicked.connect(self._open_form)
        actions.addWidget(self._open_button)
        self._copy_button = QPushButton(tr("feedback.copy_link"))
        self._copy_button.setObjectName("feedbackCopy")
        self._copy_button.clicked.connect(self._copy_link)
        actions.addWidget(self._copy_button)
        actions.addStretch(1)
        self._close_button = QPushButton(tr("feedback.close"))
        self._close_button.setObjectName("feedbackClose")
        self._close_button.clicked.connect(self.reject)
        actions.addWidget(self._close_button)
        layout.addLayout(actions)

        self._refresh_preview()
        # Font-relative width: the preview and the destination path must fit
        # without horizontal scrolling at any UI scale (Э4).
        self.setMinimumWidth(max(self.fontMetrics().horizontalAdvance("m") * 60, 420))

    # ── contents ────────────────────────────────────────────────────────────
    def issue_url(self, *, bundle_name: str | None = None) -> str:
        """The prefilled form link for the current dialog state."""
        name = self._bundle_path.name if bundle_name is None else bundle_name
        if not self._bundle_checkbox.isChecked():
            name = ""
        # Only machine-known fields are prefilled: the description, the steps
        # and the expected result stay empty so the form shows its own prompts
        # instead of boilerplate nobody deletes.
        return build_issue_url(additional=environment_text(QApplication.instance(), bundle_name=name))

    def _compose_environment(self) -> str:
        name = self._bundle_path.name if self._bundle_checkbox.isChecked() else ""
        return environment_text(QApplication.instance(), bundle_name=name)

    def _refresh_preview(self) -> None:
        self._preview.setPlainText(self._compose_environment())
        self._destination_label.setText(tr("feedback.bundle_destination", path=str(self._bundle_path)))
        enabled = self._bundle_checkbox.isChecked()
        self._destination_label.setVisible(enabled)
        self._browse_button.setVisible(enabled)

    # ── actions ─────────────────────────────────────────────────────────────
    def _choose_destination(self) -> None:
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        chosen, _ = styled_save_file(
            self,
            tr("feedback.save_dialog_title"),
            str(self._bundle_path),
            "ZIP (*.zip)",
        )
        if not chosen:
            return
        path = Path(chosen)
        if path.suffix.lower() != ".zip":
            path = path.with_suffix(".zip")
        self._bundle_path = path
        self._refresh_preview()

    def _create_bundle(self) -> Path | None:
        """Write the sanitized diagnostic ZIP; ``None`` when it failed."""
        from echo_personal_tool.infrastructure.diagnostics import create_diagnostic_bundle

        try:
            return create_diagnostic_bundle(self._bundle_path, app=QApplication.instance())
        except OSError as exc:
            logger.warning("Could not create the diagnostic bundle (%s)", type(exc).__name__)
            QMessageBox.warning(
                self,
                tr("feedback.title"),
                tr("feedback.bundle_failed", error=type(exc).__name__),
            )
            return None

    def _open_form(self) -> None:
        bundle_name = ""
        if self._bundle_checkbox.isChecked():
            created = self._create_bundle()
            if created is not None:
                bundle_name = created.name
                # The user has to attach the archive by hand: show them where it is.
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(created.parent)))
        url = self.issue_url(bundle_name=bundle_name or "")
        if not QDesktopServices.openUrl(QUrl(url)):
            self._copy_to_clipboard(url)
            QMessageBox.information(self, tr("feedback.title"), tr("feedback.browser_failed"))
            return
        self.accept()

    def _copy_link(self) -> None:
        # A bundle that was never written must not be promised to the maintainer.
        promised = self._bundle_checkbox.isChecked() and self._bundle_path.exists()
        url = self.issue_url(bundle_name=self._bundle_path.name if promised else "")
        self._copy_to_clipboard(url)
        QMessageBox.information(self, tr("feedback.title"), tr("feedback.copied"))

    @staticmethod
    def _copy_to_clipboard(text: str) -> None:
        clipboard = QApplication.clipboard()
        if clipboard is not None:
            clipboard.setText(text)


def show_support_feedback_dialog(parent: QWidget | None = None) -> None:
    """Open the report dialog (used by Settings)."""
    from echo_personal_tool.presentation.ui_animations import exec_animated

    dialog = SupportFeedbackDialog(parent)
    exec_animated(dialog)
