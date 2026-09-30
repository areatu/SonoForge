# Project website (GitHub Pages)

Source of <https://areatu.github.io/SonoForge/> — a static landing page for SonoForge,
bilingual (EN/RU toggle), no framework, no build tooling beyond a shell script.

| File | Purpose |
|---|---|
| `index.html` | The page. Every piece of copy exists twice, as `lang="en"` / `lang="ru"` siblings; CSS shows only the active language. |
| `styles.css` | Dark theme, responsive layout, components (cards, tabs, gallery, lightbox). System fonts only — no external requests. |
| `app.js` | Progressive enhancement: language toggle, OS‑aware download buttons (GitHub Releases API, cached in `sessionStorage`), copy buttons, tabs, poster→video facade with GIF fallback, lightbox, reveal‑on‑scroll. The page is fully usable without it. |
| `404.html` | Custom not‑found page (uses absolute `/SonoForge/` paths). |
| `favicon.svg` | Site icon. |
| `build.sh` | Assembles the deployable `_site/` directory (see below). |

## Build & preview locally

```bash
bash site/build.sh            # → ./_site   (needs ImageMagick; ffmpeg optional but recommended)
python3 -m http.server -d _site 8000
```

`build.sh` copies the page, converts `assets/*.gif` demos to MP4 (falls back to copying the GIFs when
ffmpeg is missing — the page detects that at runtime), extracts JPEG posters, makes gallery thumbnails from
`docs/screenshots/`, and pulls the traffic report from the `github-repo-stats` branch into
`areatu/SonoForge/latest-report/` (also linked as `/stats/`).

## Deployment

`.github/workflows/pages.yml` runs `build.sh` and deploys with `actions/deploy-pages` on:

- pushes to `main` that touch `site/`, `assets/`, `docs/screenshots/` or the workflow,
- every successful run of the *Repo traffic stats* workflow (so the embedded report is at most a day old),
- manual dispatch.

Repository setting required once: **Settings → Pages → Source: GitHub Actions**.

## Editing tips

- Keep EN and RU siblings next to each other; a missing sibling simply shows nothing in that language.
- Release/download data is fetched live; the hard‑coded `v0.3.1` fallbacks in `index.html` only show if the
  GitHub API is unreachable.
- Screenshots used by the gallery are listed in `SHOTS=(…)` in `build.sh`; poster frames in `MEDIA=(…)`.