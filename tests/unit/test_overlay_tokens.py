"""The colours of the markup on the image: tokens, cycles, migrated widgets (UI-0 PR-7b).

The redesign fixes the rule in UD-16: what is drawn *on* the image (contours,
calipers, captions, points, phase markers, spectrum traces) is a semantic group
of its own — ``overlay.*`` — and neither the theme nor the accent colour
changes it. UI-0 PR-7 moved the viewer; this file covers the tail: the Doppler
spectrum, the speckle overlay, the M-mode tools, the ECG strip, the strain
curves and the Multiview marker strip.

Three things are checked here:

* the group stays theme-independent (every theme has the same value, so no
  theme switch can repaint the measurement a clinician is reading);
* the values are the colours the widgets had before the move — a migration
  that changed a colour would be a visible change and is not allowed;
* the migrated modules hold no raw literal any more, and no token is dead.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

from echo_personal_tool.presentation.theme import palettes, tokens

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src" / "echo_personal_tool"
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_ui_colors  # noqa: E402

#: Every colour of the overlay group, exactly as the widgets spelled it before
#: the migration. A change here is a change of the interface, not a refactor.
OVERLAY_VALUES = {
    # contours, calipers, points, phase markers (UI-0 PR-7)
    "overlay.contour.manual": "#ff6f00",
    "overlay.contour.auto": "#00bcd4",
    "overlay.contour.model": "#4caf50",
    "overlay.caliper": "#ffb300",
    "overlay.caliper.doppler": "#29b6f6",
    "overlay.label": "#9e9e9e",
    "overlay.point": "#4fc3f7",
    "overlay.marker": "#ab47bc",
    # the Doppler spectrum and the vessel trace
    "overlay.peak": "#ff6f00",
    "overlay.peak.fill": "#ffb74d",
    "overlay.peak.caption": "#e8eef4",
    "overlay.peak.guide": "#ff9800",
    "overlay.doppler.roi": "#90caf9",
    "overlay.doppler.baseline": "#78909c",
    "overlay.doppler.trace": "#1565c0",
    "overlay.doppler.envelope": "#00e5ff",
    "overlay.doppler.interval": "#00897b",
    "overlay.doppler.interval.text": "#80cbc4",
    "overlay.doppler.region": "#ffaa00",
    "overlay.doppler.point": "#ffffff",
    # speckle tracking
    "overlay.speckle.zone": "#42a5f5",
    "overlay.speckle.arrow": "#ffeb3b",
    "overlay.speckle.legend": "#ffd54f",
    "overlay.speckle.rejected": "#ff1744",
    "overlay.speckle.unverified": "#ffb300",
    "overlay.speckle.ed": "#00e676",
    "overlay.speckle.es": "#ff1744",
    # M-mode, the strain curves, the ECG strip
    "overlay.mmode.es": "#ff5722",
    "overlay.strain.longitudinal": "#2196f3",
    "overlay.strain.radial": "#f44336",
    "overlay.strain.ed": "#4caf50",
    "overlay.strain.es": "#ff9800",
    "overlay.ecg.wave": "#00ff88",
    # the Multiview marker strip
    "overlay.multiview.track": "#3a3f45",
    "overlay.multiview.window": "#40e2de",
    "overlay.multiview.playhead": "#8ab4f8",
    "overlay.multiview.badge.text": "#0b0d10",
    "overlay.multiview.caption": "#d7dde3",
}

#: The widgets UI-0 PR-7b moved to the tokens. They must stay free of raw
#: colour literals: a literal in a painter is a colour that no theme can reach.
MIGRATED = (
    "presentation/doppler_overlay.py",
    "presentation/doppler_widget.py",
    "presentation/speckle_overlay.py",
    "presentation/multiview_marker_strip.py",
    "presentation/mmode_measurement.py",
    "presentation/mmode_scan_line.py",
    "presentation/mmode_widget.py",
    "presentation/ecg_strip_widget.py",
    "presentation/strain_curve_widget.py",
)


class TestOverlayVocabulary:
    def test_every_overlay_token_is_listed_here(self):
        """The pinned table covers the whole group — a new token needs a colour here."""
        declared = {spec.name for spec in tokens.TOKENS if spec.group == tokens.GROUP_OVERLAY}
        assert declared == set(OVERLAY_VALUES), sorted(declared ^ set(OVERLAY_VALUES))

    @pytest.mark.parametrize("theme_id", palettes.THEME_IDS)
    def test_the_group_does_not_depend_on_the_theme(self, theme_id):
        for name in OVERLAY_VALUES:
            assert palettes.PALETTES[theme_id][name] == OVERLAY_VALUES[name], (theme_id, name)

    def test_the_group_is_a_real_token_group(self):
        """Nothing outside the group borrows an ``overlay.`` name, and vice versa."""
        for spec in tokens.TOKENS:
            assert (spec.name.startswith("overlay.")) == (spec.group == tokens.GROUP_OVERLAY)

    def test_tokens_are_declared_once(self):
        names = [spec.name for spec in tokens.TOKENS]
        assert len(names) == len(set(names))


class TestOverlayCycle:
    def test_marker_cycle_is_pinned(self):
        """The six marker colours of a Multiview pane, in the order they are painted."""
        assert palettes.overlay_cycle("overlay.multiview.markers") == (
            "#ff5252",
            "#ffb300",
            "#40c4ff",
            "#69f0ae",
            "#e040fb",
            "#ffd740",
        )

    def test_marker_colours_are_distinguishable(self):
        cycle = palettes.overlay_cycle("overlay.multiview.markers")
        assert len(set(cycle)) == len(cycle), "two markers of a pane must not share a colour"

    def test_only_declared_cycles_exist(self):
        assert set(tokens.OVERLAY_CYCLES) == {"overlay.multiview.markers"}

    def test_an_unknown_cycle_is_an_error(self):
        with pytest.raises(KeyError, match="unknown overlay cycle"):
            palettes.overlay_cycle("overlay.does.not.exist")


class TestMigratedWidgets:
    @pytest.mark.parametrize("relative", MIGRATED)
    def test_no_raw_colour_literal(self, relative):
        text = (SRC_ROOT / relative).read_text(encoding="utf-8")
        assert check_ui_colors.count_literals(text) == 0, relative

    @pytest.mark.parametrize("relative", MIGRATED)
    def test_markup_goes_through_a_token(self, relative):
        text = (SRC_ROOT / relative).read_text(encoding="utf-8")
        assert "get_theme_tokens()" in text, relative

    def test_ratchet_counts_the_group_only_in_the_palette(self):
        """``palettes.py`` stays the only file of the theme with raw colours."""
        counts = check_ui_colors.scan(roots=("presentation/theme",), whitelist=("presentation/theme/palettes.py",))
        assert counts == {}, counts

    def test_the_ratchet_is_at_the_lowered_baseline(self):
        baseline = check_ui_colors.load_baseline(check_ui_colors.DEFAULT_BASELINE)
        assert baseline["total"] == check_ui_colors.total_of(check_ui_colors.scan())

    def test_the_cycle_name_is_not_a_token(self):
        """A cycle is a list of colours; it must not sneak into the token tables."""
        assert "overlay.multiview.markers" not in {spec.name for spec in tokens.TOKENS}
        assert "overlay.multiview.markers" not in palettes.PALETTES[palettes.THEME_DARK]

    def test_marker_color_cycles_over_the_pinned_cycle(self):
        from echo_personal_tool.presentation.multiview_marker_strip import marker_color

        cycle = palettes.overlay_cycle("overlay.multiview.markers")
        assert [marker_color(index) for index in range(len(cycle))] == list(cycle)
        assert marker_color(len(cycle)) == cycle[0]
