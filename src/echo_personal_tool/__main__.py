"""Application entry point.

``--package-smoke`` is handled before the GUI modules are imported: the packaged
artifact is launched with that flag by the release workflows (QH-5a), and the
smoke must run in the frozen environment without creating a window or requiring
a display.
"""

import multiprocessing
import sys

multiprocessing.freeze_support()

if "--package-smoke" in sys.argv:
    from echo_personal_tool.application.package_smoke import main as package_smoke_main

    _args = sys.argv[sys.argv.index("--package-smoke") + 1 :]
    raise SystemExit(package_smoke_main(_args))

from echo_personal_tool.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
