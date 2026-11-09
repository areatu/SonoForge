#!/usr/bin/env python3
"""Bind generated CycloneDX metadata to a release before attestation."""

from __future__ import annotations

import argparse
import json
import uuid
from pathlib import Path


def finalize(path: Path, version: str, repo: str = "areatu/SonoForge") -> None:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("bomFormat") != "CycloneDX" or data.get("specVersion") != "1.6" or not data.get("components"):
        raise ValueError("expected a non-empty CycloneDX 1.6 SBOM")
    serial = "urn:uuid:" + str(uuid.uuid5(uuid.NAMESPACE_URL, f"https://github.com/{repo}/releases/tag/v{version}"))
    if data.get("serialNumber") not in (None, serial):
        raise ValueError("SBOM serialNumber does not match the release")
    data["serialNumber"] = serial
    component = data.setdefault("metadata", {}).setdefault("component", {})
    if component.get("version") not in (None, version):
        raise ValueError("SBOM component version does not match the release")
    component.setdefault("type", "application")
    component.setdefault("name", "SonoForge")
    component["version"] = version
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path)
    parser.add_argument("version")
    args = parser.parse_args()
    finalize(args.path, args.version)


if __name__ == "__main__":
    main()
