"""Quick launcher for the Reference Constructor dialog."""

import sys
from pathlib import Path

# Add src to path (script lives in scripts/, sources are in ../src)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from PySide6.QtWidgets import QApplication
from echo_personal_tool.constructor.constructor_dialog import ConstructorDialog


def main() -> int:
    app = QApplication(sys.argv)
    dialog = ConstructorDialog()
    dialog.showMaximized()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
