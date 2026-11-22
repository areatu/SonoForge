"""Build an interactive contact sheet for labelling clip views (issue #639).

Extracts two representative frames from every DICOM listed in ``gold.json``,
writes JPEG thumbnails, and generates ``index.html``: a grid of clips where
each view can be assigned with a click or a number key. Labels are kept in
``localStorage`` and the page exports the complete updated ``gold.json``.

Usage::

    .venv/bin/python scripts/make_view_contact_sheet.py \\
        --dicom-dir /home/areatu/ECHO2026_src/gold
    # then open models/view_contact_sheet/index.html in a browser

``--dicom-dir`` re-scans the folder; existing views from ``--gold`` are kept.
Re-running skips existing thumbnails unless ``--force`` is passed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pydicom
from PIL import Image, ImageDraw, ImageOps
from pydicom.pixels import pixel_array

# Candidate positions inside a clip; the two with the most content are kept.
_FRAME_FRACTIONS = (0.15, 0.30, 0.45, 0.60, 0.75)

_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="utf-8">
<title>SonoForge — разметка видов</title>
<style>
  :root { color-scheme: dark; }
  * { box-sizing: border-box; }
  body { margin: 0; font: 14px/1.4 system-ui, sans-serif; background: #11151a; color: #e6edf3; }
  header { position: sticky; top: 0; z-index: 10; display: flex; flex-wrap: wrap; gap: 12px;
           align-items: center; padding: 10px 16px; background: #1a2029; border-bottom: 1px solid #2d3641; }
  header h1 { font-size: 15px; margin: 0 12px 0 0; font-weight: 600; }
  .progress { min-width: 180px; }
  .bar { height: 6px; background: #2d3641; border-radius: 3px; overflow: hidden; }
  .bar > i { display: block; height: 100%; width: 0; background: #3fb950; transition: width .2s; }
  button, label.btn { font: inherit; color: #e6edf3; background: #26303b; border: 1px solid #3a4653;
           border-radius: 6px; padding: 5px 10px; cursor: pointer; }
  button:hover, label.btn:hover { background: #303c49; }
  button.primary { background: #238636; border-color: #2ea043; }
  button.primary:hover { background: #2ea043; }
  input[type=file] { display: none; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr));
          gap: 12px; padding: 16px; }
  .card { background: #1a2029; border: 2px solid #2d3641; border-radius: 10px; padding: 8px;
          display: flex; flex-direction: column; gap: 8px; }
  .card.active { border-color: #58a6ff; }
  .card.labeled { border-color: #2ea043; }
  .card.hidden { display: none; }
  .thumbs { display: grid; grid-template-columns: 1fr 1fr; gap: 6px; background: #000; border-radius: 6px;
            overflow: hidden; aspect-ratio: 4 / 3; }
  .thumbs img { width: 100%; height: 100%; object-fit: contain; }
  .name { display: flex; justify-content: space-between; gap: 8px; font-size: 13px; }
  .name b { font-weight: 600; }
  .name span { color: #8b949e; font-size: 12px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .views { display: flex; flex-wrap: wrap; gap: 4px; }
  .views button { padding: 3px 8px; font-size: 12px; }
  .views button.on { background: #1f6feb; border-color: #58a6ff; }
  .views button.clear { color: #8b949e; }
  .err { color: #f85149; font-size: 12px; }
  .hint { color: #8b949e; font-size: 12px; }
  kbd { background: #2d3641; border-radius: 3px; padding: 0 4px; }
</style>
</head>
<body>
<header>
  <h1>Разметка видов</h1>
  <div class="progress">
    <div id="count">0 / 0</div>
    <div class="bar"><i id="bar"></i></div>
  </div>
  <button id="only-unlabeled">Показать только неразмеченные</button>
  <button class="primary" id="export">Скачать gold.json</button>
  <label class="btn">Загрузить gold.json<input type="file" id="import" accept="application/json"></label>
  <button id="reset">Сбросить метки</button>
  <span class="hint">Клик по карточке, затем <kbd>1</kbd>–<kbd>7</kbd>; <kbd>0</kbd> — очистить</span>
</header>
<div class="grid" id="grid"></div>
<script id="sheet-data" type="application/json">__DATA__</script>
<script>
const data = JSON.parse(document.getElementById('sheet-data').textContent);
const gold = data.gold;
const classes = gold.class_names;
const STORE = 'sonoforge_view_labels_v1';
let store = null;
try { store = window.localStorage; } catch (e) { store = null; }
const labels = Object.assign({}, JSON.parse((store && store.getItem(STORE)) || '{}'));
let active = -1;

for (const r of gold.records) if (r.view) labels[r.instance_path] = r.view;
function save() { try { if (store) store.setItem(STORE, JSON.stringify(labels)); } catch (e) {} }
function labelOf(r) { return labels[r.instance_path] || ''; }
function refresh() {
  const total = gold.records.length;
  const done = gold.records.filter(r => labelOf(r)).length;
  document.getElementById('count').textContent = done + ' / ' + total + ' размечено';
  document.getElementById('bar').style.width = (total ? done * 100 / total : 0) + '%';
  document.getElementById('only-unlabeled').textContent =
    onlyUnlabeled ? 'Показать все' : 'Показать только неразмеченные';
}
let onlyUnlabeled = false;
function render() {
  const grid = document.getElementById('grid');
  grid.innerHTML = '';
  gold.records.forEach((r, i) => {
    const card = document.createElement('div');
    card.className = 'card' + (labelOf(r) ? ' labeled' : '') + (i === active ? ' active' : '');
    const thumbs = (data.thumbs[r.instance_path] || []).map(
      src => `<img loading="lazy" src="${src}" alt="">`).join('');
    card.innerHTML =
      `<div class="thumbs">${thumbs || '<div></div>'}</div>` +
      `<div class="name"><b>${r.file}</b><span>${r.sop_instance_uid.slice(-12)}</span></div>` +
      `<div class="views"></div>` +
      (data.errors[r.instance_path] ? `<div class="err">${data.errors[r.instance_path]}</div>` : '');
    const views = card.querySelector('.views');
    classes.forEach((c, ci) => {
      const b = document.createElement('button');
      b.textContent = c;
      b.className = labelOf(r) === c ? 'on' : '';
      b.onclick = e => { e.stopPropagation(); setLabel(i, c); };
      views.appendChild(b);
    });
    const clr = document.createElement('button');
    clr.textContent = '—';
    clr.className = 'clear';
    clr.title = 'Без метки';
    clr.onclick = e => { e.stopPropagation(); setLabel(i, ''); };
    views.appendChild(clr);
    card.onclick = () => select(i);
    if (onlyUnlabeled && labelOf(r)) card.classList.add('hidden');
    grid.appendChild(card);
  });
  refresh();
}
function select(i) { active = i; render(); }
function setLabel(i, value) {
  const r = gold.records[i];
  if (value) labels[r.instance_path] = value; else delete labels[r.instance_path];
  save();
  active = i;
  render();
  // Advance to the next unlabeled card for keyboard-driven labelling.
  for (let j = i + 1; j < gold.records.length; j++) {
    if (!labelOf(gold.records[j])) { active = j; render(); return; }
  }
  active = -1; render();
}
document.addEventListener('keydown', e => {
  if (e.target.tagName === 'INPUT') return;
  if (e.key >= '1' && e.key <= '7') {
    const c = classes[Number(e.key) - 1];
    if (c && active >= 0) { e.preventDefault(); setLabel(active, c); }
  } else if (e.key === '0' || e.key === 'Backspace') {
    if (active >= 0) { e.preventDefault(); setLabel(active, ''); }
  } else if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
    e.preventDefault();
    if (!gold.records.length) return;
    active = active < 0 ? 0 : (active + (e.key === 'ArrowDown' ? 1 : -1) + gold.records.length) % gold.records.length;
    render();
    const card = document.querySelectorAll('.card')[active];
    if (card) card.scrollIntoView({ block: 'center', behavior: 'smooth' });
  }
});
document.getElementById('only-unlabeled').onclick = () => { onlyUnlabeled = !onlyUnlabeled; render(); };
document.getElementById('reset').onclick = () => {
  if (!confirm('Удалить все метки из этого браузера?')) return;
  for (const k of Object.keys(labels)) delete labels[k];
  save(); render();
};
document.getElementById('export').onclick = () => {
  const out = JSON.parse(JSON.stringify(gold));
  for (const r of out.records) r.view = labels[r.instance_path] || '';
  const blob = new Blob([JSON.stringify(out, null, 2) + '\\n'], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = 'gold.json';
  a.click();
  URL.revokeObjectURL(a.href);
};
document.getElementById('import').onchange = async e => {
  const file = e.target.files[0];
  if (!file) return;
  const data = JSON.parse(await file.text());
  for (const r of data.records || []) {
    if (r.instance_path && r.view) labels[r.instance_path] = r.view;
  }
  save(); render();
};
render();
</script>
</body>
</html>
"""


def _to_image(frame: np.ndarray) -> Image.Image:
    if frame.ndim == 3 and frame.shape[-1] in (3, 4):
        return Image.fromarray(np.ascontiguousarray(frame[..., :3])).convert("RGB")
    array = frame.astype(np.float32)
    low, high = np.percentile(array, (1, 99))
    if high <= low:
        high = low + 1.0
    scaled = np.clip((array - low) * (255.0 / (high - low)), 0, 255).astype(np.uint8)
    return Image.fromarray(scaled).convert("RGB")


def _thumb(image: Image.Image, width: int, height: int) -> Image.Image:
    canvas = Image.new("RGB", (width, height), (12, 12, 12))
    fitted = ImageOps.contain(image, (width, height), Image.Resampling.LANCZOS)
    canvas.paste(fitted, ((width - fitted.width) // 2, (height - fitted.height) // 2))
    return canvas


def _placeholder(width: int, height: int, text: str) -> Image.Image:
    image = Image.new("RGB", (width, height), (40, 20, 20))
    ImageDraw.Draw(image).text((8, height // 2 - 6), text[:28], fill=(240, 160, 160))
    return image


def extract_thumbs(path: Path, out_dir: Path, stem: str, *, width: int, height: int, force: bool) -> list[str]:
    targets = [out_dir / f"{stem}_{i}.jpg" for i in (1, 2)]
    if not force and all(t.is_file() for t in targets):
        return [f"thumbs/{t.name}" for t in targets]

    ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
    nframes = max(1, int(getattr(ds, "NumberOfFrames", 1) or 1))
    indices = sorted({min(nframes - 1, round(nframes * f)) for f in _FRAME_FRACTIONS})
    scored: list[tuple[float, int, Image.Image]] = []
    for index in indices:
        try:
            frame = pixel_array(path, index=index) if nframes > 1 else pixel_array(path)
        except Exception:  # noqa: BLE001 - a single bad frame must not abort the sheet
            continue
        image = _to_image(frame)
        scored.append((float(np.asarray(image.convert("L")).std()), index, image))
    if not scored:
        raise ValueError("no decodable frames")
    chosen = sorted(sorted(scored, key=lambda item: item[0], reverse=True)[:2], key=lambda item: item[1])
    while len(chosen) < 2:
        chosen.append(chosen[-1])

    out_dir.mkdir(parents=True, exist_ok=True)
    for target, (_, _, image) in zip(targets, chosen):
        _thumb(image, width, height).save(target, "JPEG", quality=82)
    return [f"thumbs/{t.name}" for t in targets]


def records_from_dicom_dir(dicom_dir: Path, existing: dict) -> dict:
    """Build sheet records for every DICOM in ``dicom_dir``, keeping old views.

    Existing labels are matched first by ``instance_path``, then by
    ``sop_instance_uid``, so a re-scan never loses manual work.
    """
    previous = existing.get("records", [])
    by_path = {str(r.get("instance_path", "")): r for r in previous}
    by_uid: dict[str, dict] = {}
    for record in previous:
        uid = str(record.get("sop_instance_uid", ""))
        if uid:
            by_uid.setdefault(uid, record)

    paths = sorted({p for ext in ("*.dcm", "*.dicom") for p in dicom_dir.rglob(ext)})
    records: list[dict] = []
    used_stems: set[str] = set()
    for path in paths:
        uid = ""
        try:
            ds = pydicom.dcmread(path, stop_before_pixels=True, force=True)
            uid = str(ds.get("SOPInstanceUID", "") or "")
        except Exception as exc:  # noqa: BLE001 - keep the clip in the sheet anyway
            print(f"  ! header {path.name}: {exc}", file=sys.stderr)  # noqa: T201
        prior = by_path.get(str(path)) or (by_uid.get(uid) if uid else None) or {}
        stem = path.stem
        if stem in used_stems:
            index = 2
            while f"{stem}_{index}" in used_stems:
                index += 1
            stem = f"{stem}_{index}"
        used_stems.add(stem)
        records.append(
            {
                "sop_instance_uid": uid,
                "instance_path": str(path),
                "file": path.name,
                "view": str(prior.get("view", "")),
            }
        )
    return {**existing, "records": records}


def build_sheet(gold: dict, out_dir: Path, *, width: int, height: int, force: bool) -> dict:
    thumbs: dict[str, list[str]] = {}
    errors: dict[str, str] = {}
    (out_dir / "thumbs").mkdir(parents=True, exist_ok=True)
    for record in gold.get("records", []):
        path_text = str(record.get("instance_path", ""))
        path = Path(path_text)
        stem = str(record.get("stem") or path.stem or record.get("file") or "clip")
        if not path.is_file():
            errors[path_text] = "файл не найден"
            continue
        try:
            thumbs[path_text] = extract_thumbs(path, out_dir / "thumbs", stem, width=width, height=height, force=force)
        except Exception as exc:  # noqa: BLE001 - report per clip and continue
            errors[path_text] = f"{type(exc).__name__}: {exc}"
            placeholder = _placeholder(width * 2 + 6, height, "нет кадра")
            placeholder.save(out_dir / "thumbs" / f"{stem}_1.jpg", "JPEG", quality=82)
            thumbs[path_text] = [f"thumbs/{stem}_1.jpg"]
    return {"thumbs": thumbs, "errors": errors}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--gold", type=Path, default=Path("models/gold.json"), help="Consolidated gold JSON")
    parser.add_argument(
        "--dicom-dir",
        type=Path,
        default=None,
        help="Scan this folder for DICOMs instead of using only records from --gold",
    )
    parser.add_argument("--out-dir", type=Path, default=Path("models/view_contact_sheet"))
    parser.add_argument("--width", type=int, default=300, help="Thumbnail width (default 300)")
    parser.add_argument("--height", type=int, default=225, help="Thumbnail height (default 225)")
    parser.add_argument("--force", action="store_true", help="Regenerate existing thumbnails")
    parser.add_argument("--limit", type=int, default=0, help="Only the first N clips (debug)")
    args = parser.parse_args(argv)

    gold = json.loads(args.gold.read_text(encoding="utf-8"))
    if args.dicom_dir is not None:
        if not args.dicom_dir.is_dir():
            print(f"error: DICOM directory not found: {args.dicom_dir}", file=sys.stderr)  # noqa: T201
            return 2
        gold = records_from_dicom_dir(args.dicom_dir, gold)
    if args.limit:
        gold["records"] = gold["records"][: args.limit]
    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    assets = build_sheet(gold, out_dir, width=args.width, height=args.height, force=args.force)
    payload = json.dumps({"gold": gold, **assets}, ensure_ascii=False).replace("</", "<\\/")
    (out_dir / "index.html").write_text(_HTML.replace("__DATA__", payload), encoding="utf-8")

    done = len(assets["thumbs"])
    print(f"clips: {len(gold['records'])}, thumbnails: {done}, errors: {len(assets['errors'])}")  # noqa: T201
    for path_text, message in assets["errors"].items():
        print(f"  ! {Path(path_text).name}: {message}", file=sys.stderr)  # noqa: T201
    print(f"open: {(out_dir / 'index.html').resolve()}")  # noqa: T201
    return 0 if done else 1


if __name__ == "__main__":
    raise SystemExit(main())
