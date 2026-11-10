#!/usr/bin/env bash
# Assemble the GitHub Pages site into a single static directory.
#
#   bash site/build.sh [OUT_DIR]        # default: ./_site
#
# Static site, Presenter illustration and current screenshots from docs/images/release-0.4/.
# ImageMagick is optional: without it the full PNGs are used as thumbnails.
#
# Used by .github/workflows/pages.yml; safe to run locally (python3 -m http.server -d _site).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SITE="$ROOT/site"
OUT="${1:-$ROOT/_site}"
case "$OUT" in /*) ;; *) OUT="$PWD/$OUT" ;; esac

have() { command -v "$1" >/dev/null 2>&1; }
log()  { printf '\033[1;36m▸\033[0m %s\n' "$*"; }

rm -rf "$OUT"
mkdir -p "$OUT/media" "$OUT/screenshots/thumbs"

# ---------------------------------------------------------------- static files
log "static files"
cp "$SITE/index.html" "$SITE/tour.html" "$SITE/404.html" "$SITE/styles.css" "$SITE/app.js" "$SITE/favicon.svg" "$OUT/"
: > "$OUT/.nojekyll"

# Current, user-supplied screenshots; no external demo recordings required.
cp "$ROOT/assets/presenter.png" "$OUT/media/presenter.png"
mkdir -p "$OUT/media/features"
cp "$SITE"/media/features/*.gif "$SITE"/media/features/*-poster.jpg "$OUT/media/features/"
SHOTS=(lv-simpson kidney kidney-report echo-report doppler lv-linear calculators reference server-loader)
for s in "${SHOTS[@]}"; do
  src="$ROOT/docs/images/release-0.4/$s.png"
  cp "$src" "$OUT/screenshots/$s.png"
  if have convert; then
    convert "$src" -resize 1200x -strip -interlace Plane -quality 80 "$OUT/screenshots/thumbs/$s.jpg"
  else
    # Keep file extension and format consistent without ImageMagick.
    cp "$src" "$OUT/screenshots/thumbs/$s.png"
    sed -i "s|screenshots/thumbs/$s.jpg|screenshots/thumbs/$s.png|g" "$OUT/index.html"
  fi
done

# ---------------------------------------------------------------- summary
log "done → $OUT"
if have du; then du -sh "$OUT" | sed 's/^/  total: /'; fi
find "$OUT" -type f | sort | sed "s|^$OUT/|  |"