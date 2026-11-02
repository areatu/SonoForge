"""Tests for the documentation link check (issue #329).

The audit found comments and specs that name files nobody can clone
(`docs/superpowers/plans/` is in `.gitignore`) and relative links into the void.
`scripts/check_doc_links.py` keeps both at zero; these tests pin what counts as a
link, what counts as a reference to an ignored directory, the allowlist rules and
the command line.
"""

from __future__ import annotations

import ast
import json
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import check_doc_links  # noqa: E402

SCRIPT_FILE = REPO_ROOT / "scripts" / "check_doc_links.py"
ALLOWLIST_FILE = REPO_ROOT / "scripts" / "doc_links_allowlist.json"
CI_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "ci.yml"
GITIGNORE = "docs/superpowers/plans/\ndocs/compose/\n"


def _tree(tmp_path: Path, files: dict[str, str]) -> Path:
    for name, content in files.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(textwrap.dedent(content), encoding="utf-8")
    return tmp_path


def _links(text: str) -> list[tuple[int, str]]:
    return list(check_doc_links.markdown_links(textwrap.dedent(text)))


def _broken(tmp_path: Path, files: dict[str, str]) -> list[str]:
    root = _tree(tmp_path, files)
    return [
        str(violation) for violation in check_doc_links.find_broken_links(root, check_doc_links.tracked_files(root))
    ]


def _ignored_refs(tmp_path: Path, files: dict[str, str], allowlist: dict[str, str] | None = None) -> list[str]:
    root = _tree(tmp_path, {".gitignore": GITIGNORE, **files})
    found = check_doc_links.find_ignored_references(root, check_doc_links.tracked_files(root), allowlist or {})
    return [str(violation) for violation in found]


class TestFindingLinks:
    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("see [the plan](../plans/a.md) now", [(1, "../plans/a.md")]),
            ("![shot](img/a.png)", [(1, "img/a.png")]),
            ("[a](x.md) and [b](y.md)", [(1, "x.md"), (1, "y.md")]),
            ('[titled](x.md "A title")', [(1, "x.md")]),
            ("[angle](<dir with space/x.md>)", [(1, "dir with space/x.md")]),
            ("[ref]: ../docs/x.md", [(1, "../docs/x.md")]),
            ("[`code text`](x.md)", [(1, "x.md")]),
            ("first line\n[a](x.md)", [(2, "x.md")]),
        ],
    )
    def test_these_are_links(self, text: str, expected: list[tuple[int, str]]) -> None:
        assert _links(text) == expected

    @pytest.mark.parametrize(
        "text",
        [
            "an example: `[a](missing.md)`",
            "double `` `[a](missing.md)` `` span",
            "```\n[a](missing.md)\n```",
            "~~~md\n[a](missing.md)\n~~~",
            "plain text (not a link) [just brackets]",
            "[no target]()",
        ],
        ids=["inline-code", "double-backtick", "fenced", "tilde-fence", "no-link", "empty-target"],
    )
    def test_these_are_not(self, text: str) -> None:
        assert _links(text) == []

    def test_a_link_after_a_closed_fence_is_seen_again(self) -> None:
        assert _links("```\n[a](skipped.md)\n```\n[b](seen.md)") == [(4, "seen.md")]


class TestResolving:
    def test_a_relative_link_resolves_against_the_file_and_a_slash_against_the_root(self, tmp_path: Path) -> None:
        source = tmp_path / "docs" / "a" / "page.md"

        assert (
            check_doc_links.resolve_link(source, "../b/x.md", tmp_path) == (tmp_path / "docs" / "b" / "x.md").resolve()
        )
        assert check_doc_links.resolve_link(source, "/README.md", tmp_path) == (tmp_path / "README.md").resolve()

    @pytest.mark.parametrize(
        "target",
        ["#section", "https://example.org/x.md", "http://x", "mailto:a@b.c", "ftp://x/y", "data:text/plain,hi", ""],
    )
    def test_urls_and_in_page_anchors_are_not_files(self, tmp_path: Path, target: str) -> None:
        assert check_doc_links.resolve_link(tmp_path / "a.md", target, tmp_path) is None

    def test_an_anchor_a_query_and_percent_encoding_are_stripped(self, tmp_path: Path) -> None:
        source = tmp_path / "a.md"
        expected = (tmp_path / "dir with space" / "x.md").resolve()

        assert check_doc_links.resolve_link(source, "dir%20with%20space/x.md#part", tmp_path) == expected
        assert check_doc_links.resolve_link(source, "dir%20with%20space/x.md?raw=1", tmp_path) == expected


class TestBrokenLinks:
    def test_a_link_to_a_missing_file_is_reported_with_its_line(self, tmp_path: Path) -> None:
        found = _broken(tmp_path, {"docs/a.md": "intro\n[plan](../plans/p.md)\n"})

        assert found == ["docs/a.md:2: broken link: ../plans/p.md"]

    def test_existing_files_directories_images_and_other_extensions_pass(self, tmp_path: Path) -> None:
        found = _broken(
            tmp_path,
            {
                "docs/a.md": "[b](b.md) [dir](sub/) [code](../src/x.py) ![i](img.png) [up](../README.md#top)\n",
                "docs/b.md": "",
                "docs/sub/c.md": "",
                "docs/img.png": "",
                "src/x.py": "",
                "README.md": "",
            },
        )

        assert found == []

    def test_a_missing_image_and_a_missing_reference_definition_are_reported(self, tmp_path: Path) -> None:
        found = _broken(tmp_path, {"a.md": "![i](gone.png)\n\n[ref]: gone.md\n"})

        assert found == ["a.md:1: broken link: gone.png", "a.md:3: broken link: gone.md"]

    def test_links_in_code_are_examples_not_links(self, tmp_path: Path) -> None:
        assert _broken(tmp_path, {"a.md": "`[x](gone.md)`\n\n```\n[x](gone.md)\n```\n"}) == []

    def test_only_markdown_files_are_scanned(self, tmp_path: Path) -> None:
        assert _broken(tmp_path, {"a.py": "# [x](gone.md)\n", "a.txt": "[x](gone.md)\n"}) == []


class TestIgnoredReferences:
    def test_a_reference_in_markdown_and_in_code_is_reported(self, tmp_path: Path) -> None:
        found = _ignored_refs(
            tmp_path,
            {
                "docs/spec.md": "see `docs/superpowers/plans/x.md`\n",
                "src/mod.py": "# plan: docs/compose/y.md\n",
            },
        )

        assert len(found) == 2
        assert found[0].startswith("docs/spec.md:1: names `docs/superpowers/plans/`")
        assert found[1].startswith("src/mod.py:1: names `docs/compose/`")

    def test_gitignore_itself_and_unrelated_files_are_fine(self, tmp_path: Path) -> None:
        assert (
            _ignored_refs(tmp_path, {"docs/spec.md": "see docs/superpowers/specs/x.md\n", "bin.dat": "docs/compose/"})
            == []
        )

    def test_an_allowlisted_file_may_describe_the_gap(self, tmp_path: Path) -> None:
        files = {"docs/review.md": "the directory docs/superpowers/plans/ is ignored\n"}

        assert _ignored_refs(tmp_path, files, {"docs/review.md": "describes the gap"}) == []

    def test_a_stale_allowlist_entry_fails(self, tmp_path: Path) -> None:
        found = _ignored_refs(tmp_path, {"docs/review.md": "clean now\n"}, {"docs/review.md": "describes the gap"})

        assert found == [
            "docs/review.md:0: stale allowlist entry — the file no longer names an ignored directory; remove it"
        ]

    def test_only_documentation_directories_with_a_trailing_slash_count(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path,
            {
                ".gitignore": "# docs/tracked/ is tracked\ndocs/plans\n!docs/keep/\nbuild/\ndocs/local/\n",
                "a.md": "docs/tracked/x docs/plans docs/keep/x build/y docs/local/z\n",
            },
        )

        assert check_doc_links.ignored_doc_dirs(root) == ["docs/local"]

    def test_without_a_gitignore_there_is_nothing_to_check(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"a.md": "docs/superpowers/plans/x.md\n"})

        assert check_doc_links.find_ignored_references(root, check_doc_links.tracked_files(root), {}) == []


class TestDiscovery:
    def test_a_git_repository_lists_only_tracked_files(self, tmp_path: Path) -> None:
        root = _tree(
            tmp_path,
            {
                ".gitignore": "ignored/\n",
                "tracked.md": "[a](gone.md)\n",
                "ignored/skipped.md": "[a](gone.md)\n",
                "loose.md": "x\n",
            },
        )
        subprocess.run(["git", "init", "-q"], cwd=root, check=True)
        subprocess.run(["git", "add", ".gitignore", "tracked.md"], cwd=root, check=True)

        names = sorted(path.relative_to(root).as_posix() for path in check_doc_links.tracked_files(root))

        assert names == [".gitignore", "tracked.md"]

    def test_a_directory_inside_another_repository_is_walked_not_listed_as_empty(self, tmp_path: Path) -> None:
        subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
        inner = _tree(tmp_path / "vendored", {"a.md": "x\n", "sub/b.md": "x\n"})

        names = sorted(path.relative_to(inner).as_posix() for path in check_doc_links.tracked_files(inner))

        assert names == ["a.md", "sub/b.md"]

    def test_outside_a_repository_the_walk_skips_tool_directories(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {"a.md": "x\n", ".venv/lib/b.md": "x\n", "node_modules/c.md": "x\n", "d/e.md": "x\n"})

        names = sorted(path.relative_to(root).as_posix() for path in check_doc_links.tracked_files(root))

        assert names == ["a.md", "d/e.md"]


class TestCommandLine:
    def test_a_clean_tree_passes(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = _tree(tmp_path, {"a.md": "[b](b.md)\n", "b.md": "text\n"})

        assert check_doc_links.main(["--root", str(root)]) == 0
        assert "documentation links passed: 2 Markdown files" in capsys.readouterr().out

    def test_a_broken_link_fails_and_is_listed(self, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
        root = _tree(tmp_path, {"a.md": "[b](gone.md)\n"})

        assert check_doc_links.main(["--root", str(root)]) == 1
        assert "a.md:1: broken link: gone.md" in capsys.readouterr().err

    def test_an_allowlist_without_a_reason_is_an_error(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        root = _tree(
            tmp_path, {"a.md": "text\n", "scripts/doc_links_allowlist.json": json.dumps({"allowed": {"a.md": " "}})}
        )

        assert check_doc_links.main(["--root", str(root)]) == 2
        assert "non-empty reason" in capsys.readouterr().err

    def test_a_missing_allowlist_means_no_exceptions(self, tmp_path: Path) -> None:
        root = _tree(tmp_path, {".gitignore": GITIGNORE, "a.md": "docs/compose/x.md\n"})

        assert check_doc_links.main(["--root", str(root)]) == 1


class TestRepository:
    def test_the_repository_passes_the_check(self) -> None:
        assert check_doc_links.main([]) == 0

    def test_every_exception_carries_a_reason_and_names_an_existing_file(self) -> None:
        allowlist = check_doc_links.load_allowlist(ALLOWLIST_FILE)

        assert allowlist
        assert all(reason.strip() for reason in allowlist.values())
        assert all((REPO_ROOT / name).is_file() for name in allowlist)

    def test_the_ignored_directories_are_the_ones_the_issue_named(self) -> None:
        assert {"docs/superpowers/plans", "docs/compose"} <= set(check_doc_links.ignored_doc_dirs(REPO_ROOT))

    def test_the_check_runs_in_the_lint_job(self) -> None:
        workflow = yaml.safe_load(CI_WORKFLOW.read_text(encoding="utf-8"))
        commands = [str(step.get("run", "")) for step in workflow["jobs"]["lint"]["steps"]]

        assert "python scripts/check_doc_links.py" in commands

    def test_the_script_needs_nothing_the_lint_job_does_not_install(self) -> None:
        tree = ast.parse(SCRIPT_FILE.read_text(encoding="utf-8"))
        modules = {
            alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names
        }
        modules |= {
            node.module.split(".")[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module and node.level == 0
        }

        assert modules <= set(sys.stdlib_module_names)
