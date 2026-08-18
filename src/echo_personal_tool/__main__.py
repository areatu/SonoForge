"""Application entry point."""

import multiprocessing

multiprocessing.freeze_support()

from echo_personal_tool.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
