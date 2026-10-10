# Project website (GitHub Pages)

Source of <https://areatu.github.io/SonoForge/> — a static landing page for SonoForge,
bilingual (EN/RU toggle), no framework, no build tooling beyond a shell script.

| File | Purpose |
|---|---|
| `index.html` | The page. Every piece of copy exists twice, as `lang="en"` / `lang="ru"` siblings; CSS shows only the active language. |
| `styles.css` | Dark theme, responsive layout, components (cards, tabs, gallery, lightbox). System fonts only — no external requests. |
| `app.js` | Progressive enhancement: language toggle, live release asset links (GitHub Releases API, cached in `sessionStorage`), copy buttons, OS‑aware download tabs with a sliding pill, poster→video facade with GIF fallback, lazy feature GIFs with a pause control, lightbox with arrow‑key navigation, staggered reveal‑on‑scroll, scroll progress, hero counters, cursor parallax/tilt, section rail. The page is fully usable without it. |
| `404.html` | Custom not‑found page (uses absolute `/SonoForge/` paths). |
| `favicon.svg` | Site icon. |
| `media/features/` | Six compact GIF previews and JPEG posters, shipped as static assets. |
| `generate_feature_media.py` | Optional Pillow-based authoring tool; recreates the feature assets from existing project media. |
| `tour.html` | Feature tour (EN/RU): seven GIFs of the real application window, grouped as contours, workspace and measurements. Linked from the header and from the features section of `index.html`. |
| `media/tour/` | The tour GIFs (about 1.3 MB in total), written by `tools/record_tour.py`. |
| `tests/test_site.py` | Dependency-free landing-page / media / citation regression checks. |
| `build.sh` | Assembles the deployable `_site/` directory (see below). |

## Build & preview locally

```bash
bash site/build.sh            # → ./_site   (needs ImageMagick; ffmpeg optional but recommended)
python3 -m http.server --bind 0.0.0.0 -d _site 8000
```

`build.sh` copies the page and prebuilt feature previews, converts `assets/*.gif` demos to MP4 (falls back to copying the GIFs when
ffmpeg is missing — the page detects that at runtime), extracts JPEG posters, makes gallery thumbnails from
`docs/screenshots/`, and pulls the traffic report from the `github-repo-stats` branch into
`areatu/SonoForge/latest-report/` (also linked as `/stats/`).

## Deployment

`.github/workflows/pages.yml` runs `build.sh` and deploys with `actions/deploy-pages` on:

- pushes to `main` that touch `site/`, `assets/`, `docs/screenshots/` or the workflow,
- every successful run of the *Repo traffic stats* workflow (so the embedded report is at most a day old),
- manual dispatch.

Repository setting required once: **Settings → Pages → Source: GitHub Actions**.

## Motion layer

The landing page deliberately stays framework‑free, so interactive motion lives in two places:

* **CSS** (`styles.css`, section *"Motion & polish layer"*) — entrance of the hero, scroll progress bar, drifting
  hero orbs and the sonar sweep, the technology ticker, card spotlights and
  icon reactions, table/step/row staggers, the tab pill, the
  back‑to‑top ring, the section rail and the lightbox.
* **JS** (`app.js`) — only what CSS cannot do: scroll state (`--scroll`, sticky‑header class, back‑to‑top
  visibility), the counter roll‑up, smoothed cursor parallax + media tilt, staggered reveal delays, gallery tilt,
  section rail markup, lightbox prev/next and feature GIF playback (visible cards only, with a pause control).

CSS motion stays on `transform`/`opacity` where possible; nothing is hidden unless `html.js` is present;
automatic motion is disabled under `prefers-reduced-motion: reduce` (verify with DevTools → Rendering → Emulate);
the hero orbs and the sonar sweep are dropped on phones to keep scrolling smooth.

## Feature previews

The first six cards have **480×224 GIFs**, with JPEG posters as the initial / no-JS / reduced-motion
state. The third row intentionally has no previews. GIFs load only while their card is in view; they
return to the poster off-screen, in a hidden tab, when paused, or if a GIF cannot be loaded. The pause
button is keyboard-accessible and follows EN/RU switching. Changing the OS motion preference live is
also supported. All six GIFs together are below 512 KiB; no external image hosts or runtime libraries.

| Preview | Source / animation |
|---|---|
| Cardiac measurements | Cropped `docs/screenshots/lv-linear-measurements.png`, with the original caliper positions / readings revealed in sequence. |
| Doppler & vascular | Actual vascular PW spectrum from frame 930 of `assets/sonoforge_preview.gif`; highlights measured cycles and PSV/EDV. |
| Auto-calibration | The same real spectrum, with baseline, velocity ruler and time ticks highlighted in sequence. |
| AI segmentation | A4C / contour frames 21–32 of `assets/presenter_demo.gif`, with contour detection, tracking and refinement stages. |
| DICOM & PACS | Illustrative transfer diagram with moving packets and an existing cropped echo thumbnail. |
| Reports & norms | Illustrative report / ASE-reference diagram with progressive rows and PDF export. No patient data or invented clinical readings. |

The clinical crops omit patient identifiers and acquisition dates. Preview overlays are illustrative;
they are not new clinical results or performance benchmarks.

To regenerate (optional; the normal build only copies the checked-in files):

```bash
python3 -m pip install 'Pillow>=10'
# Debian/Ubuntu: fonts-dejavu-core supplies the generator's fonts
python3 site/generate_feature_media.py
```

## Checks

```bash
python3 -m unittest discover -s site/tests -v
node --check site/app.js
# Optional full CFF schema validation: pip install cffconvert
cffconvert --validate
```

Before publishing, preview EN/RU at desktop and phone widths, both with JavaScript disabled and with
reduced motion enabled. Check pause/resume, off-screen posters and a missing-GIF fallback. Hero Linux
and Windows links must both stay visible regardless of detected OS or GitHub API availability.

## Citation DOI

The default citation link and BibTeX use the **all-versions DOI**
[`10.5281/zenodo.21463212`](https://doi.org/10.5281/zenodo.21463212), which resolves to the latest Zenodo
release. The general BibTeX links to the repository rather than a version tag and does not pin a version.

`CITATION.cff` keeps the current release version/date but uses the same concept DOI for general citations.
Its identifiers distinguish the concept DOI from
[`10.5281/zenodo.23000446`](https://doi.org/10.5281/zenodo.23000446), which identifies **v0.3.1 only**.
The concept DOI is listed first for converters that prioritize the identifier list over the top-level DOI.

## Editing tips

- Keep EN and RU siblings next to each other; a missing sibling simply shows nothing in that language.
- Release/download data is fetched live; the hard‑coded `v0.3.1` fallbacks in `index.html` only show if the
  GitHub API is unreachable.
- Screenshots used by the gallery are listed in `SHOTS=(…)` in `build.sh`; poster frames in `MEDIA=(…)`.

## Feature tour (`tour.html`)

The tour shows what text cannot: how the tools, menus and workspace behave. Every GIF is a capture of the
**real SonoForge window** (offscreen Qt), not a mockup or a title card. `tools/record_tour.py` boots `MainWindow`,
drives it with the same clicks and menu actions a user makes, grabs the window and writes the GIFs.

| GIF | What it shows |
|---|---|
| `open-study.gif` | Opening a folder: thumbnails, first frame, cine playback. |
| `tabs.gif` | One study per tab; switching between tabs. |
| `lv-contours.gif` | Manual LV contour on one frame: three landmarks against a freehand trace. |
| `tools-customization.gif` | Settings → Tools: reordering sections, showing or hiding tools. |
| `layout.gif` | Layout menu: gallery position, status bar. |
| `linear-caliper.gif` | Linear caliper with a live label after calibration. |
| `calculators.gif` | Calculators tab: expanding and collapsing cards. |

Rules for these captures:

* The image on screen is a **synthetic** cine phantom generated by the script. No patient data, no vendor
  screenshots, no real acquisition. Numbers on the page (for example the LV volumes for the two contour
  methods) are phantom results, not clinical benchmarks, and the page says so.
* The script uses an isolated HOME and XDG directories, so it does not touch a developer's settings or data.
* Identical consecutive frames are merged by the GIF writer, so a static interface shows fewer frames.
  This is expected.

To regenerate (developer tool, not a build dependency; the normal `build.sh` only copies the checked-in GIFs):

```bash
uv sync --extra dev                              # project environment with PySide6
CI=1 python tools/qtstub/mkstub.py               # only on hosts without system OpenGL libraries
export LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen
python tools/record_tour.py                      # all scenarios
python tools/record_tour.py lv-contours          # one scenario
```

`tests/test_site.py` checks that every GIF referenced by `tour.html` exists and is a GIF, that every GIF on disk is
linked, that the total size stays under 2 MiB, that every English text block has a Russian sibling, and that the
local links resolve.
