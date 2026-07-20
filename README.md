<div align="center">

# SonoForge

### Desktop Echocardiography Analysis Tool

[![Python 3.10+](https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/downloads/)
[![License GPL-3.0](https://img.shields.io/badge/License-GPL%203.0-green?style=for-the-badge)](LICENSE)
[![CI](https://img.shields.io/github/actions/workflow/status/areatu/SonoForge/ci.yml?style=for-the-badge&label=CI)](https://github.com/areatu/SonoForge/actions)
[![Release](https://img.shields.io/github/v/release/areatu/SonoForge?style=for-the-badge&color=blue)](https://github.com/areatu/SonoForge/releases)
[![DOI](https://img.shields.io/badge/DOI-10.5281/zenodo.XXXXXXX-blue?style=for-the-badge)](https://zenodo.org/)

---

**DICOM** · **MP4** · **JPEG/PNG** — AI-powered cardiac measurements, offline, ASE-compliant.

[Installation](#installation) · [Features](#features) · [Quick Start](#quick-start) · [Documentation](#documentation) · [Contributing](#contributing)

</div>

---

## 📦 Installation

<details open>
<summary><strong>Linux (.deb)</strong></summary>

```bash
# Download
wget https://github.com/areatu/SonoForge/releases/latest/download/sonoforge_*.deb

# Install
sudo dpkg -i sonoforge_*.deb

# Run
sonoforge
```

</details>

<details>
<summary><strong>Windows (.zip)</strong></summary>

1. Download `SonoForge-*.zip` from [Releases](https://github.com/areatu/SonoForge/releases)
2. Extract to any folder
3. Run `SonoForge\bin\SonoForge.bat`

> **Requires:** Python 3.10+ ([download](https://www.python.org/downloads/), check "Add to PATH")

</details>

<details>
<summary><strong>From Source (Development)</strong></summary>

```bash
git clone https://github.com/areatu/SonoForge.git
cd SonoForge

# With uv (recommended)
uv sync --extra dev
uv run sonoforge

# Or pip
pip install -e ".[dev]"
python -m echo_personal_tool
```

</details>

> **Note:** First run creates a virtual environment, installs dependencies (~940 MB), and optionally downloads AI models (~300 MB).

---

## 🚀 Features

<table>
<tr>
<td width="50%">

### 📊 Measurements
- **Linear:** LVEDD, IVSd, TAPSE, RVOT...
- **Volumes:** Simpson (open-arc), Planimeter
- **Doppler:** Peaks, VTI, Intervals
- **M-Mode:** Scan line, measurements, smoothing
- **STE:** GLS, AHA segments, strain curves

</td>
<td width="50%">

### 🤖 AI Segmentation
- **ONNX LV Auto** (`I` key)
- **Temporal Fusion** (N±2 neighbors)
- **LA Segmentation** (A4C ES)
- **Mitral Annulus** landmark detection
- **Active Contour Refine** (`R` key)

</td>
</tr>
<tr>
<td>

### 🏥 DICOM Integration
- **DICOMweb:** QIDO-RS, WADO-RS, STOW-RS
- **DIMSE:** C-FIND, C-GET, C-MOVE, C-STORE
- **TLS** support
- **Orthanc** integration

</td>
<td>

### 📈 Reports
- Study overlay with all measurements
- BSA indices (LVMI, LAVi, RAVi)
- ASE reference norms
- PDF export

</td>
</tr>
</table>

> **See all features:** [Features Overview](#features-overview)

---

## 🏃 Quick Start

1. **Open Folder** → DICOM/MP4/JPEG directory, or **Load from Server** → Orthanc
2. **Gallery** → Select series → Frame opens in viewer
3. **Measures** → Linear, Simpson, Doppler, M-Mode, STE, RV FAC...
4. **Results** → Summary and PDF export

### Keyboard Shortcuts

| Key | Action | Key | Action |
|-----|--------|-----|--------|
| `Space` | Play/Pause | `I` | LV Auto Segment |
| `L` | Linear caliper | `R` | Refine contour |
| `K` | Manual calibration | `C` | Manual contour |
| `T` | Doppler interval | `V` | VTI trace |
| `Tab` | Next caliper label | `Esc` | Cancel tool |

---

## 📚 Documentation

| Document | Description |
|----------|-------------|
| [SECURITY.md](SECURITY.md) | PHI handling, data security, model integrity |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Contribution guidelines |
| [ROADMAP.md](ROADMAP.md) | Feature status |
| [docs/superpowers/specs/](docs/superpowers/specs/) | Technical specs |
| [docs/superpowers/plans/](docs/superpowers/plans/) | Implementation plans |

---

## 🏗️ Architecture

```
src/echo_personal_tool/
├── domain/           # Business logic (no Qt dependency)
│   ├── models/       # Contour, Doppler, Speckle, MMode
│   ├── calculations/ # Simpson, Bernoulli, Teichholz, BSA
│   └── services/     # Segmentation, tracking, references
├── infrastructure/   # DICOM, Orthanc, ONNX, DIMSE
├── application/      # AppController, workers (11)
├── presentation/     # MainWindow, Viewer, M-Mode, Doppler
└── resources/        # Fonts, icons, ASE reference
```

---

## 🛡️ Security

> **Your data stays local.** SonoForge processes all DICOM data in memory — no PHI is written to disk, no cloud uploads, no telemetry.

- ✅ DICOM file validation before parsing
- ✅ SHA256 model integrity checks
- ✅ Network timeouts for DICOMweb/DIMSE
- ✅ PHI sanitization in logs

See [SECURITY.md](SECURITY.md) for details.

---

## 🤝 Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for guidelines.

```bash
# Run tests
python -m pytest tests/

# Lint
ruff check src tests

# Format
ruff format src tests
```

---

## 📜 Citation

If you use SonoForge in your research, please cite:

```bibtex
@software{kuvilkin2026sonoforge,
  author       = {Kuvilkin, Vitaliy},
  title        = {SonoForge: Desktop Echocardiography Analysis Tool},
  year         = {2026},
  publisher    = {GitHub},
  url          = {https://github.com/areatu/SonoForge},
  license      = {GPL-3.0}
}
```

---

## 📄 License

[GPL-3.0](LICENSE) — Free software, open source.

---

<div align="center">

**Built with ❤️ for cardiology**

[Report Bug](https://github.com/areatu/SonoForge/issues) · [Request Feature](https://github.com/areatu/SonoForge/issues) · [Discussions](https://github.com/areatu/SonoForge/discussions)

</div>
