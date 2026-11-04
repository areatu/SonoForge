"""Regression tests for the actual presenter-healing workflow step (stdlib only)."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class PresenterHealerTests(unittest.TestCase):
    def test_ignored_tracked_pins_are_committed_and_second_run_is_a_noop(self):
        workflow = (ROOT / ".github/workflows/drift-healer.yml").read_text(encoding="utf-8")
        step = workflow.split("      - name: Regenerate presenter pins when uv.lock drifted\n", 1)[1]
        script = step.split("        run: |\n", 1)[1].split("\n      # Everything below", 1)[0]
        script = textwrap.dedent(script)

        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary)
            for name in ("tools/release/presenter_pins.py", "build/presenter/pinned-packages.txt", "uv.lock"):
                target = repo / name
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / name, target)
            pins = repo / "build/presenter/pinned-packages.txt"
            # Deliberately stale, while keeping a syntactically valid pin.
            text = pins.read_text(encoding="utf-8")
            self.assertIn("pyside6-essentials==", text)
            import re

            text = re.sub(r"(?m)^pyside6-essentials==[^\n]+", "pyside6-essentials==0.0.0", text)
            pins.write_text(text, encoding="utf-8")
            (repo / ".gitignore").write_text("build/\n", encoding="utf-8")

            def git(*args):
                return subprocess.run(["git", *args], cwd=repo, check=True, text=True, capture_output=True)

            git("init", "-q")
            git("config", "user.name", "test")
            git("config", "user.email", "test@example.invalid")
            git("add", ".gitignore", "uv.lock", "tools")
            git("add", "-f", "build/presenter/pinned-packages.txt")
            git("commit", "-qm", "stale pins")
            output = repo / "output"
            env = {**os.environ, "GITHUB_OUTPUT": str(output)}

            def heal():
                subprocess.run(["bash", "-e", "-c", script], cwd=repo, env=env, check=True, capture_output=True)

            heal()
            self.assertIn("changed=true", output.read_text(encoding="utf-8"))
            self.assertNotIn("pyside6-essentials==0.0.0", pins.read_text(encoding="utf-8"))
            self.assertEqual(git("status", "--porcelain", "--untracked-files=no").stdout, "")
            self.assertEqual(git("rev-list", "--count", "HEAD").stdout.strip(), "2")
            output.write_text("", encoding="utf-8")
            heal()
            self.assertIn("changed=false", output.read_text(encoding="utf-8"))
            self.assertEqual(git("rev-list", "--count", "HEAD").stdout.strip(), "2")


if __name__ == "__main__":
    unittest.main()
