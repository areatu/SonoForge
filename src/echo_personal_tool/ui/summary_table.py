"""Summary metrics table — Clinical-style layout with per-view QC marks."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QVBoxLayout, QWidget

from echo_personal_tool.application.localization import tr
from echo_personal_tool.domain.measurement_catalog import format_measurement
from echo_personal_tool.ui.ui_metrics import font_pixel_size, text_width

# UI colour literals live once per module: the colour ratchet counts
# occurrences, so every repeat references the constant instead.
_TITLE_COLOR = "#e0e0e0"
_DIM_COLOR = "#bdbdbd"
_VALUE_COLOR = "#ffd54f"


class SummaryTable(QWidget):
    """Summary metrics table — Clinical-style layout with per-view QC marks."""

    #: The cuff BP the user typed in the MW block — ``(SBP, DBP)`` raw texts;
    #: the window parses them and recomputes Myocardial Work (plan А.9).
    bp_edited = Signal(str, str)

    #: Per-view rows and the view each one reports. The vendor "3 Point Contour"
    #: screen marks every analysed view with its status, so the reader knows at a
    #: glance which views entered the average; the same mark travels with our
    #: per-view GLS.
    _ROW_VIEW: dict[str, str] = {"gls_a4c": "A4C", "gls_a2c": "A2C", "gls_dao": "A3C"}
    _STATUS_MARKS: dict[str, str] = {"valid": "●", "review": "⚠", "invalid": "■"}
    _ROW_MEASUREMENT_IDS: dict[str, str] = {
        "gls": "lv.gls",
        "ess": "lv.gls",
        "psi": "lv.gls",
        "drift": "lv.gls",
        "gls_a4c": "lv.gls_a4c",
        "gls_a2c": "lv.gls_a2c",
        "gls_dao": "lv.gls_a3c",
        "gls_av": "lv.gls",
        "gwi": "lv.gwi",
        "gwe": "lv.gwe",
        "ef": "lv.ef_bp",
        "edv": "lv.edv_bp",
        "esv": "lv.esv_bp",
        "ttp": "doppler.pht",
        "autozak": "doppler.pht",
        "hr": "hr",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(text_width(self, tr("strain.summary_table"), padding=48, minimum=180))
        self._view_status: dict[str, str] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        title = QLabel(tr("strain.summary_table"))
        title.setStyleSheet(f"font-weight: bold; color: {_TITLE_COLOR}; font-size: 12px;")
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
            ("gwi", tr("strain.mw_gwi_row"), "mmHg%"),
            ("gwe", tr("strain.mw_gwe_row"), "%"),
            ("la_lasr", tr("strain.la_lasr_row"), "%"),
            ("la_lascd", tr("strain.la_lascd_row"), "%"),
            ("la_lasct", tr("strain.la_lasct_row"), "%"),
            ("rv_gls", tr("strain.rv_gls_row"), "%"),
            ("gls_mid", tr("strain.gls_mid_row"), "%"),
            ("gls_epi", tr("strain.gls_epi_row"), "%"),
            ("gls_grad", tr("strain.gls_grad_row"), tr("strain.unit_pp")),
            ("ef", tr("strain.ef"), "%"),
            ("edv", tr("strain.edv"), tr("strain.unit_ml")),
            ("esv", tr("strain.esv"), tr("strain.unit_ml")),
            ("autozak", tr("strain.autozak"), tr("strain.unit_ms")),
            ("hr", tr("strain.hr"), "bpm"),
        ]
        for key, label_text, unit in row_defs:
            row = QHBoxLayout()
            lbl = QLabel(label_text)
            lbl.setStyleSheet(f"color: {_DIM_COLOR}; font-size: {font_pixel_size(lbl, 0.85, minimum=9)}px;")
            val = QLabel("--")
            val.setStyleSheet(
                f"color: {_VALUE_COLOR}; font-weight: bold; font-size: {font_pixel_size(val, 0.85, minimum=9)}px;"
            )
            val.setAlignment(Qt.AlignmentFlag.AlignRight)
            val.setMinimumWidth(text_width(val, "0.00", padding=16, minimum=44))
            row.addWidget(lbl)
            row.addStretch()
            row.addWidget(val)
            layout.addLayout(row)
            self._rows[key] = (lbl, val, unit)
            if key in {"gwi", "gwe", "la_lasr", "la_lascd", "la_lasct", "rv_gls", "gls_mid", "gls_epi", "gls_grad"}:
                lbl.hide()
                val.hide()

        # ── Cuff BP input (plan А.9): the MW loop needs an amplitude, and the
        # amplitude must come from a person with a cuff, never invented. The
        # same pressure drives the report via the protocol header; this local
        # editor only previews the work for the curves on screen.
        bp_row = QHBoxLayout()
        bp_label = QLabel(tr("strain.mw_bp_label"))
        bp_label.setStyleSheet(f"color: {_DIM_COLOR}; font-size: {font_pixel_size(bp_label, 0.85, minimum=9)}px;")
        self._sbp_edit = QLineEdit()
        self._sbp_edit.setPlaceholderText("120")
        # The summary column is narrow; without a floor the cuff fields
        # collapsed to a few pixels and the value could not be typed at all
        # (user feedback: the placeholder read «1…»).
        self._sbp_edit.setMinimumWidth(40)
        self._dbp_edit = QLineEdit()
        self._dbp_edit.setPlaceholderText("80")
        self._dbp_edit.setMinimumWidth(40)
        for edit in (self._sbp_edit, self._dbp_edit):
            edit.setFixedWidth(text_width(edit, "000", padding=18, minimum=44))
            edit.setAccessibleName(tr("strain.mw_bp_label"))
            edit.textEdited.connect(self._emit_bp)
        self._bp_slash = QLabel("/")
        self._bp_slash.setStyleSheet(
            f"color: #bdbdbd; font-size: {font_pixel_size(self._bp_slash, 0.85, minimum=9)}px;"
        )
        bp_row.addWidget(bp_label)
        bp_row.addStretch()
        bp_row.addWidget(self._sbp_edit)
        bp_row.addWidget(self._bp_slash)
        bp_row.addWidget(self._dbp_edit)
        layout.addLayout(bp_row)
        for widget in (bp_label, self._sbp_edit, self._bp_slash, self._dbp_edit):
            widget.hide()

        layout.addStretch()

    def set_view_statuses(self, statuses: dict[str, str]) -> None:
        """Declare the QC status of each analysed view (``valid``/``review``/``invalid``).

        A view that was never analysed is simply absent: its row keeps ``--`` so
        the table never fabricates a value, while the mark tells the reader which
        measured views were allowed into ``GLS_AV``.
        """
        self._view_status = {str(view): str(status) for view, status in statuses.items() if status}

    def _emit_bp(self) -> None:
        self.bp_edited.emit(self._sbp_edit.text().strip(), self._dbp_edit.text().strip())

    def set_la_values(
        self,
        reservoir: float | None,
        conduit: float | None,
        booster: float | None,
    ) -> None:
        """Fill the LA strain rows (plan А.6) or blank them.

        A phase a view could not measure (no A-onset on the curve) shows
        ``--``; the whole block stays blank when the study has no LA
        measurement — the table never fabricates an atrial number.
        """
        for key, val in (("la_lasr", reservoir), ("la_lascd", conduit), ("la_lasct", booster)):
            _lbl, val_label, _unit = self._rows[key]
            if val is None:
                val_label.setText("--")
            else:
                val_label.setText(f"{val:.1f}%")

    def set_rv_values(self, gls: float | None) -> None:
        """Fill the RV free-wall strain row (plan А.7) or blank it.

        Blank when this clip had no free-wall trace to track — the table
        never fabricates a right-ventricular number.
        """
        _lbl, val_label, _unit = self._rows["rv_gls"]
        if gls is None:
            val_label.setText("--")
        else:
            val_label.setText(f"{gls:.1f}%")

    def set_layer_values(self, mid: float | None, epi: float | None, gradient_pp: float | None) -> None:
        """Fill the layered-strain rows (plan А.8) or blank them.

        The endocardial GLS is the main ``gls`` row — only the other layers
        and the transmural gradient get their own rows, and each stays ``--``
        when this run produced no curve for it (never a fabricated layer).
        """
        for key, val in (("gls_mid", mid), ("gls_epi", epi), ("gls_grad", gradient_pp)):
            _lbl, val_label, _unit = self._rows[key]
            if val is None:
                val_label.setText("--")
            else:
                val_label.setText(f"{val:.1f}")

    def set_mw_values(self, gwi: float | None, gwe: float | None, *, warnings: tuple[str, ...] = ()) -> None:
        """Fill the Myocardial Work rows (plan А.9) or blank them.

        ``warnings`` are the domain gate keys (``no_strain``, ``no_cycle``,
        ``no_shortening`` …): the rows stay ``--`` and the first warning is
        shown as a marked label — never a fabricated number for a beat the
        domain refused to integrate.
        """
        for key, val in (("gwi", gwi), ("gwe", gwe)):
            lbl, val_label, _unit = self._rows[key]
            if val is None:
                val_label.setText("--")
            else:
                mid = self._ROW_MEASUREMENT_IDS.get(key, "lv.gls")
                val_label.setText(format_measurement(mid, val, "%" if key == "gwe" else "mmHg%"))
            base = lbl.text().replace(" ⚠", "")
            lbl.setText(base + (" ⚠" if warnings else ""))
            lbl.setToolTip(tr(f"strain.mw_warn_{warnings[0]}") if warnings else "")

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
                    mid = self._ROW_MEASUREMENT_IDS.get(key, "lv.gls")
                    val_label.setText(f"{format_measurement(mid, val, '%')}%")
                elif unit == tr("strain.unit_ml"):
                    mid = self._ROW_MEASUREMENT_IDS.get(key, "lv.edv_bp")
                    val_label.setText(f"{format_measurement(mid, val, 'mL')} {tr('strain.unit_ml')}")
                elif unit == tr("strain.unit_ms"):
                    mid = self._ROW_MEASUREMENT_IDS.get(key, "doppler.pht")
                    val_label.setText(f"{format_measurement(mid, val, 'ms')} {tr('strain.unit_ms')}")
                elif unit == "bpm":
                    val_label.setText(f"{format_measurement('hr', val, 'bpm')} bpm")
                else:
                    mid = self._ROW_MEASUREMENT_IDS.get(key, "lv.gls")
                    val_label.setText(format_measurement(mid, val, unit))
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
