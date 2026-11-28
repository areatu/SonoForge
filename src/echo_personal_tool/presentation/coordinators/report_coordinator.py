"""Report mode of the main window — the first coordinator slice of ``MainWindow`` (issue 478).

«Изображения | Отчёт» (spec §4.6): the report page is a surface of the main
stack next to the images content. Each tab keeps its own mode in
``TabSession.report_mode``, and the tab coordinator asks
:meth:`ReportCoordinator.mode_page` whenever it picks the surface. Toggling
never touches the viewer, so the clip, the frame and an armed protocol step
survive the round trip. The page carries the phrases column and the conclusion
draft (``TabSession.report_conclusion``), the «откуда значение» card with its
«Открыть кадры» jump, the export block (PDF, CSV, JSON, print) and the per-tab
finished version a physician signs off.

The coordinator owns the one report page of the window and the pending frame of
the «Открыть кадры» jump. Everything else is explicit:

* the application facade (:class:`AppController`) for the study snapshot, the
  open studies and the cine transport;
* :class:`ReportWindowPort` — a handful of callables for what only the window
  can do (its tabs and preferences, its stack, status line, viewer focus,
  gallery selection, protocol session, and the file/print dialogs).

The port is a bag of callables rather than the window itself, so the
coordinator never reaches into ``MainWindow`` internals, and a test builds it
from plain functions — no ``QMainWindow`` needed.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from PySide6.QtCore import QObject, Signal

from echo_personal_tool.application.diagnostics import log_boundary_failure, safe_error_category
from echo_personal_tool.application.localization import get_language, tr
from echo_personal_tool.application.report_conclusion import ConclusionAutofillResult, autofill_conclusion
from echo_personal_tool.application.report_phrases import ReportPhraseStore, make_report_phrase_store
from echo_personal_tool.application.transport_policy import TransportPolicyError
from echo_personal_tool.domain.exceptions import InteropError
from echo_personal_tool.domain.models.ste_analysis import StrainStudy, strain_report_from_study
from echo_personal_tool.domain.services.report_builder import (
    PatientInfo,
    ReportDocument,
    build_report_document,
    with_extra_values,
    without_values,
)
from echo_personal_tool.domain.services.report_profiles import (
    DEFAULT_PROFILE_ID,
    normalize_profile_id,
)
from echo_personal_tool.domain.services.report_sections import checklist_notices, not_evaluated_values
from echo_personal_tool.domain.services.report_value_layout import DEFAULT_REPORT_VALUE_EXCLUDED, merge_report_order
from echo_personal_tool.presentation.report_mode import ReportModePage, SheetVersion
from echo_personal_tool.presentation.report_mode.print_job import print_report_pdf
from echo_personal_tool.presentation.report_values_dialog import ReportValuesDialog

if TYPE_CHECKING:
    from PySide6.QtWidgets import QStackedWidget, QWidget

    from echo_personal_tool.application.app_controller import AppController
    from echo_personal_tool.application.protocol_session import ProtocolSession
    from echo_personal_tool.application.report_signing import ReportSigningService
    from echo_personal_tool.application.tab_session import TabSession
    from echo_personal_tool.application.user_preferences import UserPreferences
    from echo_personal_tool.domain.models import InstanceMetadata
    from echo_personal_tool.domain.models.measurements import MeasurementSnapshot
    from echo_personal_tool.domain.models.report_signature import SignatureReceipt
    from echo_personal_tool.domain.services.report_template import ReportTemplate

logger = logging.getLogger(__name__)


def study_profile_id(preferences: UserPreferences) -> str:
    """Active study profile of the workspace (item 11 of the 2026-11-06 list)."""
    from echo_personal_tool.domain.study_profiles import normalize_profile_id as normalize_study_profile

    return normalize_study_profile(getattr(preferences, "study_profile", ""))


def instance_label(instance: InstanceMetadata) -> str:
    """Name a clip the way the gallery does: its file name, else its SOP Instance UID."""
    if instance.path is not None:
        return instance.path.name
    return instance.sop_instance_uid


@dataclass(frozen=True)
class ReportWindowPort:
    """What the report mode needs from the window, and nothing else.

    Every field is a callable so the window can bind late (tests replace
    ``window._show_status`` or the viewer's methods after construction) and a
    test without a window can pass plain functions.
    """

    #: The tab whose report is on screen (``None`` while no tab exists).
    active_tab: Callable[[], TabSession | None]
    #: The window's current preferences, and how to replace *and persist* them.
    preferences: Callable[[], UserPreferences]
    store_preferences: Callable[[UserPreferences], None]
    #: The main stack the report page lives in (its parent).
    page_stack: Callable[[], QStackedWidget]
    #: Parent of the file / print dialogs and of the PDF export job.
    dialog_parent: Callable[[], QWidget]
    show_status: Callable[[str], None]
    #: Re-pick the surface of the main stack for the active tab.
    show_active_surface: Callable[[], None]
    #: Give the keys back to the viewer when it is the visible content.
    focus_images: Callable[[], None]
    focus_viewer: Callable[[], None]
    #: Select *instance* in the gallery and load it, like a click there.
    open_instance: Callable[[InstanceMetadata], None]
    protocol_session: Callable[[], ProtocolSession]
    #: Activate a catalog tool of the measurement panel (organ checklist rows).
    activate_tool: Callable[[str], None]
    #: Rename a planimetry contour of the clip on screen; False if it lives elsewhere.
    rename_contour: Callable[[str, str], bool]
    #: Mirror the mode into the patient-line switch.
    mirror_report_mode: Callable[[bool], None]
    #: ``(title, default file name, filter) -> chosen path`` ("" when cancelled).
    ask_save_path: Callable[[str, str, str], str]
    warn: Callable[[str, str], None]
    #: A configured printer, or ``None`` when the print dialog is cancelled.
    ask_printer: Callable[[], Any | None]


def ask_report_printer(parent: QWidget) -> Any | None:
    """The system print dialog for the sheet; ``None`` when cancelled."""
    from PySide6.QtPrintSupport import QPrintDialog, QPrinter

    printer = QPrinter(QPrinter.PrinterMode.HighResolution)
    dialog = QPrintDialog(printer, parent)
    dialog.setWindowTitle(tr("report.print_title"))
    if dialog.exec() != QPrintDialog.DialogCode.Accepted:
        return None
    return printer


def _parse_mmhg(raw: object) -> float | None:
    """Parse a header BP field ("120", "120.0") to mmHg; junk → ``None``.

    A cleared or malformed field means "no pressure": the Myocardial Work
    section then disappears from the protocol instead of showing a loop built
    from a stale or invented number.
    """
    text = str(raw or "").strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if 0.0 < value < 400.0 else None


def _parse_weeks(raw: object) -> float | None:
    """Parse a header gestational-age field to weeks; junk → ``None``.

    Same contract as :func:`_parse_mmhg`: a cleared or malformed field means
    «not filled in» — the fetal Z-scores then stay off the protocol instead
    of running against an invented gestational age.
    """
    text = str(raw or "").strip().replace(",", ".")
    try:
        value = float(text)
    except ValueError:
        return None
    return value if 0.0 < value <= 45.0 else None


class ReportCoordinator(QObject):
    """Owns the report page of the window and every reaction of the report mode."""

    patient_context_changed = Signal()

    _BP_FIELD_NAMES = ("systolic_bp_mmhg", "diastolic_bp_mmhg")

    def __init__(self, controller: AppController, port: ReportWindowPort, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._port = port
        # One page per window, built on first entry; which tab is in «Отчёт»
        # lives in the TabSession, so every tab keeps its own mode.
        self._page: ReportModePage | None = None
        self._shown_tab_id = ""
        #: Frame of the «откуда значение» card to jump to once its clip loads.
        self._pending_frame: int | None = None

    # ── State the window and the tests read ─────────────────────────────

    @property
    def page(self) -> ReportModePage | None:
        """The report page, or ``None`` before the first entry into «Отчёт»."""
        return self._page

    @property
    def pending_frame(self) -> int | None:
        """Frame «Открыть кадры» will apply once the requested clip is on screen."""
        return self._pending_frame

    def _active_tab(self) -> TabSession | None:
        return self._port.active_tab()

    def _finished(self, tab: TabSession | None) -> bool:
        return bool(getattr(tab, "report_finished", False)) if tab is not None else False

    # ── Window lifecycle hooks ──────────────────────────────────────────

    def apply_preferences(self, preferences: UserPreferences) -> None:
        """Font, theme, language, template and unit changes of the settings dialog."""
        page = self._page
        if page is None:  # built on first entry into «Отчёт»
            return
        page.set_font_size(preferences.pdf_font_size)
        page.set_research_banner(preferences.report_research_watermark)
        page.apply_theme()
        # The printable form (header fields, notes, measurement columns) mirrors the preferences (2026-11-16 п.6).
        self.refresh_template()
        # Language and the length unit change the document itself.
        page.request_refresh()
        self._refresh_signing_availability()

    def reload_text(self) -> None:
        """Retranslate the page after a language switch."""
        if self._page is not None:
            self._page.reload_text()
        self._refresh_signing_availability()

    def set_allowed_profiles(self, profile_ids: tuple[str, ...]) -> None:
        """The study profile changed: the sheet header offers its formats only."""
        page = self._page
        if page is not None:
            page.preview.set_allowed_profiles(profile_ids)
            page.preview.request_refresh()

    def resume_pending_frame(self) -> None:
        """The clip «Открыть кадры» asked for is on screen: apply its saved frame."""
        if self._pending_frame is None:
            return
        frame_index = self._pending_frame
        self._pending_frame = None
        self.jump_to_frame(frame_index)

    # ── Patient header and document ─────────────────────────────────────

    def patient_info(self, measurement_snapshot: MeasurementSnapshot | None) -> PatientInfo:
        """Report header pre-filled from the DICOM header and the session.

        A video file has no patient block, and a corrupt header must not stop
        the report from opening, so every failure degrades to an empty header
        the physician can fill in by hand.
        """
        from echo_personal_tool.application.dicom_io import read_patient_demographics

        instance = self._controller.state_manager.snapshot.instance
        demographics = None
        if instance is not None and instance.path is not None and instance.media_format == "dicom":
            try:
                demographics = read_patient_demographics(instance.path)
            except Exception as exc:  # noqa: BLE001 - an unreadable header is not fatal
                log_boundary_failure(logger, "patient.demographics", exc, code="io", level=logging.WARNING)

        indexed = measurement_snapshot.indexed if measurement_snapshot is not None else None
        height_cm = measurement_snapshot.height_cm if measurement_snapshot is not None else None
        weight_kg = measurement_snapshot.weight_kg if measurement_snapshot is not None else None
        height_source, weight_source = (
            self._controller.patient_metric_sources()
            if hasattr(self._controller, "patient_metric_sources")
            else ("unset", "unset")
        )
        if demographics is not None:
            # Explicit clearing wins too; a report must not resurrect DICOM values.
            # The session values win: they are the ones the user can correct in
            # the tool panel, the header is only the fallback.
            if height_cm is None and height_source == "unset" and demographics.height_m:
                height_cm = demographics.height_m * 100.0
            if weight_kg is None and weight_source == "unset":
                weight_kg = demographics.weight_kg
        # The permanent header values (Settings → Report) win over the DICOM
        # header when configured: the physician filled them once instead of
        # per study.  Session edits in the report header still win last.
        from echo_personal_tool.application.composition import user_session_of

        session = user_session_of(self._controller)
        session_physician = session.default_report_physician() if session is not None else ""
        prefs = self._port.preferences()
        patient = PatientInfo(
            name=demographics.name if demographics else "",
            patient_id=demographics.patient_id if demographics else "",
            birth_date=demographics.birth_date if demographics else "",
            age=demographics.age if demographics else "",
            sex=demographics.sex if demographics else "",
            study_date=demographics.study_date if demographics else "",
            height_cm=height_cm,
            weight_kg=weight_kg,
            bsa_m2=indexed.bsa_m2 if indexed is not None else None,
            institution=prefs.report_institution or (demographics.institution if demographics else ""),
            equipment=prefs.report_equipment or (demographics.equipment if demographics else ""),
            physician=(
                prefs.report_physician
                or session_physician
                or (demographics.referring_physician if demographics else "")
            ),
        )

        tab = self._active_tab()
        raw_overrides = dict(getattr(tab, "report_patient_fields", {}) or {})
        overrides = dict(raw_overrides)
        sbp = _parse_mmhg(overrides.pop("systolic_bp_mmhg", None))
        dbp = _parse_mmhg(overrides.pop("diastolic_bp_mmhg", None))
        weeks = _parse_weeks(overrides.pop("gestational_weeks", None))
        patient = replace(patient, **overrides)
        if "systolic_bp_mmhg" in raw_overrides:
            patient = replace(patient, systolic_bp_mmhg=sbp)
        if "diastolic_bp_mmhg" in raw_overrides:
            # A touched field that did not parse (cleared or junk) means "no
            # pressure": it must not resurrect the header value.
            patient = replace(patient, diastolic_bp_mmhg=dbp)
        if "gestational_weeks" in raw_overrides:
            patient = replace(patient, gestational_weeks=weeks)
        return patient

    def default_report_name(self) -> str:
        """Suggested file name of an exported report."""
        instance = self._controller.state_manager.snapshot.instance
        if instance is not None and instance.path is not None:
            return f"{instance.path.stem}_report.pdf"
        return "echo_report.pdf"

    def current_document(self) -> ReportDocument:
        """The report of the active study, as the sheet and every export build it.

        Same inputs everywhere (study-wide snapshot, DICOM header, the patient's
        sex, the length unit), so the sheet of the mode and the exported
        document cannot drift apart.
        """
        tab = self._active_tab()
        if tab is not None and tab.report_finished and isinstance(tab.report_frozen_sheet, SheetVersion):
            return tab.report_frozen_sheet.document
        document = self._unfiltered_document()
        if self._page is not None and not self._finished(tab):
            self._page.set_hidden_values(self.hidden_value_labels(document))
        return without_values(document, self.hidden_value_keys() | self._saved_exclusions())

    def _report_snapshot(self) -> MeasurementSnapshot | None:
        return self._controller.compute_study_snapshot(
            report_choices=getattr(self._active_tab(), "report_value_choices", {})
        )

    def _unfiltered_document(self) -> ReportDocument:
        preferences = self._port.preferences()
        snapshot = self._report_snapshot()
        patient = self.patient_info(snapshot)
        tab = self._active_tab()
        conclusion = getattr(tab, "report_conclusion", "") if tab is not None else ""
        if conclusion:
            # The draft lives in the tab and is part of the document, so the
            # sheet and the PDF can never print two different conclusions.
            patient = replace(patient, conclusion=conclusion)
        if (
            snapshot is not None
            and snapshot.strain is not None
            and patient.systolic_bp_mmhg is not None
            and patient.diastolic_bp_mmhg is not None
        ):
            # А.9: the cuff pressure turns the stored strain study into
            # pressure-strain loops; the projection re-runs so the sheet and
            # the header can never disagree about the inputs. Only a real
            # StrainStudy is adopted — a duck-typed stand-in (test double or
            # stubbed controller) must not reach the projection, exactly as
            # in ``StrainWindow.set_study``.
            provider = getattr(self._controller, "strain_study", None)
            candidate = provider() if callable(provider) else None
            if isinstance(candidate, StrainStudy):
                reprojected = strain_report_from_study(
                    candidate,
                    blood_pressure=(patient.systolic_bp_mmhg, patient.diastolic_bp_mmhg),
                )
                if reprojected is not None:
                    snapshot = replace(snapshot, strain=reprojected)
        document = build_report_document(
            snapshot,
            patient,
            sex=patient.sex,
            length_display_unit=preferences.length_display_unit,
            profile_id=self.profile_id(),
            include_inputs=bool(getattr(preferences, "report_show_inputs", False)),
            value_order=getattr(preferences, "report_value_order", ()),
            study_profile_id=study_profile_id(preferences),
            draft=not self._finished(tab),
        )
        page = self._page
        if page is None:
            return document
        # The checklist is the same value the left column shows: missing, stale
        # and unreviewed counts become printable notices, so an incomplete
        # export never looks complete (#560).  The explicit decisions print as
        # rows with their reason instead of silently disappearing.
        page.set_unreviewed(snapshot.unreviewed_contours if snapshot is not None else 0)
        document = replace(document, notices=document.notices + checklist_notices(page.checklist_summary()))
        marks = page.marked_not_evaluated()
        if not marks:
            return document
        return with_extra_values(
            document,
            not_evaluated_values(
                page.sections.sections,
                marks,
                value_text=tr("report.not_evaluated"),
                decisions=page.checklist_decisions(),
            ),
        )

    # ── The page ────────────────────────────────────────────────────────

    def phrase_store(self) -> ReportPhraseStore:
        """The local phrase library; one file per user profile."""
        return make_report_phrase_store()

    def ensure_page(self) -> ReportModePage:
        """The one report page of the window, created on first entry."""
        if self._page is None:
            stack = self._port.page_stack()
            page = ReportModePage(
                self.current_document,
                projection_provider=self._controller.study_projection,
                phrase_store=self.phrase_store(),
                conclusion_autofill_provider=self.provide_conclusion,
                font_size=self._port.preferences().pdf_font_size,
                translate=tr,
                parent=stack,
            )
            page.patient_field_changed.connect(self.set_patient_field)
            page.measure_requested.connect(self.measure_step)
            page.tool_requested.connect(self.measure_tool)
            page.conclusion_changed.connect(self.set_conclusion)
            page.generated_conclusion_changed.connect(self.remember_generated_conclusion)
            page.open_frames_requested.connect(self.open_frames)
            page.export_requested.connect(self.export_pdf)
            page.export_csv_requested.connect(self.export_csv)
            page.export_json_requested.connect(self.export_json)
            page.print_requested.connect(self.print_sheet)
            page.sign_requested.connect(self.sign_report)
            page.verify_requested.connect(self.verify_signature)
            page.interop_hl7_requested.connect(self.export_hl7)
            page.interop_fhir_requested.connect(self.export_fhir)
            page.interop_pacs_requested.connect(self.send_report_to_pacs)
            page.interop_sr_requested.connect(self.export_sr)
            page.interop_cda_requested.connect(self.export_cda)
            page.finish_requested.connect(lambda: self.set_finished(True))
            page.draft_requested.connect(lambda: self.set_finished(False))
            page.sections.not_evaluated_changed.connect(self.refresh_marks)
            page.preview.profile_changed.connect(self.choose_profile)
            page.preview.inputs_visibility_changed.connect(self.set_inputs_visible)
            page.preview.edit_values_requested.connect(self.edit_values)
            page.preview.value_choice_changed.connect(self.choose_value_source)
            page.value_visibility_changed.connect(self.set_value_hidden)
            page.value_rename_requested.connect(self.rename_value)
            stack.addWidget(page)
            self._page = page
            page.set_checklist_profile(study_profile_id(self._port.preferences()))
            page.set_research_banner(self._port.preferences().report_research_watermark)
        return self._page

    # ── Mode ────────────────────────────────────────────────────────────

    def mode_active(self) -> bool:
        """Whether the active tab shows «Отчёт»."""
        tab = self._active_tab()
        return bool(getattr(tab, "report_mode", False)) if tab is not None else False

    def mode_page(self) -> ReportModePage | None:
        """Tab-coordinator hook: the report page when the active tab is in «Отчёт».

        Also the one place the patient-line switch is synced to the tab: the
        tab coordinator asks on every surface change (tab switch, load, abort),
        which is exactly when the mirror could go stale.
        """
        tab = self._active_tab()
        report = tab is not None and tab.report_mode
        self._port.mirror_report_mode(report)
        self.patient_context_changed.emit()
        if not report or tab is None:
            self._shown_tab_id = ""
            return None
        if self._shown_tab_id != tab.tab_id:
            self._show_tab_sheet(tab)
        return self._page

    def _show_tab_sheet(self, tab: TabSession) -> None:
        # The page is reused. Before exposing it (including its export
        # buttons), render this tab's choices or restore its exact frozen sheet.
        page = self.ensure_page()
        self._shown_tab_id = tab.tab_id
        page.preview.set_profile(self.profile_id())
        self.refresh_inputs_toggle()
        self.refresh_template()
        self.sync_finished(tab)
        page.set_conclusion(tab.report_conclusion)
        if not tab.report_finished:
            page.refresh_now()
        if page.document is not None:
            patient = page.document.patient
            study_uid = self._controller.resolve_study_uid()
            if study_uid and not study_uid.startswith("__"):
                from echo_personal_tool.application.worklist_autofill import autofill_patient_for_study

                try:
                    filled = autofill_patient_for_study(study_uid)
                except (OSError, ValueError):
                    filled = None
                if filled is not None:
                    # worklist demographics only fill fields the study left empty
                    patient = PatientInfo(
                        name=patient.name or filled.name,
                        patient_id=patient.patient_id or filled.patient_id,
                        birth_date=patient.birth_date or filled.birth_date,
                        age=patient.age,
                        sex=patient.sex or filled.sex,
                        study_date=patient.study_date or filled.study_date,
                        height_cm=patient.height_cm,
                        weight_kg=patient.weight_kg,
                        bsa_m2=patient.bsa_m2,
                        physician=patient.physician or filled.physician,
                    )
            page.patient_editor.set_patient(patient)

    def set_mode(self, enabled: bool) -> None:
        """Put the active tab into «Отчёт» (True) or back to «Изображения»."""
        tab = self._active_tab()
        if tab is None:
            return
        tab.report_mode = bool(enabled)
        if enabled:
            self._show_tab_sheet(tab)
        self._port.show_active_surface()
        if not enabled:
            # Back on the images the keys belong to the viewer again, not to
            # the switch button the pointer just left.
            self._port.focus_images()

    def toggle_mode(self) -> None:
        """Ctrl+R: «Изображения» ↔ «Отчёт» of the active tab (spec §4.6)."""
        self.set_mode(not self.mode_active())

    def show_results(self) -> None:
        """Compatibility entry point of the tool panel: one report editor, preview and export."""
        self.set_mode(True)

    def request_refresh(self) -> None:
        """Schedule a sheet rebuild when the active tab shows the report."""
        if self._page is not None and self.mode_active():
            if self._finished(self._active_tab()):
                return
            self._page.request_refresh()

    # ── Patient fields and conclusion ───────────────────────────────────

    def set_patient_field(self, name: str, value: str) -> None:
        """One field of the patient header edited on the page (per tab)."""
        from echo_personal_tool.presentation.report_mode.patient import BP_FIELDS, FIELDS

        tab = self._active_tab()
        if (
            tab is None
            or tab.report_finished
            or name not in {key for key, _ in FIELDS} | {key for key, _ in BP_FIELDS} | {"sex"}
        ):
            return
        tab.report_patient_fields[name] = value
        if name == "sex":
            self.patient_context_changed.emit()
        if self._page is not None:
            self._page.preview.request_refresh()

    def set_conclusion(self, text: str) -> None:
        """Keep the conclusion draft in the tab and refresh the sheet."""
        tab = self._active_tab()
        if tab is None:
            return
        page = self._page
        if self._finished(tab):
            # A finished version is read-only: a stray echo of the editor
            # must not become an edit of the draft the physician signed off.
            if page is not None:
                page.set_conclusion(tab.report_conclusion)
            return
        tab.report_conclusion = str(text)
        # Only the sheet depends on the conclusion: the sections column and the
        # measurement projections are untouched by typing.
        if page is not None and self.mode_active():
            page.preview.request_refresh()

    def provide_conclusion(self) -> ConclusionAutofillResult:
        """Fresh study snapshot + patient context for the conclusion button."""
        from echo_personal_tool.application.report_conclusion import age_years_from_text
        from echo_personal_tool.domain.services.report_conclusion import build_conclusion
        from echo_personal_tool.presentation.report_mode.conclusion_decision import ConclusionDecisionDialog

        tab = self._active_tab()
        page = self.ensure_page()
        if tab is None or self._finished(tab):
            return ConclusionAutofillResult(
                text=page.conclusion,
                generated_block=getattr(tab, "report_generated_conclusion", "") if tab is not None else "",
                status_key="report.conclusion.status.readonly",
                changed=False,
                finding_count=0,
            )
        snapshot = self._report_snapshot()
        patient = self.patient_info(snapshot)
        age = age_years_from_text(patient.age)
        draft = build_conclusion(snapshot, sex=patient.sex, age_years=age)
        choices = {}
        for finding in draft.findings:
            if not finding.candidates:
                continue
            stored = tab.report_conclusion_choices.get(finding.id)
            current = stored[1] if stored and stored[0] == finding.candidate_evidence else None
            selected = ConclusionDecisionDialog.ask(page, finding, current=current)
            if selected is not None:
                choices[finding.id] = (finding.candidate_evidence, selected)
        tab.report_conclusion_choices = choices
        return autofill_conclusion(
            snapshot,
            sex=patient.sex,
            age_years=age,
            choices=choices,
            language=get_language(),
            existing=page.conclusion,
            previous_generated=getattr(tab, "report_generated_conclusion", ""),
        )

    def remember_generated_conclusion(self, block: str) -> None:
        """Remember the exact managed block in the active tab only."""
        tab = self._active_tab()
        if tab is None or self._finished(tab):
            return
        tab.report_generated_conclusion = str(block)

    def measure_step(self, protocol_id: str, step_index: int) -> None:
        """«измерить» in the report sections: back to the images with the step armed."""
        if not protocol_id:
            return
        self.set_mode(False)
        session = self._port.protocol_session()
        if session.active_protocol_id != protocol_id:
            session.start(protocol_id)
        session.arm(step_index)

    def measure_tool(self, tool_id: str) -> None:
        """«измерить» of an organ-profile checklist row (no TP protocol step)."""
        if not tool_id:
            return
        self.set_mode(False)
        self._port.activate_tool(tool_id)

    # ── Format, inputs footnote, hidden rows, template ──────────────────

    def allowed_profiles(self) -> tuple[str, ...]:
        """Report formats the sheet header may show for the active study."""
        from echo_personal_tool.domain.study_profiles import study_profile

        return tuple(study_profile(study_profile_id(self._port.preferences())).report_profile_ids)

    def profile_id(self) -> str:
        """Report format of the active tab (item 7 of the 2026-11-06 list).

        The choice belongs to the tab: one study, one protocol.  Only an
        explicit choice is remembered — the auto-selection is derived on every
        read, so a tab that existed before the study was loaded does not lock
        «УЗИ» in and the answer follows the study that is on screen now.
        """
        tab = self._active_tab()
        allowed = self.allowed_profiles()
        if tab is None:
            return DEFAULT_PROFILE_ID
        stored = getattr(tab, "report_profile", "") or ""
        if stored:
            chosen = normalize_profile_id(stored)
            if chosen not in allowed:
                # A tab saved under another study profile keeps its measurements
                # but not a protocol the current profile does not print.
                chosen = self._unset_format()
        else:
            chosen = self._unset_format()
        page = self._page
        if page is not None:
            page.preview.set_allowed_profiles(allowed)
            page.preview.set_profile(chosen)
            page.phrases.set_profile(chosen)
            page.set_checklist_profile(study_profile_id(self._port.preferences()))
        return chosen

    def _unset_format(self) -> str:
        """Format of a tab that has not chosen one.

        Item 11 of the 2026-11-06 list made the study profile own its protocol,
        so «УЗИ артерий» must not leave a «Протокол ЭхоКГ» on the sheet.  The
        2026-11-16 list (item 6) closes the same gap for the cardiac profile:
        with «Эхокардиография» selected the sheet opens as «ЭхоКГ» — the old
        DICOM-header classification buried it under «УЗИ» whenever the vendor
        header carried no cardiac keywords (Samsung cines in particular).  The
        profile picks only the *default*; the tab can still switch to «УЗИ»
        explicitly.
        """
        from echo_personal_tool.domain.study_profiles import study_profile

        return str(study_profile(study_profile_id(self._port.preferences())).report_profile_id)

    def choose_profile(self, profile_id: str) -> None:
        """The header picked another format: rebuild the sheet of this tab."""
        tab = self._active_tab()
        if tab is None or self._finished(tab):
            # A finished version is read-only; the header buttons are disabled
            # for the same reason, this is the belt to that braces.
            if self._page is not None:
                self._page.preview.set_profile(self.profile_id())
            return
        tab.report_profile = normalize_profile_id(profile_id)
        if self._page is not None:
            self._page.phrases.set_profile(tab.report_profile)
            self._page.preview.request_refresh()

    def set_inputs_visible(self, visible: bool) -> None:
        """The header switched the «Входные данные» footnote (item 8).

        The choice is a user preference — the physician should not have to
        repeat it per study — so it is saved and every open tab follows it.
        """
        # The adapter behind the ``UserPreferences`` contract is a frozen-style dataclass.
        updated = replace(cast(Any, self._port.preferences()), report_show_inputs=bool(visible))
        self._port.store_preferences(updated)
        if self._page is not None:
            self._page.preview.request_refresh()
        self.refresh_inputs_toggle()

    def refresh_inputs_toggle(self) -> None:
        """Mirror the saved preference into the switch of the sheet header."""
        page = self._page
        if page is not None:
            page.preview.set_inputs_visible(bool(getattr(self._port.preferences(), "report_show_inputs", False)))

    def template(self) -> ReportTemplate | None:
        """The printable form of the protocol (item 12 of the 2026-11-06 list).

        An empty preference is the full standard form of older builds, so an
        untouched settings file keeps printing everything.
        """
        from echo_personal_tool.domain.services.report_template import decode_template

        raw = getattr(self._port.preferences(), "report_template_json", "") or ""
        if not raw:
            return None
        return decode_template(raw)

    def refresh_template(self) -> None:
        """Mirror the saved template into the sheet of the report mode."""
        page = self._page
        if page is not None:
            page.set_template(self.template())

    def hidden_value_keys(self) -> set[str]:
        """Keys of the sheet rows the physician hid in the active tab (item 9)."""
        tab = self._active_tab()
        hidden = getattr(tab, "report_hidden_values", None) if tab is not None else None
        return set(hidden) if hidden else set()

    def _saved_exclusions(self) -> set[str]:
        return set(getattr(self._port.preferences(), "report_value_excluded", DEFAULT_REPORT_VALUE_EXCLUDED))

    def hidden_value_labels(self, document: ReportDocument | None = None) -> tuple[tuple[str, str], ...]:
        """Use the unfiltered sheet: even the last hidden row of a group is restorable."""
        local = self.hidden_value_keys()
        hidden = local | self._saved_exclusions()
        if not hidden:
            return ()
        document = document if document is not None else self._unfiltered_document()
        entries = [(v.key, f"{g.title}: {v.label}") for g in document.groups for v in g.values if v.key in hidden]
        # Local quick-hides remain restorable across formats. Do not list
        # global preferences for parameters absent from this study.
        entries.extend((key, key) for key in sorted(local - {key for key, _ in entries}))
        return tuple(entries)

    def edit_values(self, focus_key: str = "") -> None:
        tab = self._active_tab()
        if tab is None or self._finished(tab):
            return
        dialog = ReportValuesDialog(
            self._unfiltered_document().groups,
            self._saved_exclusions() | self.hidden_value_keys(),
            focus_key=focus_key,
            clip_label=self.clip_label,
            parent=self._port.dialog_parent(),
        )
        try:
            if (
                dialog.exec() != ReportValuesDialog.DialogCode.Accepted
                or self._active_tab() is not tab
                or self._finished(tab)
            ):
                return
            edits = dialog.edits()
        finally:
            dialog.deleteLater()
        prefs = self._port.preferences()
        excluded = (self._saved_exclusions() - edits.included) | edits.excluded
        order = prefs.report_value_order
        for rows in edits.reordered_groups:
            order = merge_report_order(order, rows)
        if excluded != self._saved_exclusions() or order != prefs.report_value_order:
            self._port.store_preferences(
                replace(cast(Any, prefs), report_value_excluded=tuple(sorted(excluded)), report_value_order=order)
            )
        tab.report_hidden_values.difference_update(edits.included | edits.excluded)
        for key, candidate in edits.choices.items():
            if candidate:
                tab.report_value_choices[key] = candidate
            else:
                tab.report_value_choices.pop(key, None)
        if self._page is not None:
            self._page.preview.refresh_now()

    def choose_value_source(self, repeat_key: str, candidate_id: str) -> None:
        """Pin one acquisition of a repeat row from the hover card (item 1).

        The choice lives in the tab like every other report edit: an empty
        candidate id returns the row to following the latest acquisition, and
        a finished version keeps its frozen bytes.
        """
        tab = self._active_tab()
        if tab is None or self._finished(tab) or not repeat_key:
            return
        if candidate_id:
            tab.report_value_choices[repeat_key] = candidate_id
        else:
            tab.report_value_choices.pop(repeat_key, None)
        if self._page is not None:
            self._page.preview.refresh_now()

    def set_value_hidden(self, key: str, hidden: bool) -> None:
        """Hide or restore a single row of the sheet (item 9 of the 2026-11-06 list).

        Hiding is a report edit, not a measurement: the set lives in the tab,
        a fresh study clears it, and the finished version refuses it.
        """
        tab = self._active_tab()
        if tab is None or not key or tab.report_finished:
            return
        hidden_keys = getattr(tab, "report_hidden_values", None)
        if hidden_keys is None:
            return
        if hidden:
            hidden_keys.add(key)
        else:
            hidden_keys.discard(key)
            saved = self._saved_exclusions()
            if key in saved:
                self._port.store_preferences(
                    replace(cast(Any, self._port.preferences()), report_value_excluded=tuple(sorted(saved - {key})))
                )
        page = self._page
        if page is not None:
            page.preview.refresh_now()

    def rename_value(self, measurement_id: str, label: str) -> None:
        """Rename a planimetry row from the sheet (item 10 of the 2026-11-06 list).

        The name lives in the contour, so the viewer is asked to change it and
        the usual ``contours_changed`` path carries it to the study session,
        the overlay, the JSON and the DICOM annotations.  A finished sheet is
        read-only: the frozen bytes must not change under the physician.
        """
        if self._finished(self._active_tab()):
            return
        if not measurement_id or not label.strip():
            return
        if not self._port.rename_contour(measurement_id, label.strip()):
            # The contour belongs to another clip: it is still in the study,
            # but this window cannot rewrite a measurement it does not show.
            self._port.show_status(tr("report.rename.not_here"))
            return
        if self._page is not None:
            self._page.preview.request_refresh()

    def refresh_marks(self) -> None:
        """A new «не оценивалось» mark changes the printed sheet (PR-5)."""
        page = self._page
        tab = self._active_tab()
        if page is None or tab is None or self._finished(tab):
            return
        page.request_refresh()

    # ── «откуда значение» (PR-4) ────────────────────────────────────────

    def instance_by_uid(self, sop_instance_uid: str) -> InstanceMetadata | None:
        """Find an instance of the open studies by its SOP Instance UID."""
        if not sop_instance_uid:
            return None
        for study in self._controller.studies:
            for series in study.series:
                for instance in series.instances:
                    if instance.sop_instance_uid == sop_instance_uid:
                        return instance
        return None

    def clip_label(self, sop_instance_uid: str) -> str:
        """Name a clip the way the gallery does (hover card, PR-4)."""
        instance = self.instance_by_uid(sop_instance_uid)
        if instance is None:
            return ""
        return instance_label(instance)

    def open_frames(self, sop_instance_uid: str, frame_index: int) -> None:
        """«Открыть кадры»: back to «Изображения» on the source clip and frame."""
        self.set_mode(False)
        instance = self.instance_by_uid(sop_instance_uid)
        if instance is None:
            self._port.show_status(tr("report.origin.clip_missing"))
            return
        current = self._controller.state_manager.snapshot.instance
        if current is None or current.sop_instance_uid != instance.sop_instance_uid:
            self._port.open_instance(instance)
            self._pending_frame = int(frame_index)
        else:
            self.jump_to_frame(int(frame_index))
        self._port.focus_viewer()

    def jump_to_frame(self, frame_index: int) -> None:
        """Move the cine to a recorded frame; an out-of-range index is ignored."""
        snapshot = self._controller.state_manager.snapshot
        total = int(getattr(snapshot, "total_frames", 0) or 0)
        if total < 1 or frame_index < 0 or frame_index >= total:
            return
        self._controller.set_playing(False)
        self._controller.state_manager.set_frame(frame_index)

    # ── Export, print, finish (PR-5) ────────────────────────────────────

    def _exportable_document(self) -> tuple[ReportModePage, ReportDocument] | None:
        from echo_personal_tool.application.composition import user_session_of
        from echo_personal_tool.domain.models.user import Permission

        session = user_session_of(self._controller)
        if session is not None and not session.can(Permission.EXPORT_DATA):
            self._port.show_status(tr("auth.status.permission_denied"))
            return None
        page = self._page
        if page is None:
            return None
        document = page.document
        if document is None:
            page.set_status(tr("report.export_empty"))
            return None
        return page, document

    def export_pdf(self) -> None:
        """«PDF…» of the export block: rendered in a worker, written atomically.

        Rendering the sheet does not run on the UI thread (S3-04, issue 313):
        the window keeps repainting and the modal progress dialog can cancel the
        export before anything is published.
        """
        exportable = self._exportable_document()
        if exportable is None:
            return
        page, document = exportable
        path = self._port.ask_save_path(
            tr("report.export_pdf_title"),
            str(Path(self.default_report_name())),
            tr("report.pdf_filter"),
        )
        if not path:
            return
        from echo_personal_tool.presentation.report_mode.export_job import (
            PDF_EXPORT_CANCELLED,
            PDF_EXPORT_FINISHED,
            ReportPdfExportJob,
        )

        def _on_outcome(outcome: str, name: str) -> None:
            if outcome == PDF_EXPORT_FINISHED:
                page.set_status(tr("report.export_done", name=name))
            elif outcome == PDF_EXPORT_CANCELLED:
                page.set_status(tr("report.export_cancelled"))
            else:
                page.set_status(tr("report.export_failed"))

        ReportPdfExportJob(
            self._port.dialog_parent(),
            document,
            Path(path),
            font_size=self._port.preferences().pdf_font_size,
            template=self.template(),
            research_banner=self._port.preferences().report_research_watermark,
            on_outcome=_on_outcome,
        ).run()

    def export_csv(self) -> None:
        """«CSV…» of the export block: flat table of the report sheet."""
        from echo_personal_tool.application.report_export import render_report_csv

        self._export_table(".csv", "report.export_csv_title", "report.export_csv_filter", render_report_csv)

    def export_json(self) -> None:
        """«JSON…» of the export block: structured document as JSON."""
        from echo_personal_tool.application.report_export import render_report_json

        self._export_table(".json", "report.export_json_title", "report.export_json_filter", render_report_json)

    def _export_table(
        self,
        suffix: str,
        title_key: str,
        filter_key: str,
        render: Callable[[ReportDocument, Path], object],
    ) -> None:
        """Ask for a path and write *document* there synchronously (CSV / JSON are small)."""
        exportable = self._exportable_document()
        if exportable is None:
            return
        page, document = exportable
        path = self._port.ask_save_path(
            tr(title_key),
            str(Path(self.default_report_name().replace(".pdf", suffix))),
            tr(filter_key),
        )
        if not path:
            return
        try:
            render(document, Path(path))
        except Exception as exc:  # noqa: BLE001 - show the error, keep the app alive
            page.set_status(tr("report.export_failed"))
            self._port.warn(tr(title_key), str(safe_error_category(exc)))
            return
        page.set_status(tr("report.export_done", name=Path(path).name))

    # ── Local Ed25519 signing (issue 624) ─────────────────────────────────

    def _refresh_signing_availability(self) -> None:
        """«Подписать…» exists only for a signed-in user with SIGN_REPORT."""
        from echo_personal_tool.application.composition import user_session_of
        from echo_personal_tool.domain.models.user import Permission

        if self._page is None:
            return
        session = user_session_of(self._controller)
        enabled = session is not None and session.is_multi_user_enabled() and session.can(Permission.SIGN_REPORT)
        self._page.export.set_signing_enabled(enabled)

    def _signing_service(self) -> ReportSigningService | None:
        """Build the application signing service over the bound session/repository."""
        from echo_personal_tool.application.composition import services_of, user_session_of
        from echo_personal_tool.application.report_signing import ReportSigningService

        session = user_session_of(self._controller)
        if session is None:
            return None
        services = services_of(self._controller)
        repository = services.persistence.repository if services is not None else None
        if repository is None:
            repository = self._controller.measurement_persistence.repository
        return ReportSigningService(session=session, repository=repository)

    def _ask_signing_secret(self) -> str | None:
        """Re-enter the password/PIN only at the signing moment (issue 624)."""
        from PySide6.QtWidgets import QInputDialog, QLineEdit

        text, ok = QInputDialog.getText(
            self._port.dialog_parent(),
            tr("report.sign_secret_title"),
            tr("report.sign_secret_label"),
            QLineEdit.EchoMode.Password,
        )
        if not ok or not text:
            return None
        return text

    def _ask_amend_reason(self) -> str | None:
        from PySide6.QtWidgets import QInputDialog, QLineEdit

        text, ok = QInputDialog.getText(
            self._port.dialog_parent(),
            tr("report.amend_reason_title"),
            tr("report.amend_reason_label"),
            QLineEdit.EchoMode.Normal,
        )
        if not ok or not text.strip():
            return None
        return text.strip()

    def sign_report(self) -> None:
        """«Подписать…»: sign the shown sheet, publish stamped PDF + .sig.json (issue 624)."""
        from echo_personal_tool.application.composition import user_session_of
        from echo_personal_tool.domain.exceptions import ReportSignatureError
        from echo_personal_tool.domain.models.report_signature import ReportLifecycle
        from echo_personal_tool.domain.models.user import Permission

        session = user_session_of(self._controller)
        if session is None or not session.can(Permission.SIGN_REPORT):
            self._port.show_status(tr("auth.status.permission_denied"))
            return
        exportable = self._exportable_document()
        if exportable is None:
            return
        page, document = exportable
        path = self._port.ask_save_path(
            tr("report.sign_title"),
            str(Path(self.default_report_name())),
            tr("report.pdf_filter"),
        )
        if not path:
            return
        study_uid = self._controller.resolve_study_uid()
        if not study_uid or study_uid == "__default__":
            page.set_status(tr("report.sign_no_study"))
            return
        secret = self._ask_signing_secret()
        if secret is None:
            return
        service = self._signing_service()
        if service is None:
            page.set_status(tr("report.sign_unavailable"))
            return
        try:
            lifecycle = service.lifecycle_of(study_uid)
            if lifecycle in (ReportLifecycle.SIGNED, ReportLifecycle.AMENDED):
                reason = self._ask_amend_reason()
                if reason is None:
                    return
                service.amend_report(
                    document,
                    study_uid=study_uid,
                    output_path=Path(path),
                    secret=secret,
                    reason=reason,
                    font_size=self._port.preferences().pdf_font_size,
                    template=self.template(),
                    research_banner=self._port.preferences().report_research_watermark,
                )
                page.set_status(tr("report.amend_done", name=Path(path).name))
            else:
                service.sign_report(
                    document,
                    study_uid=study_uid,
                    output_path=Path(path),
                    secret=secret,
                    font_size=self._port.preferences().pdf_font_size,
                    template=self.template(),
                    research_banner=self._port.preferences().report_research_watermark,
                )
                page.set_status(tr("report.sign_done", name=Path(path).name))
        except ReportSignatureError as exc:
            page.set_status(tr("report.sign_failed"))
            self._port.warn(tr("report.sign_title"), f"{tr('report.sign_failed')}: {safe_error_category(exc)}")

    def verify_signature(self) -> None:
        """«Проверить подпись…»: offline check of an exported signed PDF (issue 624)."""
        from PySide6.QtWidgets import QMessageBox

        from echo_personal_tool.presentation.styled_dialogs import styled_open_file

        parent = self._port.dialog_parent()
        chosen, _ = styled_open_file(parent, tr("report.verify_title"), "", tr("report.sig_filter"))
        if not chosen:
            return
        service = self._signing_service()
        page = self._page
        if service is None:
            if page is not None:
                page.set_status(tr("report.sign_unavailable"))
            return
        document = page.document if page is not None else None
        result = service.verify_report_pdf(Path(chosen), document=document)
        if page is not None:
            page.set_status(tr("report.verify_ok") if result.valid else tr("report.verify_failed"))
        if result.receipt is not None:
            receipt = result.receipt
            lines = [
                tr("report.verify_result_ok" if result.valid else "report.verify_result_bad"),
                tr(
                    "report.verify_signer",
                    name=receipt.signer_display_name + (f", {receipt.signer_title}" if receipt.signer_title else ""),
                ),
                tr("report.verify_key", fingerprint=receipt.key_id),
                tr("report.verify_signed_at", at=receipt.signed_at),
                tr(
                    "report.verify_pdf_match",
                    yes_no=tr("report.verify_yes") if result.pdf_match else tr("report.verify_no"),
                ),
                tr(
                    "report.verify_key_archived"
                    if result.key_archived
                    else "report.verify_user_inactive"
                    if not result.user_active
                    else "report.verify_key_active"
                ),
            ]
            QMessageBox.information(parent, tr("report.verify_title"), "\n".join(lines))
        else:
            QMessageBox.warning(
                parent, tr("report.verify_title"), tr("report.verify_result_bad") + f": {result.reason}"
            )

    # ── Outbound interop (issue 625): HL7 v2 / FHIR R4 / Encapsulated PDF ──

    def _interop_service(self) -> Any:
        """The application interop facade over the bound user session."""
        from echo_personal_tool.application.composition import user_session_of
        from echo_personal_tool.application.interop_export import InteropExportService

        return InteropExportService(session=user_session_of(self._controller))

    def _interop_document(self) -> tuple[ReportDocument, str] | None:
        """The shown document and the current study uid, gated by EXPORT_DATA."""
        from echo_personal_tool.application.composition import user_session_of
        from echo_personal_tool.domain.models.user import Permission

        session = user_session_of(self._controller)
        if session is not None and not session.can(Permission.EXPORT_DATA):
            self._port.show_status(tr("auth.status.permission_denied"))
            return None
        page = self._page
        if page is None or page.document is None:
            return None
        study_uid = self._controller.resolve_study_uid()
        if not study_uid or study_uid == "__default__":
            return None
        return page.document, study_uid

    def _signed_receipt_for(self, study_uid: str) -> SignatureReceipt | None:
        """The newest stored receipt for the study, when the protocol was signed."""
        try:
            from echo_personal_tool.application.composition import services_of
            from echo_personal_tool.domain.models.report_signature import validate_receipt_history

            services = services_of(self._controller)
            repository = (
                services.persistence.repository
                if services is not None
                else self._controller.measurement_persistence.repository
            )
            record = repository.load(study_uid)
            if record is None:
                return None
            receipts = validate_receipt_history(record.get("signatures", []))
            return receipts[-1] if receipts else None
        except (OSError, ValueError, KeyError):  # a storage hiccup must not crash interop
            return None

    def export_hl7(self) -> None:
        """«HL7…» of the export block: file export or MLLP send, chosen in a prompt."""
        interop = self._interop_document()
        if interop is None:
            return
        document, study_uid = interop
        page = self._page
        from PySide6.QtWidgets import QInputDialog

        mode, ok = QInputDialog.getItem(
            self._port.dialog_parent(),
            tr("report.interop_hl7_title"),
            tr("report.interop_mode_label"),
            [tr("report.interop_mode_file"), tr("report.interop_mode_send")],
            0,
            False,
        )
        if not ok:
            return
        if mode == tr("report.interop_mode_send"):
            self.send_hl7()
            return
        path = self._port.ask_save_path(
            tr("report.interop_hl7_title"),
            str(Path(self.default_report_name().replace(".pdf", ".hl7"))),
            tr("report.hl7_filter"),
        )
        if not path:
            return
        try:
            service = self._interop_service()
            service.export_hl7_file(
                document,
                Path(path),
                study_uid=study_uid,
                physician=self._port.preferences().report_physician,
                receipt=self._signed_receipt_for(study_uid),
                status="F",
            )
        except (InteropError, TransportPolicyError, OSError, ValueError) as exc:
            if page is not None:
                page.set_status(tr("report.interop_failed"))
            self._port.warn(tr("report.interop_hl7_title"), str(safe_error_category(exc)))
            return
        if page is not None:
            page.set_status(tr("report.export_done", name=Path(path).name))

    def export_fhir(self) -> None:
        """«FHIR…» of the export block: file export or HTTPS send, chosen in a prompt."""
        interop = self._interop_document()
        if interop is None:
            return
        document, study_uid = interop
        page = self._page
        from PySide6.QtWidgets import QInputDialog

        mode, ok = QInputDialog.getItem(
            self._port.dialog_parent(),
            tr("report.interop_fhir_title"),
            tr("report.interop_mode_label"),
            [tr("report.interop_mode_file"), tr("report.interop_mode_send")],
            0,
            False,
        )
        if not ok:
            return
        if mode == tr("report.interop_mode_send"):
            self.send_fhir()
            return
        path = self._port.ask_save_path(
            tr("report.interop_fhir_title"),
            str(Path(self.default_report_name().replace(".pdf", ".fhir.json"))),
            tr("report.fhir_filter"),
        )
        if not path:
            return
        try:
            service = self._interop_service()
            service.export_fhir_file(
                document,
                Path(path),
                study_uid=study_uid,
                physician=self._port.preferences().report_physician,
                receipt=self._signed_receipt_for(study_uid),
                status="F",
            )
        except (InteropError, TransportPolicyError, OSError, ValueError) as exc:
            if page is not None:
                page.set_status(tr("report.interop_failed"))
            self._port.warn(tr("report.interop_fhir_title"), str(safe_error_category(exc)))
            return
        if page is not None:
            page.set_status(tr("report.export_done", name=Path(path).name))

    def export_sr(self) -> None:
        """«SR…» of the export block: TID 5200 file export or PACS send."""
        interop = self._interop_document()
        if interop is None:
            return
        document, study_uid = interop
        page = self._page
        from PySide6.QtWidgets import QInputDialog

        mode, ok = QInputDialog.getItem(
            self._port.dialog_parent(),
            tr("report.interop_sr_title"),
            tr("report.interop_mode_label"),
            [tr("report.interop_mode_file"), tr("report.interop_mode_send")],
            0,
            False,
        )
        if not ok:
            return
        if mode == tr("report.interop_mode_send"):
            self.send_sr_to_pacs()
            return
        path = self._port.ask_save_path(
            tr("report.interop_sr_title"),
            str(Path(self.default_report_name().replace(".pdf", ".dcm"))),
            tr("report.sr_filter"),
        )
        if not path:
            return
        try:
            service = self._interop_service()
            service.export_sr_file(
                document,
                Path(path),
                study_uid=study_uid,
                physician=self._port.preferences().report_physician,
                receipt=self._signed_receipt_for(study_uid),
                accession=self._accession_for(study_uid),
            )
        except (InteropError, TransportPolicyError, OSError, ValueError) as exc:
            if page is not None:
                page.set_status(tr("report.interop_failed"))
            self._port.warn(tr("report.interop_sr_title"), str(safe_error_category(exc)))
            return
        if page is not None:
            page.set_status(tr("report.export_done", name=Path(path).name))

    def send_sr_to_pacs(self) -> None:
        """Send the TID 5200 SR object to the configured PACS via STOW-RS/C-STORE."""
        interop = self._interop_document()
        if interop is None:
            return
        document, study_uid = interop
        page = self._page
        try:
            from echo_personal_tool.application.server_io import load_server_settings, make_upload_targets

            settings = load_server_settings()
            protocol = "stow" if settings.query_source != "dimse" and not settings.dimse_enabled else "dimse"
            uploader, stow_client = make_upload_targets(settings, protocol)
            service = self._interop_service()
            ok = service.send_sr(
                document,
                upload_client=uploader,
                stow_client=stow_client,
                use_stow=(protocol == "stow"),
                study_uid=study_uid,
                physician=self._port.preferences().report_physician,
                receipt=self._signed_receipt_for(study_uid),
                accession=self._accession_for(study_uid),
            )
        except (InteropError, TransportPolicyError, OSError, ValueError) as exc:
            if page is not None:
                page.set_status(tr("report.interop_failed"))
            self._port.warn(tr("report.interop_sr_title"), str(safe_error_category(exc)))
            return
        if page is not None:
            page.set_status(tr("report.interop_sent", ack="SR") if ok else tr("report.interop_failed"))

    def export_cda(self) -> None:
        """«CDA…» of the export block: HL7 CDA R2 XML file export."""
        interop = self._interop_document()
        if interop is None:
            return
        document, study_uid = interop
        page = self._page
        path = self._port.ask_save_path(
            tr("report.interop_cda_title"),
            str(Path(self.default_report_name().replace(".pdf", ".xml"))),
            tr("report.cda_filter"),
        )
        if not path:
            return
        try:
            service = self._interop_service()
            service.export_cda_file(
                document,
                Path(path),
                study_uid=study_uid,
                physician=self._port.preferences().report_physician,
                receipt=self._signed_receipt_for(study_uid),
            )
        except (InteropError, TransportPolicyError, OSError, ValueError) as exc:
            if page is not None:
                page.set_status(tr("report.interop_failed"))
            self._port.warn(tr("report.interop_cda_title"), str(safe_error_category(exc)))
            return
        if page is not None:
            page.set_status(tr("report.export_done", name=Path(path).name))

    def _accession_for(self, study_uid: str) -> str:
        """Accession number from the worklist when the study came from an order."""
        try:
            store_get = getattr(self, "_worklist_lookup", None)
            if store_get is not None:
                item = store_get(study_uid)
                if item is not None:
                    return str(getattr(item, "accession_number", ""))
        except (AttributeError, TypeError, ValueError, KeyError):
            pass  # worklist lookup is best-effort
        return ""

    def send_hl7(self) -> None:
        """Send the ORU^R01 over MLLP/MLLP+TLS to the endpoint asked at send time."""
        from PySide6.QtWidgets import QInputDialog

        interop = self._interop_document()
        if interop is None:
            return
        document, study_uid = interop
        page = self._page
        parent = self._port.dialog_parent()
        host, ok = QInputDialog.getText(
            parent, tr("report.interop_hl7_send_title"), tr("report.interop_host_label"), text="127.0.0.1"
        )
        if not ok or not host.strip():
            return
        port_text, ok = QInputDialog.getInt(
            parent, tr("report.interop_hl7_send_title"), tr("report.interop_port_label"), 6000, 1, 65535
        )
        if not ok:
            return
        use_tls, ok = QInputDialog.getItem(
            parent,
            tr("report.interop_hl7_send_title"),
            tr("report.interop_tls_label"),
            [tr("report.interop_tls_yes"), tr("report.interop_tls_no")],
            1,
            False,
        )
        if not ok:
            return
        try:
            from echo_personal_tool.application.interop_export import make_hl7_mllp_client

            client = make_hl7_mllp_client(
                host=host.strip(), port=port_text, use_tls=(use_tls == tr("report.interop_tls_yes"))
            )
            service = self._interop_service()
            ack = service.send_hl7(
                document,
                client=client,
                study_uid=study_uid,
                physician=self._port.preferences().report_physician,
                receipt=self._signed_receipt_for(study_uid),
            )
        except (InteropError, TransportPolicyError, OSError, ValueError) as exc:
            if page is not None:
                page.set_status(tr("report.interop_failed"))
            self._port.warn(tr("report.interop_hl7_send_title"), str(safe_error_category(exc)))
            return
        if page is not None:
            page.set_status(tr("report.interop_sent", ack=ack.code) if ack.accepted else tr("report.interop_failed"))

    def send_fhir(self) -> None:
        """POST the FHIR R4 Bundle over HTTPS to the endpoint asked at send time."""
        from PySide6.QtWidgets import QInputDialog, QLineEdit

        interop = self._interop_document()
        if interop is None:
            return
        document, study_uid = interop
        page = self._page
        parent = self._port.dialog_parent()
        url, ok = QInputDialog.getText(
            parent,
            tr("report.interop_fhir_send_title"),
            tr("report.interop_url_label"),
            text="https://127.0.0.1:8043/fhir",
        )
        if not ok or not url.strip():
            return
        token, ok = QInputDialog.getText(
            parent, tr("report.interop_fhir_send_title"), tr("report.interop_token_label"), QLineEdit.EchoMode.Password
        )
        if not ok:
            return
        try:
            from echo_personal_tool.application.interop_export import make_fhir_https_client

            client = make_fhir_https_client(base_url=url.strip(), bearer_token=token)
            service = self._interop_service()
            result = service.send_fhir(
                document,
                client=client,
                study_uid=study_uid,
                physician=self._port.preferences().report_physician,
                receipt=self._signed_receipt_for(study_uid),
            )
        except (InteropError, TransportPolicyError, OSError, ValueError) as exc:
            if page is not None:
                page.set_status(tr("report.interop_failed"))
            self._port.warn(tr("report.interop_fhir_send_title"), str(safe_error_category(exc)))
            return
        if page is not None:
            page.set_status(
                tr("report.interop_sent", ack=str(result.status_code))
                if result.accepted
                else tr("report.interop_failed")
            )

    def send_report_to_pacs(self) -> None:
        """«В PACS…» of the export block: DICOM Encapsulated PDF via the configured server."""
        interop = self._interop_document()
        if interop is None:
            return
        document, study_uid = interop
        page = self._page
        try:
            from echo_personal_tool.application import report_export
            from echo_personal_tool.application.server_io import load_server_settings, make_upload_targets
            from echo_personal_tool.domain.models.report_signature import build_stamp

            stamp = build_stamp(receipt) if (receipt := self._signed_receipt_for(study_uid)) is not None else None
            rendered = report_export.render_report(
                document,
                font_size=self._port.preferences().pdf_font_size,
                template=self.template(),
                stamp=stamp,
                research_banner=self._port.preferences().report_research_watermark,
            )
            settings = load_server_settings()
            protocol = "stow" if settings.query_source != "dimse" and not settings.dimse_enabled else "dimse"
            uploader, stow_client = make_upload_targets(settings, protocol)
            service = self._interop_service()
            spec = service.build_encapsulated_pdf_spec(
                document,
                study_uid=study_uid,
                pdf_bytes=rendered.pdf,
                receipt=receipt,
            )
            ok = service.send_encapsulated_pdf(
                spec, upload_client=uploader, stow_client=stow_client, use_stow=(protocol == "stow")
            )
        except (InteropError, TransportPolicyError, OSError, ValueError) as exc:
            if page is not None:
                page.set_status(tr("report.interop_failed"))
            self._port.warn(tr("report.interop_pacs_title"), str(safe_error_category(exc)))
            return
        if page is not None:
            page.set_status(tr("report.interop_sent", ack="OK") if ok else tr("report.interop_failed"))

    def print_sheet(self) -> None:
        """«Печать…» of the export block: the rendered sheet bytes, nothing re-rendered."""
        page = self._page
        if page is None or not page.pdf_bytes:
            if page is not None:
                page.set_status(tr("report.print_empty"))
            return
        printer = self._port.ask_printer()
        if printer is None:
            return
        self.print_to(printer)

    def print_to(self, printer: Any) -> bool:
        """Print the sheet bytes on *printer*; the status line reports the outcome."""
        page = self._page
        if page is None:
            return False
        ok = bool(print_report_pdf(page.pdf_bytes, printer))
        page.set_status(tr("report.print_done") if ok else tr("report.print_failed"))
        return ok

    def set_finished(self, finished: bool) -> None:
        """«Завершить» / «Новый черновик» of the active tab.

        Finishing fixes *the bytes currently on the sheet* — that is the
        version the physician signed off, not a later recomputation.  Editing
        starts a new draft, and the fixed version is dropped then: storing
        versions is a separate decision together with QH.
        """
        tab = self._active_tab()
        page = self.ensure_page()
        if tab is None:
            return
        if finished:
            version = page.preview.version()
            if version is None:
                page.set_status(tr("report.finish_empty"))
                return
            tab.report_finished = True
            tab.report_frozen_sheet = version
            page.set_finished(True)
            page.set_status(tr("report.finish_done"))
            return
        tab.report_finished = False
        tab.report_frozen_sheet = None
        page.set_finished(False)
        page.set_status(tr("report.draft_done"))
        page.refresh_now()

    def sync_finished(self, tab: TabSession | None) -> None:
        """Show the tab's own finished version or its live draft."""
        page = self._page
        if page is None or tab is None:
            return
        finished = self._finished(tab)
        frozen_sheet = getattr(tab, "report_frozen_sheet", None)
        if finished and frozen_sheet is not None:
            page.set_finished(True)
            page.preview.set_version(frozen_sheet)
            return
        page.set_finished(False)
        # The format buttons of the header follow the frozen state of the sheet
        # (item 7): a finished version keeps its format until «Новый черновик».
        page.preview.set_profile_locked(finished)


def build_window_report_coordinator(window: Any) -> ReportCoordinator:
    """Create a :class:`ReportCoordinator` backed by late-bound window callbacks.

    Every entry binds late through ``window`` so tests that replace
    ``_show_status`` or viewer methods after construction are observed, and
    widgets created later during startup are resolved on first report use.
    """
    from PySide6.QtWidgets import QMessageBox

    from echo_personal_tool.application.user_preferences import save_user_preferences

    def store_preferences(preferences: UserPreferences) -> None:
        window._user_preferences = preferences
        save_user_preferences(preferences)

    def focus_images() -> None:
        if window._viewer_stack.currentWidget() is window._viewer:
            window._viewer.setFocus()

    def open_instance(instance: InstanceMetadata) -> None:
        window._gallery.select_instance(instance)
        window._on_instance_selected(instance)

    def mirror_report_mode(report: bool) -> None:
        system_bar = getattr(window, "_system_bar", None)
        if system_bar is not None:
            system_bar.set_report_mode(report)

    def ask_save_path(title: str, default_name: str, file_filter: str) -> str:
        from echo_personal_tool.presentation.styled_dialogs import styled_save_file

        path, _ = styled_save_file(window, title, default_name, file_filter)
        return str(path or "")

    def warn_dialog(title: str, text: str) -> None:
        QMessageBox.warning(window, title, text)

    port = ReportWindowPort(
        active_tab=lambda: window._tabs.active,
        preferences=lambda: window._user_preferences,
        store_preferences=store_preferences,
        page_stack=lambda: window._main_stack,
        dialog_parent=lambda: window,
        show_status=lambda message: window._show_status(message),
        show_active_surface=lambda: window._update_main_stack(),
        focus_images=focus_images,
        focus_viewer=lambda: window._viewer.setFocus(),
        open_instance=open_instance,
        protocol_session=lambda: window.protocol.ensure_session(),
        activate_tool=lambda tool_id: window._tool_panel.activate_tool(tool_id),
        rename_contour=lambda measurement_id, label: window._viewer.rename_contour_measurement(measurement_id, label),
        mirror_report_mode=mirror_report_mode,
        ask_save_path=ask_save_path,
        warn=warn_dialog,
        ask_printer=lambda: ask_report_printer(window),
    )
    return ReportCoordinator(window._controller, port, parent=window)
