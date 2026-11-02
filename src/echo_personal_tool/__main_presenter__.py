"""SonoForge Presenter entry point (lite portable build).

Sets the ``presenter`` profile *before* any application import so that:

- ONNX AI segmentation UI and runtime are disabled (the packaging spec
  additionally excludes ``onnxruntime`` from the bundle);
- the ASE reference viewer / constructor UI is disabled (the spec excludes
  QtWebEngine, PyMuPDF and openpyxl);
- portable storage is enabled: preferences, PACS server profiles, PACS
  passwords and the Orthanc cache are written next to the executable
  (i.e. on the USB stick) instead of onto the host machine.

Everything else (measurement tools, Doppler, M-mode, strain/STE, reports,
PACS connectivity) is identical to the full SonoForge profile.
"""

import multiprocessing
import os
import sys

multiprocessing.freeze_support()

os.environ.setdefault("SONOFORGE_PROFILE", "presenter")
os.environ.setdefault("SONOFORGE_PORTABLE", "1")

# the lite artifact is smoke-tested through the same entry point it ships
# with, so the profile that is verified is the profile that runs.
if "--package-smoke" in sys.argv:
    from echo_personal_tool.application.package_smoke import main as package_smoke_main

    _args = sys.argv[sys.argv.index("--package-smoke") + 1 :]
    raise SystemExit(package_smoke_main(_args))

from echo_personal_tool.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
