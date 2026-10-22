"""Tests for the «3 Point Contour» overview screen (plan §5.3 п.2).

Acceptance criteria covered here:

* Renders offscreen (Qt offscreen platform) without crashes, which is the
  first gate — the vendor screen must come up headlessly so CI can screenshot
  it and so users can export PNG from a script.
* Every per-view number comes out of ``StrainStudy``; the overview widget
  never recomputes GLS or the average.
* A view that was never analysed shows the "no data" placeholder instead of
  a fabricated zero — the same honesty rule the report follows.
* The 18-segment bull's-eye is built from the study's merged segments (the
  same merge ``strain_report_from_study`` uses), not from the last analysed
  view alone.
"""

from __future__ import annotations

import numpy as np
import pytest

pytestmark = pytest.mark.gui


@pytest.fixture(autouse=True)
def _setup_qapp():
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _make_analysis(
    view: str,
    *,
    gls: float = -19.0,
    qc_status: str = "valid",
    n_segments: int = 6,
    ed_index: int = 0,
    es_index: int = 18,
) -> StrainAnalysis:
    """Build a minimal :class:`StrainAnalysis` for one view."""
    from echo_personal_tool.domain.models.ste_analysis import StrainAnalysis

    # Realistic per-view segment ids (A4C: 3,6,9,12,15,18; A2C: 1,4,7,10,13,16; A3C: 2,5,8,11,14,17).
    from echo_personal_tool.domain.services.segment_map import view_segment_ids

    seg_ids = list(view_segment_ids(view))[:n_segments]
    segments = {int(s): float(gls) + 0.3 * (i - 2) for i, s in enumerate(seg_ids)}
    quality = {int(s): 0.9 for s in seg_ids}
    ttp = {int(s): 320.0 + i * 5 for i, s in enumerate(seg_ids)}
    return StrainAnalysis(
        view=view,
        gls=float(gls),
        ess=float(gls) + 1.5,
        peak=float(gls),
        qc_status=qc_status,
        qc_reasons=() if qc_status == "valid" else ("strain.qc.reason.low_coverage",),
        qc_coverage=0.98 if qc_status == "valid" else 0.55,
        ed_index=ed_index,
        es_index=es_index,
        avc_index=es_index,
        avc_source="ecg",
        heart_rate_bpm=66.0,
        frame_time_ms=21.7,
        segment_values=segments,
        segment_quality=quality,
        segment_ttp_ms=ttp,
        global_curve=np.linspace(0, gls, 30),
    )


def _make_snapshot(view: str, *, frame_size=(120, 100), n_frames: int = 30) -> ViewSnapshot:
    """Build a :class:`ViewSnapshot` with a synthetic ED frame and a contour."""
    from echo_personal_tool.ui.ste.overview_screen import ViewSnapshot

    h, w = frame_size
    rng = np.random.default_rng(42)
    frames = rng.integers(0, 255, size=(n_frames, h, w), dtype=np.uint8)
    # Endo contour: ellipse between apex (w/2, h*0.1) and base (w/2 ± w*0.4, h*0.9).
    t = np.linspace(0, np.pi, 20)
    cx, cy = w / 2.0, h * 0.5
    rx, ry = w * 0.35, h * 0.4
    contour = np.stack([cx + rx * np.cos(t + np.pi / 2), cy + ry * np.sin(t + np.pi / 2)], axis=1)
    # Endo positions: equally spaced samples along the contour.
    endo = contour[::3]
    ecg = np.sin(np.linspace(0, 4 * np.pi, n_frames)) * 0.5 + 0.5
    return ViewSnapshot(
        view=view,
        ed_frame=frames[0],
        ed_contour=contour,
        es_contour=contour * 0.95,
        endo_positions_ed=endo,
        ecg_trace=ecg,
        ecg_frame_time_ms=21.7,
        ed_index=0,
        es_index=18,
        frame_count=n_frames,
        heart_rate_bpm=66.0,
        kernels=[],
    )


class TestOverviewScreen:
    def _make_widget(self):
        from echo_personal_tool.ui.ste.overview_screen import OverviewScreen

        return OverviewScreen()

    def _show(self, w) -> None:
        """Show the widget and pump events so child visibility settles offscreen."""
        from PySide6.QtWidgets import QApplication

        w.resize(1200, 700)
        w.show()
        QApplication.processEvents()

    def test_construction_offscreen(self):
        """Widget constructs and paints offscreen (CI gate)."""
        from echo_personal_tool.domain.models.ste_analysis import StrainStudy

        w = self._make_widget()
        w.set_study(StrainStudy())
        self._show(w)
        pix = w.grab()
        assert pix.width() > 0
        assert pix.height() > 0

    def test_empty_study_shows_no_data_placeholders(self):
        """Without analyses every card keeps its "no data" placeholder."""
        from echo_personal_tool.domain.models.ste_analysis import StrainStudy

        w = self._make_widget()
        w.set_study(StrainStudy())
        self._show(w)
        # The GLS_AV label must be "--" when no views have numbers.
        assert "--" in w._avg_label.text()
        for card in w._cards.values():
            assert not card._placeholder.isHidden()

    def test_per_view_numbers_come_from_study(self):
        """GLS chips and cards display the exact study values — no recomputation."""
        from echo_personal_tool.domain.models.ste_analysis import StrainStudy

        a4c = _make_analysis("A4C", gls=-20.0)
        a2c = _make_analysis("A2C", gls=-18.5)
        study = StrainStudy.from_analyses([a4c, a2c])
        w = self._make_widget()
        w.set_study(study)
        self._show(w)
        # GLS_AV is the mean of valid views only — and must match study.gls_average().
        expected_av = study.gls_average()
        assert expected_av is not None
        assert f"{expected_av:.1f}%" in w._avg_label.text()
        # Per-view chips carry their numbers.
        assert "-20.0%" in w._view_chips["A4C"].text()
        assert "-18.5%" in w._view_chips["A2C"].text()
        # A3C was never analysed → chip must show "--" (not a fabricated 0).
        assert "A3C --" in w._view_chips["A3C"].text()
        # Cards show/hide the placeholder accordingly (isHidden reflects explicit
        # visibility, independent of whether the parent window is currently on
        # screen — the effective isVisible() only becomes True after show()).
        assert w._cards["A4C"]._placeholder.isHidden()
        assert w._cards["A2C"]._placeholder.isHidden()
        assert not w._cards["A3C"]._placeholder.isHidden()
        # The card for an analysed view shows the matching GLS value.
        assert "-20.0%" in w._cards["A4C"]._value.text()

    def test_bullseye_uses_merged_segments(self):
        """18-segment bull's-eye merges A4C + A2C + A3C (not just the last view)."""
        from echo_personal_tool.domain.models.ste_analysis import StrainStudy

        a4c = _make_analysis("A4C", gls=-20.0)
        a2c = _make_analysis("A2C", gls=-18.0)
        a3c = _make_analysis("A3C", gls=-16.0)
        study = StrainStudy.from_analyses([a4c, a2c, a3c])
        w = self._make_widget()
        w.set_study(study)
        self._show(w)
        merged = study.bullseye_segments()
        # 6 + 6 + 6 = 18 segments when all three views are valid.
        assert len(merged) == 18
        # Every merged segment reached the bull's-eye widget (no silent drop).
        assert set(w._bullseye._segment_strains.keys()) == set(merged.keys())

    def test_snapshot_draws_contours(self):
        """When a snapshot is supplied the card renders ED/ES contours + kernels."""
        from echo_personal_tool.domain.models.ste_analysis import StrainStudy

        a4c = _make_analysis("A4C", gls=-21.0)
        study = StrainStudy.from_analyses([a4c])
        w = self._make_widget()
        snap = _make_snapshot("A4C")
        w.set_snapshot(snap)
        w.set_study(study)
        self._show(w)
        card = w._cards["A4C"]
        # The ED and ES contours were created (items exist).
        assert card._ed_item is not None
        assert card._es_item is not None
        # Endo kernel scatter plot exists and shows the snapshot points.
        assert card._kitem is not None
        assert card._kitem.getData()[0].size > 0
        # ECG strip visible because we supplied a trace.
        assert not card._ecg_plot.isHidden()
        assert card._ecg_item is not None

    def test_missing_ecg_hides_strip(self):
        """Never draw a synthetic ECG when the snapshot has none (plan §6.5)."""
        from echo_personal_tool.domain.models.ste_analysis import StrainStudy

        a4c = _make_analysis("A4C", gls=-20.0)
        study = StrainStudy.from_analyses([a4c])
        w = self._make_widget()
        snap = _make_snapshot("A4C")
        snap.ecg_trace = None
        w.set_snapshot(snap)
        w.set_study(study)
        self._show(w)
        assert w._cards["A4C"]._ecg_plot.isHidden()

    def test_review_view_shows_mark(self):
        """review/invalid views carry the ▲/■ mark and the matching tooltip.

        (review uses ▲ instead of the Unicode warning sign so the glyph is
        reliably present in every font and cannot be confused with the
        invalid-block ■, which is the same visual cue QFont uses when a glyph
        is missing.)
        """
        from echo_personal_tool.domain.models.ste_analysis import StrainStudy
        from echo_personal_tool.ui.ste.overview_screen import _STATUS_MARK

        a4c = _make_analysis("A4C", gls=-20.0, qc_status="valid")
        a2c = _make_analysis("A2C", gls=-14.0, qc_status="review")
        a3c = _make_analysis("A3C", gls=-4.0, qc_status="invalid")
        study = StrainStudy.from_analyses([a4c, a2c, a3c])
        w = self._make_widget()
        w.set_study(study)
        # Chips carry the status mark glyph next to the value.
        assert _STATUS_MARK["valid"] in w._view_chips["A4C"].text()
        assert _STATUS_MARK["review"] in w._view_chips["A2C"].text()
        assert _STATUS_MARK["invalid"] in w._view_chips["A3C"].text()

    def test_offscreen_render_to_pixmap(self):
        """End-to-end render: three views with snapshots → QPixmap of non-zero size."""
        from echo_personal_tool.domain.models.ste_analysis import StrainStudy

        a4c = _make_analysis("A4C", gls=-20.0)
        a2c = _make_analysis("A2C", gls=-18.0)
        a3c = _make_analysis("A3C", gls=-16.0)
        study = StrainStudy.from_analyses([a4c, a2c, a3c])
        w = self._make_widget()
        w.resize(1280, 760)
        for v in ("A4C", "A2C", "A3C"):
            w.set_snapshot(_make_snapshot(v))
        w.set_study(study)
        w.show()
        # Process events so layouts and paint events actually fire offscreen.
        from PySide6.QtWidgets import QApplication

        QApplication.processEvents()
        pix = w.grab()
        assert pix.width() >= 1000
        assert pix.height() >= 500
