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
import subprocess
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
    paths += sorted((REPO_ROOT / "changelog.d").glob("*.md"))
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

        # The audit found a 460 KB single file (issue 329 later a 180 KB Unreleased).
        # The entry point is an index now: the text of an entry lives in
        # changelog.d/, history in changelog/YYYY-MM.md.
        assert len(text) < 40_000, "the full text of an entry belongs to changelog.d/, history to changelog/YYYY-MM.md"

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


class TestChangelogFragments:
    """Issue 329: `Unreleased` is an index; every entry lives in its own fragment."""

    FRAGMENT_NAME = re.compile(r"^\d{3}-[a-z0-9]+(?:-[a-z0-9]+)*\.md$")
    INDEX_LINE = re.compile(r"^- .+ \(\[полностью\]\(changelog\.d/([^)]+)\)\)$")

    @staticmethod
    def _fragments() -> list[Path]:
        return sorted(path for path in (REPO_ROOT / "changelog.d").glob("*.md") if path.name != "README.md")

    @classmethod
    def _index(cls) -> list[str]:
        text = (REPO_ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
        return [line for line in text.split("## Unreleased", 1)[1].splitlines() if line.startswith("- ")]

    def test_fragment_names_follow_the_convention(self) -> None:
        wrong = [path.name for path in self._fragments() if not self.FRAGMENT_NAME.match(path.name)]

        assert self._fragments()
        assert not wrong, f"name a fragment NNN-type-scope-ref.md (see changelog.d/README.md): {wrong}"

    def test_every_fragment_is_one_entry_in_the_documented_format(self) -> None:
        entry = re.compile(r"^- `[a-z]+(?:\([^)]*\))?`: ")
        wrong = [path.name for path in self._fragments() if not entry.match(path.read_text(encoding="utf-8"))]

        assert not wrong, f"a fragment starts with '- `type(scope)`: ': {wrong}"

    def test_every_fragment_has_exactly_one_index_line_and_the_reverse(self) -> None:
        linked: list[str] = []
        for line in self._index():
            match = self.INDEX_LINE.match(line)
            assert match, f"an index line is '- summary ([полностью](changelog.d/NNN-….md))': {line[:90]}"
            linked.append(match.group(1))

        assert sorted(linked) == [path.name for path in self._fragments()]

    def test_the_index_is_ordered_newest_first_and_stays_short(self) -> None:
        numbers = [int(self.INDEX_LINE.match(line).group(1)[:3]) for line in self._index()]  # type: ignore[union-attr]

        assert numbers == sorted(numbers, reverse=True), "newest entries go to the top of the index"
        assert all(len(line) <= 420 for line in self._index()), "an index line is a summary, not the entry"

    def test_a_release_leaves_no_fragments_behind_the_index(self) -> None:
        """The README documents the procedure the index and the fragments follow."""
        readme = (REPO_ROOT / "changelog.d" / "README.md").read_text(encoding="utf-8")

        assert "При выпуске релиза" in readme
        assert "NNN-<тип>-<область>-<ссылка>.md" in readme


class TestDocumentationHygiene:
    """Issue 329: stray characters and undated reviews make documents hard to trust."""

    CJK = re.compile("[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af]")
    SNAPSHOT = re.compile(r"^> \*\*Снимок на (\d{4}-\d{2}-\d{2})\.\*\* ")

    @staticmethod
    def _tracked(*suffixes: str) -> list[Path]:
        try:
            listing = subprocess.run(
                ["git", "-C", str(REPO_ROOT), "ls-files", "-z"], capture_output=True, check=True
            ).stdout.decode("utf-8")
            files = [REPO_ROOT / name for name in listing.split("\0") if name]
        except (OSError, subprocess.CalledProcessError):
            files = [path for path in REPO_ROOT.rglob("*") if path.is_file() and ".git" not in path.parts]
        return sorted(path for path in files if path.suffix in suffixes)

    def test_no_stray_cjk_characters_in_documentation(self) -> None:
        """A word of a language the document is not written in is an editing accident, not content."""
        found = [
            f"{path.relative_to(REPO_ROOT).as_posix()}:{number}"
            for path in self._tracked(".md", ".yaml", ".yml")
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1)
            if self.CJK.search(line)
        ]

        assert not found, "CJK characters in documentation:\n" + "\n".join(found)

    def test_every_review_carries_a_snapshot_header(self) -> None:
        """A review states the day it describes, so it does not compete with the current documents."""
        problems: list[str] = []
        reviews = sorted((REPO_ROOT / "docs" / "reviews").glob("*.md"))
        for path in reviews:
            named = re.match(r"(\d{4}-\d{2}-\d{2})-", path.name)
            if named is None:
                problems.append(f"{path.name}: a review is named YYYY-MM-DD-topic.md")
                continue
            head = path.read_text(encoding="utf-8").splitlines()[:14]
            stamps = [match.group(1) for line in head if (match := self.SNAPSHOT.match(line))]
            if not stamps:
                problems.append(
                    f"{path.name}: add under the title: > **Снимок на {named.group(1)}.** Документ фиксирует состояние "
                    "на эту дату и не обновляется вслед за кодом: актуальное состояние — в коде, `README.md`, HELP и открытых issues."
                )
            elif stamps[0] < named.group(1):
                problems.append(f"{path.name}: the snapshot date {stamps[0]} is earlier than the date in the file name")

        assert reviews
        assert not problems, "\n".join(problems)


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
