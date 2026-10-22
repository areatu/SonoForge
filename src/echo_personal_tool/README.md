# SonoForge Source

> [Русская версия](README_RU.md)

The SonoForge source code — a desktop tool for echocardiography.

## Architecture (Clean Architecture)

```
src/echo_personal_tool/
├── domain/           # Business logic (no Qt dependencies)
│   ├── models/       # Data classes: Contour, Doppler, Speckle, MMode
│   ├── calculations/ # Calculations: Simpson, Bernoulli, Teichholz, BSA
│   ├── services/     # Services: segmentation, tracking, reference values
│   └── ports.py      # Interfaces (abstractions)
├── infrastructure/   # External integrations
│   ├── dicom_*.py    # DICOM read/write
│   ├── orthanc_*.py  # Orthanc DICOMweb client
│   ├── dimse_*.py    # DIMSE client
│   ├── onnx_engine.py # ONNX inference
│   └── ...
├── application/      # Orchestration and workflow
│   ├── app_controller.py # Main controller
│   ├── workers/      # Background tasks (11)
│   └── services/     # Application services
├── presentation/     # GUI (PySide6)
│   ├── main_window.py
│   ├── viewer_widget.py
│   ├── doppler_widget.py
│   └── ...
├── constructor/      # Reference constructor
├── resources/        # Fonts, icons, ASE reference
└── ui/               # STE windows and plots
```

## Running

```bash
python -m echo_personal_tool
```
