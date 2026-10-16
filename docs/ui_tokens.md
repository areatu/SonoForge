# Design tokens of the interface

> [Русская версия](ui_tokens_ru.md)

The colours of SonoForge are described once, as **semantic tokens** — the role
of a colour, not its shade. The raw colours of a theme live in a single
module; everything else (stylesheets, item delegates, painted widgets) asks
for a token.

The system was introduced by UI-0 PR-1 (redesign spec §5) and is extended by
the following PRs of the package: the areas are moved to tokens one by one,
and the legacy palette disappears in UI-8.

## The three layers

| Layer | Module | What it holds |
|-------|--------|---------------|
| Palette | `presentation/theme/palettes.py` | The raw colours of every theme. The only place where a hex literal is allowed. |
| Tokens | `presentation/theme/tokens.py` | The vocabulary: the role of a colour and the mapping to the former palette keys. |
| Consumers | `presentation/theme/qss.py`, widgets | Read tokens, never colours. |

`presentation/dark_theme.py` is the facade: it still hands out the former
28-key palette (`get_theme_palette()`) and the same stylesheet
(`build_clinical_stylesheet()`), so the call sites can be moved one area at a
time.

The contrast rules (WCAG 2.1 AA) live in `presentation/theme/contrast.py` — the
CI script `scripts/check_contrast.py` only wraps them, so the rule and the
check cannot drift apart. `presentation/theme_tokens.py` stays as a facade of
the former name: it re-exports the package and goes away together with the
legacy palette in UI-8.

## The token groups

| Group | Tokens | Meaning |
|-------|--------|---------|
| `surface.*` | `surface.0` … `surface.3`, `surface.hover`, `surface.pressed` | Backgrounds, from the window to the most raised element |
| `line.*` | `line.1`, `line.2` | Separators and control borders |
| `text.*` | `text.1`, `text.2`, `text.3`, `text.disabled` | Primary text, secondary text, hints, disabled elements |
| `accent.*` | `accent`, `accent.text`, `accent.on`, `accent.tab`, `accent.selected` | The active tool, the primary action, the selected item |
| `state.*` | `state.ok`, `state.warn`, `state.err`, `state.info`, `state.attention.bg/text`, `state.danger.*` | Interface states; the fixed attention pair marks the next measurement step |
| `provenance.*` | `provenance.manual`, `.missing`, `.default`, `.warning` | Fixed colors for calculator value sources and warnings |
| `focus.*` | `focus.ring` | The keyboard focus ring |
| `progress.*`, `slider.*` | `progress.text`, `slider.track`, `slider.fill` | Progress bar and slider |
| `paper.*` | `paper.surface`, `paper.text`, `paper.text.dim`, `paper.line`, `paper.highlight`, `paper.done` | The A4 report sheet and the measurement worksheet; paper colors stay fixed in every theme |
| `overlay.*` | contours, calipers, labels, points, markers | The drawing on the image; the theme and the accent colour do not change it (arrives with UI-0 PR-7) |

Sizes follow the grid of the spec: 4 px spacing, radii 4/6/8/10, control
heights 28/32, icons 16/18, font sizes 11.5/12.5/13.5/15/24.

## The rules

1. **No raw colours outside the palette module.** `scripts/check_ui_colors.py`
   counts the hex literals in `presentation/`, `ui/` and `constructor/` and
   compares the number with `scripts/ui_colors_baseline.json`. The number may
   only fall; a new literal fails the build.
2. **The contrast is checked.** `scripts/check_contrast.py` verifies the
   token pairs against WCAG 2.1 AA. The fixed next-step marker has a 14.04:1
   text-to-background ratio in every theme (minimum 4.5:1). The graphite theme
   is an error, the former themes are a report — their colours were never
   agreed with anyone.
3. **The former themes do not change.** The stylesheet of the navy, light and
   VS Code themes is pinned by golden files
   (`tests/fixtures/ui/stylesheet_*.golden.txt`); a change is a change of the
   interface and needs a decision, not a merge.
4. **The drawing on the image is not the theme.** The colours of the contours
   and the calipers are the `overlay.*` group; the theme does not change them.

## The former palette keys

The 28 keys of `get_theme_palette()` are computed from the tokens:

| Former key | Token | Former key | Token |
|------------|-------|------------|-------|
| `bg_dark` | `surface.0` | `reset_bg1` | `state.danger.bg` |
| `bg_panel` | `surface.1` | `reset_bg2` | `state.danger.bg2` |
| `bg_control` | `surface.2` | `reset_hov1` | `state.danger.bg.hover` |
| `bg_button` | `surface.3` | `reset_hov2` | `state.danger.bg2.hover` |
| `bg_button_hover` | `surface.hover` | `reset_pressed` | `state.danger.bg.pressed` |
| `bg_button_pressed` | `surface.pressed` | `reset_border` | `state.danger.border` |
| `accent` | `accent` | `reset_border_hov` | `state.danger.border.hover` |
| `accent_bright` | `accent.text` | `reset_text` | `state.danger.text` |
| `accent_tab` | `accent.tab` | `progress_text` | `progress.text` |
| `accent_selected` | `accent.selected` | `hover_btn1` | `surface.hover.alt` |
| `text` | `text.1` | `success` | `state.ok` |
| `text_dim` | `text.2` | `warning` | `state.warn` |
| `border` | `line.1` | `error` | `state.err` |
| `slider_track` | `slider.track` | | |
| `slider_fill` | `slider.fill` | | |

The tokens the former palette had no key for are derived: `text.3` and
`text.disabled` follow `text.2`, `line.2` follows `line.1`, `focus.ring` and
`state.info` follow `accent`.

## The "system" theme

`presentation/theme/system_theme.py` resolves the system colour scheme in one
place: Windows reads `AppsUseLightTheme` from the registry (`0` — the system
is dark), macOS asks `defaults` for the interface style, and the other
desktops keep the dark theme of the application. The palette and the logo
follow the same answer — before, they were asked separately and disagreed.

## How to use a token

```python
from echo_personal_tool.presentation.theme.palettes import get_palette_tokens

tokens = get_palette_tokens("graphite")
painter.setPen(QColor(tokens["accent"]))
```

Inside a widget, the palette of the running theme is at hand through the
facade:

```python
from echo_personal_tool.presentation.dark_theme import get_theme_palette

palette = get_theme_palette()  # the former 28 keys, computed from the tokens
```

New code must not use the former keys: read the token directly. The keys stay
until the areas are moved (UI-0 PR-3…PR-7).

## Migration state

| PR | Area | What was done |
|----|------|---------------|
| PR-3 | Top bar and status bar | `dark_theme.get_theme_tokens()` — the roles of the running theme for widgets; the glyphs of the bar, the tabs and the rail take `text.1`; the teal claim of the references button is gone (six literals) and the button is an ordinary bar button; the permanent status-bar labels come from `MainWindow.apply_status_bar_tokens()` (`state.warn`, `text.3`); the rail no longer draws an opaque black tile behind its glyphs (`fill(0)` → transparent fill). Ratchet: 378 → 367. |
| PR-4 | Panels and menus | Not a mechanical removal of ten literals: existing semantic colors are represented by fixed `state.attention.*`, `provenance.*` and `paper.highlight`/`paper.done` tokens in every theme. The next-step marker and text keep their appearance; contrast is 14.04:1 (minimum 4.5:1). Ratchet: 367 → 357. |
| PR-5 | Reference | `structured_reference_widget`, `ase_reference_dialog` and the web reference read token roles (`surface.*`, `text.1/2`, `line.1`, `accent.tab`, `progress.text`, `state.*`); the close-button hover is `state.danger.solid`/`state.danger.on`; the web bridge maps its CSS vars onto tokens. Kept: clinical gradation colours (UI-5 owns them), the `#ffffff` on `accent.tab` (navy pixel-match) and the SVG asset search patterns. Ratchet: 367 → 359. |
| PR-6 | Orthanc and delegates | planned |
| PR-7 | Viewer and overlays | planned: the `overlay.*` values without a colour change |

A widget reads the tokens of the running theme through the facade — the same
way the rail does:

```python
from echo_personal_tool.presentation.dark_theme import get_theme_tokens

tokens = get_theme_tokens()   # the roles of the current theme; a copy
painter.setPen(QColor(tokens["text.1"]))
```

A theme change is the only repaint mechanism: a widget never asks «is the
theme dark?».
