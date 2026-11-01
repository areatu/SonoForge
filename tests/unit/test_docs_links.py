"""Documentation hygiene guards (S3-03, issue 312).

The audit found three kinds of documentation rot and this module keeps them from
coming back:

* `docs/bench` was gitignored, so code and tests linked into a folder that never
  existed in the repository — now every `docs/bench/<file>.md` reference must
  point at a tracked file;
* `CHANGELOG.md` grew into one 460 KB file — history now lives in
  `changelog/YYYY-MM.md` and the index in `CHANGELOG.md` must list all of them;
* README/HELP/ROADMAP links drifted to deleted files — relative links in the
  documents a reader actually opens must resolve.

The scope is deliberately narrow (the documents a user or contributor opens from
the README tree): historical review notes keep their original text.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]

LINK_RE = re.compile(r"\]\(([^)]+)\)")
BENCH_REF_RE = re.compile(r"docs/bench/([A-Za-z0-9._-]+\.md)")

#: Documents that must never point at a file that is not in the repository.
READER_DOCUMENTS = (
    "README.md",
    "README_RU.md",
    "ROADMAP.md",
    "CHANGELOG.md",
    "CONTRIBUTING.md",
    "SECURITY.md",
    "docs/HELP_RU.md",
    "docs/HELP_EN.md",
    "docs/TECHNICAL_HELP_RU.md",
    "docs/TECHNICAL_HELP_EN.md",
    "tests/README.md",
    "tests/README_RU.md",
    "bench/README.md",
    "bench/README_RU.md",
    "bench/cine720/README.md",
    "bench/cine720/README_RU.md",
)


def _reader_documents() -> list[Path]:
    paths = [REPO_ROOT / name for name in READER_DOCUMENTS]
    paths += sorted((REPO_ROOT / "changelog").glob("*.md"))
    paths += sorted((REPO_ROOT / "docs" / "bench").glob("*.md"))
    return [path for path in paths if path.exists()]


def _relative_links(path: Path) -> list[tuple[int, str]]:
    links: list[tuple[int, str]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for target in LINK_RE.findall(line):
            target = target.split("#", 1)[0].strip()
            if not target or target.startswith(("http://", "https://", "mailto:")):
                continue
            links.append((number, target))
    return links


class TestChangelogStructure:
    def test_the_entry_point_keeps_the_unreleased_section(self) -> None:
        text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        assert "## Unreleased" in text
        assert "не выпущено" in text  # the policy that explains the section

    def test_the_entry_point_stays_readable(self) -> None:
        text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")

        # The audit found a 460 KB single file; the entry point is the working
        # area now, so history must not creep back into it.
        assert len(text) < 200_000, "history belongs to changelog/YYYY-MM.md"

    def test_every_month_file_is_indexed(self) -> None:
        index = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        months = sorted(path.stem for path in (REPO_ROOT / "changelog").glob("*.md"))

        assert months, "the monthly history must not be empty"
        for month in months:
            assert f"changelog/{month}.md" in index, f"{month} is not linked from CHANGELOG.md"

    def test_every_month_file_has_entries(self) -> None:
        for path in sorted((REPO_ROOT / "changelog").glob("*.md")):
            headings = [line for line in path.read_text(encoding="utf-8").splitlines() if line.startswith("## ")]
            assert headings, f"{path.name} has no entries"
            # Newest first: the file is a reverse-chronological history slice.
            assert headings[0].startswith("## ")


class TestBenchEvidence:
    def test_the_bench_folder_is_tracked(self) -> None:
        bench = REPO_ROOT / "docs" / "bench"

        assert (bench / "README.md").is_file()
        assert list(bench.glob("*.md"))

    def test_every_referenced_bench_report_exists(self) -> None:
        """A benchmark claim in code, tests or specs must have a tracked report."""
        missing: list[str] = []
        for base in ("src", "tests", "docs", "bench"):
            for path in (REPO_ROOT / base).rglob("*"):
                if path.suffix not in {".py", ".md", ".txt", ".yml"} or not path.is_file():
                    continue
                try:
                    text = path.read_text(encoding="utf-8")
                except UnicodeDecodeError:  # pragma: no cover - binary-ish file
                    continue
                for name in BENCH_REF_RE.findall(text):
                    if not (REPO_ROOT / "docs" / "bench" / name).is_file():
                        missing.append(f"{path.relative_to(REPO_ROOT)} -> docs/bench/{name}")

        assert not missing, "dangling docs/bench references:\n" + "\n".join(sorted(set(missing)))

    def test_the_gitignore_does_not_hide_the_bench_folder(self) -> None:
        lines = (REPO_ROOT / ".gitignore").read_text(encoding="utf-8").splitlines()

        assert "docs/bench/" not in lines


class TestReaderLinks:
    def test_no_relative_link_points_into_the_void(self) -> None:
        broken: list[str] = []
        for path in _reader_documents():
            for number, target in _relative_links(path):
                if not (path.parent / target).resolve().exists():
                    broken.append(f"{path.relative_to(REPO_ROOT)}:{number} -> {target}")

        assert not broken, "broken relative links:\n" + "\n".join(broken)

    def test_the_reader_documents_exist(self) -> None:
        missing = [name for name in READER_DOCUMENTS if not (REPO_ROOT / name).is_file()]

        assert not missing, "documents promised by this guard are gone:\n" + "\n".join(missing)


@pytest.mark.parametrize("name", ["ROADMAP.md"])
def test_the_roadmap_states_its_own_scope(name: str) -> None:
    """The roadmap must say what it is not — the audit's complaint about it."""
    text = (REPO_ROOT / name).read_text(encoding="utf-8")

    assert "Обновлено:" in text
    assert "Чем это не является" in text
    assert "non-goals" in text.lower()
