#!/usr/bin/env python3
"""Build ``latest.json`` — the stable-name manifest of a release's assets.

Release binaries carry the version in their names, so no fixed file name can
double as "the newest build". The manifest solves it: the small, stable-named
asset ``latest.json`` (reachable at ``releases/latest/download/latest.json``)
lists every downloadable asset of the release with its versioned URL, size and
SHA-256. This is the electron-updater (``latest.yml``) / Tauri (``latest.json``)
pattern: versioned binaries plus one tiny manifest as the permanent link.

The manifest is rebuilt from the *published* release state as the last step of
every workflow that attaches assets (``release.yml``, ``presenter.yml``), so
whichever run finishes last leaves a complete picture behind — including the
Presenter builds attached by a separate workflow.

The manifest deliberately lists only the binaries covered by the ``SHA256SUMS``
manifests. SBOMs and the checksum manifests themselves are attestation
material, not things a downloader fetches.

Modes:

* ``--repo``/``--tag``: fetch the published asset list and the ``SHA256SUMS*``
  manifests from the release with the ``gh`` CLI (release jobs).
* ``--assets-json``/``--sums``: build from captured data (tests, offline use).

Output is deterministic (assets sorted by name) for easy diffing.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

SCHEMA = 1
SUM_MANIFESTS = ("SHA256SUMS", "SHA256SUMS-presenter.txt")


def parse_sums(text: str) -> dict[str, str]:
    """Parse ``sha256sum`` output: ``<hex>  <file name>`` per line.

    File names are compared and returned as bare base names, so manifests
    written in a download directory resolve against the published assets.
    """
    sums: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        digest, _, name = line.partition("  ")
        if not name:
            digest, _, name = line.partition(" ")
        name = name.strip().lstrip("*")
        if not name or len(digest) != 64:
            continue
        sums[Path(name).name] = digest.lower()
    return sums


def build_manifest(
    tag: str,
    assets: list[dict],
    sums: dict[str, str],
    published_at: str | None = None,
    repo: str | None = None,
) -> dict:
    """Assemble the manifest for one release.

    ``assets`` items need ``name`` and ``size``; ``url`` is taken from the item
    when present, otherwise built from ``repo``/``tag`` (gh's
    ``browser_download_url`` is preferred when available). Only assets listed
    in ``sums`` are included; sha256 comes from ``sums``.
    """
    entries = []
    for asset in assets:
        name = asset.get("name", "")
        if not name or name not in sums:
            continue
        url = asset.get("url") or (f"https://github.com/{repo}/releases/download/{tag}/{name}" if repo else None)
        if not url:
            raise ValueError(f"asset {name!r} has no url and no repo to build one")
        entries.append(
            {
                "name": name,
                "url": url,
                "size": int(asset.get("size", 0)),
                "sha256": sums[name],
            }
        )
    entries.sort(key=lambda e: e["name"])
    return {
        "schema": SCHEMA,
        "tag": tag,
        "published_at": published_at,
        "assets": entries,
    }


def fetch_release(repo: str, tag: str) -> dict:
    """Fetch the release via the REST API.

    ``gh release view --json assets`` omits the per-asset ``digest`` field, and
    the fallback digest source (``sums_from_assets``) needs it.
    """
    out = subprocess.run(
        ["gh", "api", f"repos/{repo}/releases/tags/{tag}"],
        capture_output=True,
        text=True,
        check=True,
    )
    data = json.loads(out.stdout)
    assets = [
        {
            "name": a.get("name", ""),
            "size": a.get("size", 0),
            "url": a.get("browser_download_url"),
            "digest": a.get("digest"),
        }
        for a in data.get("assets", [])
    ]
    return {"assets": assets, "publishedAt": data.get("published_at")}


def sums_from_assets(assets: list[dict]) -> dict[str, str]:
    """Fallback source of digests: the release API's per-asset ``digest`` field.

    Used when the ``SHA256SUMS*`` manifests cannot be downloaded (restricted
    networks) — the API digest is the same hash the manifests carry. Attestation
    material (SBOMs, checksum manifests, signatures) is excluded: it is not
    listed in the manifests either, and ``latest.json`` is a downloader's index.
    """
    sums: dict[str, str] = {}
    for asset in assets:
        name = asset.get("name", "")
        digest = asset.get("digest") or ""
        if not name or not digest.startswith("sha256:"):
            continue
        if (
            name.endswith(".sbom.cdx.json")
            or name.startswith("SHA256SUMS")
            or name.endswith(".asc")
            or name == "latest.json"
        ):
            continue
        sums[name] = digest.removeprefix("sha256:")
    return sums


def fetch_sums(repo: str, tag: str) -> dict[str, str]:
    sums: dict[str, str] = {}
    with tempfile.TemporaryDirectory() as tmp:
        try:
            subprocess.run(
                [
                    "gh",
                    "release",
                    "download",
                    tag,
                    "--repo",
                    repo,
                    "--pattern",
                    "SHA256SUMS*",
                    "--dir",
                    tmp,
                ],
                capture_output=True,
                text=True,
                check=True,
            )
        except subprocess.CalledProcessError:
            return {}
        for path in sorted(Path(tmp).iterdir()):
            if path.is_file():
                sums.update(parse_sums(path.read_text(encoding="utf-8")))
    return sums


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--tag", required=True, help="release tag, e.g. v0.3.2")
    parser.add_argument("--repo", help="owner/name of the GitHub repository")
    parser.add_argument("--published-at", default=None, help="release timestamp override")
    parser.add_argument(
        "--assets-json",
        type=Path,
        help="JSON file with [{name, size, url?}, ...] instead of asking gh",
    )
    parser.add_argument(
        "--sums",
        type=Path,
        action="append",
        default=[],
        help="sha256sum-format file(s) instead of downloading SHA256SUMS* from the release",
    )
    parser.add_argument("--output", type=Path, default=Path("latest.json"))
    args = parser.parse_args(argv)

    if args.assets_json:
        assets = json.loads(args.assets_json.read_text(encoding="utf-8"))
    else:
        if not args.repo:
            parser.error("--repo is required unless --assets-json is given")
        release = fetch_release(args.repo, args.tag)
        assets = release.get("assets", [])
        if args.published_at is None:
            args.published_at = release.get("publishedAt")

    sums: dict[str, str] = {}
    for path in args.sums:
        sums.update(parse_sums(path.read_text(encoding="utf-8")))
    if not args.sums:
        if not args.repo:
            parser.error("--sums is required unless --repo is given")
        sums = fetch_sums(args.repo, args.tag)
        if not sums:
            sums = sums_from_assets(assets)

    manifest = build_manifest(
        tag=args.tag,
        assets=assets,
        sums=sums,
        published_at=args.published_at,
        repo=args.repo,
    )
    if not manifest["assets"]:
        print("no assets matched the checksum manifests", file=sys.stderr)
        return 1
    args.output.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{args.output}: {len(manifest['assets'])} assets for {args.tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
