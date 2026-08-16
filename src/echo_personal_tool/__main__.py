"""Application entry point."""

import multiprocessing
import sys

print(f"[LA-APP-MAIN] Python: {sys.executable}, argv: {sys.argv}", flush=True)

multiprocessing.freeze_support()

from echo_personal_tool.main import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
