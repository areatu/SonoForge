"""Editable per-study report header, shared by preview and export."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QFormLayout, QGroupBox, QLabel, QLineEdit

from echo_personal_tool.domain.services.report_builder import PatientInfo

FIELDS = (
    ("name", "report.patient_name"),
    ("patient_id", "report.patient_id"),
    ("birth_date", "report.birth_date"),
    ("age", "report.age"),
    ("study_date", "report.study_date"),
    ("institution", "report.institution"),
    ("equipment", "report.equipment"),
    ("physician", "report.physician"),
    ("indication", "report.indication"),
)


class ReportPatientEditor(QGroupBox):
    field_changed = Signal(str, str)

    def __init__(self, translate: Callable[[str], str], parent=None):
        super().__init__(parent)
        self._translate = translate
        self.setObjectName("reportPatientEditor")
        form = QFormLayout(self)
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapAllRows)
        self._fields = {}
        self._labels = {}
        for name, key in FIELDS:
            editor = QLineEdit()
            editor.setMinimumWidth(0)
            editor.setAccessibleName(self._translate(key))
            editor.textEdited.connect(lambda text, field=name: self.field_changed.emit(field, text))
            self._fields[name] = editor
            form.addRow(self._translate(key), editor)
            self._labels[name] = form.labelForField(editor)
        self._sex = QComboBox()
        for key, value in (("report.sex_unknown", ""), ("report.sex_male", "M"), ("report.sex_female", "F")):
            self._sex.addItem(self._translate(key), value)
        self._sex.activated.connect(lambda: self.field_changed.emit("sex", self._sex.currentData()))
        form.addRow(self._translate("report.sex"), self._sex)
        self._sex_label = form.labelForField(self._sex)
        self._body_metrics = QLabel()
        self._body_metrics.setWordWrap(True)
        form.addRow(self._body_metrics)
        self.reload_text()

    def set_patient(self, patient: PatientInfo) -> None:
        for name, editor in self._fields.items():
            value = str(getattr(patient, name) or "")
            if editor.text() != value:
                editor.setText(value)
        self._sex.setCurrentIndex(max(0, self._sex.findData(patient.sex)))
        metrics = []
        if patient.height_cm is not None:
            metrics.append(f"{self._translate('tools.height')}: {patient.height_cm:g} cm")
        if patient.weight_kg is not None:
            metrics.append(f"{self._translate('tools.weight')}: {patient.weight_kg:g} kg")
        if patient.bsa_m2 is not None:
            metrics.append(f"{self._translate('panel.bsa')}: {patient.bsa_m2:.2f} m²")
        self._body_metrics.setText(" · ".join(metrics))

    def reload_text(self) -> None:
        self.setTitle(self._translate("report.patient"))
        for name, key in FIELDS:
            self._labels[name].setText(self._translate(key))
            self._fields[name].setAccessibleName(self._translate(key))
        self._sex_label.setText(self._translate("report.sex"))
        for index, key in enumerate(("report.sex_unknown", "report.sex_male", "report.sex_female")):
            self._sex.setItemText(index, self._translate(key))
