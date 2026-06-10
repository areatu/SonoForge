# AGENTS.md

Guidance for AI coding agents working in this repository.

## Project overview

This repository is a **planning/spec repo** for **echo-personal-tool** — a personal desktop echocardiography analysis application (PySide6 + PyQtGraph). Sprint 1 (`uv init`, DICOM scanner, PyQtGraph PoC) is not started yet; the desktop app source tree described in `Этап2.md` does not exist in git.

**Currently runnable artifacts:**

| Artifact | Purpose |
|----------|---------|
| `test_py` | Python environment smoke test (numpy, pandas, matplotlib) |
| `scripts/export_echonet_seg_to_onnx.py` | Export EchoNet LV segmentation weights to ONNX (Phase 2 prep) |

## Cursor Cloud specific instructions

### Python environment

- Use **`uv`** for dependency management until `pyproject.toml` / `uv.lock` land in Sprint 1.
- Virtualenv lives at **`.venv/`** (gitignored). Activate with `source .venv/bin/activate` or prefix commands with `.venv/bin/python`.
- System Python is **3.12**; the planned app spec targets `>=3.10,<3.12` — watch for compatibility when Sprint 1 adds `pyproject.toml`.

### Dependency install (manual / first-time)

If `.venv` is missing:

```bash
export PATH="$HOME/.local/bin:$PATH"
uv venv .venv
uv pip install --python .venv/bin/python \
  numpy pandas matplotlib torch torchvision onnx onnxruntime onnxscript
```

The ONNX export script docstring lists `torch torchvision onnx onnxruntime`; current PyTorch also requires **`onnxscript`** for `torch.onnx.export`.

### Running checks

```bash
# Environment smoke test
.venv/bin/python test_py

# ONNX export + verify (downloads ~170 MB weights on first run; needs network)
.venv/bin/python scripts/export_echonet_seg_to_onnx.py --verify --quantize-int8
```

Exported ONNX artifacts and weights are **local-only** (see `models/.gitignore`); do not expect them in a fresh clone.

### Lint / test

No `pyproject.toml`, pytest config, or ruff/black setup exists yet. Planned dev deps are documented in `Этап2.md` §12. Skip formal lint/test until Sprint 1 initializes the project.

### Services

There is **no web server, database, or Docker stack**. The future product is a local desktop GUI (PySide6). Headless CI will need a display server (e.g. `xvfb`) once the app exists.

### Key docs

- `Этап 1.md` — product scope, Phase 1/2 features
- `Этап2.md` — architecture, folder layout, target `pyproject.toml`, sprint plan
- `Этап3.md` — implementation checklist
