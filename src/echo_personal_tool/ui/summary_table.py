"""Summary metrics table — Clinical-style layout with per-view QC marks."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from echo_personal_tool.infrastructure.i18n import tr


class SummaryTable(QWidget):
    """Summary metrics table — Clinical-style layout with 9 rows."""

    #: Per-view rows and the view each one reports. The vendor "3 Point Contour"
    #: screen marks every analysed view with its status, so the reader knows at a
    #: glance which views entered the average; the same mark travels with our
    #: per-view GLS.
    _ROW_VIEW: dict[str, str] = {"gls_a4c": "A4C", "gls_a2c": "A2C", "gls_dao": "A3C"}
    _STATUS_MARKS: dict[str, str] = {"valid": "●", "review": "⚠", "invalid": "■"}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(240)
        self._view_status: dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel(tr("strain.summary_table"))
        title.setStyleSheet("font-weight: bold; color: #e0e0e0; font-size: 12px;")
        layout.addWidget(title)

        self._rows: dict[str, tuple[QLabel, QLabel, str]] = {}
        row_defs = [
            ("gls", tr("strain.gls_global"), "%"),
            ("ess", tr("strain.ess"), "%"),
            ("ttp", tr("strain.ttp"), tr("strain.unit_ms")),
            ("psi", tr("strain.psi"), "%"),
            ("drift", tr("strain.drift"), "%"),
            ("gls_a4c", tr("strain.gls_a4c"), "%"),
            ("gls_a2c", tr("strain.gls_a2c"), "%"),
            ("gls_dao", tr("strain.gls_dao"), "%"),
            ("gls_av", tr("strain.gls_av"), "%"),
            ("ef", tr("strain.ef"), "%"),
            ("edv", tr("strain.edv"), tr("strain.unit_ml")),
            ("esv", tr("strain.esv"), tr("strain.unit_ml")),
            ("autozak", tr("strain.autozak"), tr("strain.unit_ms")),
            ("hr", tr("strain.hr"), "bpm"),
        ]
        for key, label_text, unit in row_defs:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setStyleSheet("color: #bdbdbd; font-size: 11px;")
            val = QLabel("--")
            val.setStyleSheet("color: #ffd54f; font-weight: bold; font-size: 11px;")
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            val.setMinimumWidth(60)
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            layout.addLayout(row)
            self._rows[key] = (lbl, val, unit)

        layout.addStretch()

    def set_view_statuses(self, statuses: dict[str, str]) -> None:
        """Declare the QC status of each analysed view (``valid``/``review``/``invalid``).

        A view that was never analysed is simply absent: its row keeps ``--`` so
        the table never fabricates a value, while the mark tells the reader which
        measured views were allowed into ``GLS_AV``.
        """
        self._view_status = {str(view): str(status) for view, status in statuses.items() if status}

    def update_values(self, **kwargs: float | str | None) -> None:
        """Update table values. Accepts: gls, gls_a4c, gls_a2c, gls_dao, ef, edv, esv, autozak, hr."""
        for key, val in kwargs.items():
            if key in self._rows:
                _, val_label, unit = self._rows[key]
                if val is None:
                    val_label.setText("--")
                elif isinstance(val, str):
                    val_label.setText(val)
                elif unit == "%":
                    val_label.setText(f"{val:.1f}%")
                elif unit == tr("strain.unit_ml"):
                    val_label.setText(f"{val:.1f} {tr('strain.unit_ml')}")
                elif unit == tr("strain.unit_ms"):
                    val_label.setText(f"{val:.0f} {tr('strain.unit_ms')}")
                elif unit == "bpm":
                    val_label.setText(f"{val:.0f} bpm")
                else:
                    val_label.setText(f"{val:.1f}")
                self._mark_view_status(key, val_label)

    def _mark_view_status(self, key: str, val_label: QLabel) -> None:
        """Append the QC mark of the row's view and explain it in a tooltip."""
        view = self._ROW_VIEW.get(key)
        status = self._view_status.get(view) if view else None
        mark = self._STATUS_MARKS.get(status) if status else None
        if not mark:
            return
        val_label.setText(f"{val_label.text()} {mark}")
        val_label.setToolTip(tr(f"strain.qc_status_{status}"))
