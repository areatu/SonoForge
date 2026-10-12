"""Tests for tools/release/latest_json.py — the stable-name release manifest."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools" / "release"))

import latest_json  # noqa: E402


def test_parse_sums_reads_sha256sum_format() -> None:
    text = (
        "a" * 64
        + "  SonoForge-0.3.2-portable.exe\n"
        + "b" * 64
        + " *sonoforge_0.3.2_amd64.deb\n"
        + "\n"
        + "# comment\n"
        + "not-a-digest  broken.txt\n"
    )
    sums = latest_json.parse_sums(text)
    assert sums == {
        "SonoForge-0.3.2-portable.exe": "a" * 64,
        "sonoforge_0.3.2_amd64.deb": "b" * 64,
    }


def test_parse_sums_resolves_to_base_names() -> None:
    sums = latest_json.parse_sums("c" * 64 + "  downloads/SonoForge-Setup-0.3.2-x64.exe\n")
    assert sums == {"SonoForge-Setup-0.3.2-x64.exe": "c" * 64}


def test_build_manifest_lists_only_checksummed_assets_sorted() -> None:
    assets = [
        {"name": "SonoForge-0.3.2-portable.exe", "size": 389761009},
        {"name": "SonoForge-0.3.2-windows-x64.sbom.cdx.json", "size": 96804},
        {"name": "sonoforge_0.3.2_amd64.deb", "size": 38333902},
        {"name": "SHA256SUMS", "size": 642},
    ]
    sums = {
        "SonoForge-0.3.2-portable.exe": "a" * 64,
        "sonoforge_0.3.2_amd64.deb": "b" * 64,
    }
    manifest = latest_json.build_manifest(
        tag="v0.3.2",
        assets=assets,
        sums=sums,
        published_at="2026-10-11T12:00:00Z",
        repo="areatu/SonoForge",
    )
    assert manifest["schema"] == 1
    assert manifest["tag"] == "v0.3.2"
    assert manifest["published_at"] == "2026-10-11T12:00:00Z"
    # SBOMs and the manifests themselves are attestation material, not
    # download targets — only checksummed binaries are listed.
    assert [e["name"] for e in manifest["assets"]] == [
        "SonoForge-0.3.2-portable.exe",
        "sonoforge_0.3.2_amd64.deb",
    ]
    assert manifest["assets"][0] == {
        "name": "SonoForge-0.3.2-portable.exe",
        "url": ("https://github.com/areatu/SonoForge/releases/download/v0.3.2/SonoForge-0.3.2-portable.exe"),
        "size": 389761009,
        "sha256": "a" * 64,
    }


def test_build_manifest_prefers_explicit_url() -> None:
    assets = [{"name": "x.deb", "size": 1, "url": "https://example.invalid/x.deb"}]
    manifest = latest_json.build_manifest(tag="v1", assets=assets, sums={"x.deb": "d" * 64}, repo="o/r")
    assert manifest["assets"][0]["url"] == "https://example.invalid/x.deb"


def test_build_manifest_requires_url_without_repo() -> None:
    try:
        latest_json.build_manifest(tag="v1", assets=[{"name": "x.deb", "size": 1}], sums={"x.deb": "d" * 64})
    except ValueError:
        return
    raise AssertionError("expected ValueError for a url-less asset without repo")


def test_sums_from_assets_reads_api_digests_and_skips_attestation_material() -> None:
    assets = [
        {"name": "SonoForge-0.3.2-portable.exe", "digest": "sha256:" + "a" * 64},
        {"name": "SonoForge-0.3.2-windows-x64.sbom.cdx.json", "digest": "sha256:" + "b" * 64},
        {"name": "SHA256SUMS", "digest": "sha256:" + "c" * 64},
        {"name": "latest.json", "digest": "sha256:" + "d" * 64},
        {"name": "sonoforge_0.3.2_amd64.deb", "digest": None},
        {"name": "sonoforge-0.3.2.tar.gz", "digest": "sha256:" + "e" * 64},
    ]
    assert latest_json.sums_from_assets(assets) == {
        "SonoForge-0.3.2-portable.exe": "a" * 64,
        "sonoforge-0.3.2.tar.gz": "e" * 64,
    }


def test_main_writes_manifest_from_files(tmp_path: Path) -> None:
    assets_json = tmp_path / "assets.json"
    assets_json.write_text(
        json.dumps(
            [
                {"name": "SonoForgePresenter-0.3.2.exe", "size": 154192348},
                {"name": "SonoForge-Presenter-0.3.2-x86_64.AppImage", "size": 180242936},
            ]
        ),
        encoding="utf-8",
    )
    sums = tmp_path / "SHA256SUMS-presenter.txt"
    sums.write_text(
        "1" * 64 + "  SonoForgePresenter-0.3.2.exe\n" + "2" * 64 + "  SonoForge-Presenter-0.3.2-x86_64.AppImage\n",
        encoding="utf-8",
    )
    out = tmp_path / "latest.json"
    rc = latest_json.main(
        [
            "--tag",
            "v0.3.2",
            "--repo",
            "areatu/SonoForge",
            "--assets-json",
            str(assets_json),
            "--sums",
            str(sums),
            "--output",
            str(out),
        ]
    )
    assert rc == 0
    manifest = json.loads(out.read_text(encoding="utf-8"))
    assert manifest["tag"] == "v0.3.2"
    assert [e["name"] for e in manifest["assets"]] == [
        "SonoForge-Presenter-0.3.2-x86_64.AppImage",
        "SonoForgePresenter-0.3.2.exe",
    ]


def test_main_fails_when_nothing_matches(tmp_path: Path) -> None:
    assets_json = tmp_path / "assets.json"
    assets_json.write_text(json.dumps([{"name": "sbom.json", "size": 5}]), encoding="utf-8")
    sums = tmp_path / "SHA256SUMS"
    sums.write_text("a" * 64 + "  other.exe\n", encoding="utf-8")
    rc = latest_json.main(
        [
            "--tag",
            "v1",
            "--assets-json",
            str(assets_json),
            "--sums",
            str(sums),
            "--output",
            str(tmp_path / "latest.json"),
        ]
    )
    assert rc == 1
