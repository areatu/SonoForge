"""Local dev helper: build stub GL/EGL/dbus/xkb libraries for PySide6.

In sandboxes without apt access (and without `libGL.so.1`, `libEGL.so.1`,
`libdbus-1.so.3`, `libxkbcommon.so.0`) Qt refuses to start at all, which blocks
every GUI test. This script scans the PySide6 libraries/plugins for *undefined*
symbols and emits minimal shared objects exporting exactly those names, with the
required ELF version scripts (e.g. `dbus_server_get_address@LIBDBUS_1_3`).

Usage:
    python3 tools/qtstub/mkstub.py            # writes build output to lib/
    LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen pytest tests/unit

Not part of the application — it only exists so GUI tests can run in a bare
container. The generated libraries are never called, they only need to resolve.
"""
from __future__ import annotations

import argparse
import glob
import os
import pathlib
import re
import subprocess
import sys

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "lib"
PROJECT_ROOT = HERE.parent.parent  # repo root


def _assert_not_production() -> None:
    """Refuse to run outside CI or the dev sandbox."""
    if os.environ.get("CI") or os.environ.get("PYTEST_CURRENT_TEST") or os.environ.get("MKSTUB_CI_ONLY"):
        return
    raise SystemExit(
        "mkstub.py is a CI-only tool — it generates stub .so files.\n"
        "Set CI=1 or PYTEST_CURRENT_TEST=1 or MKSTUB_CI_ONLY=1 to force."
    )


def _assert_output_safe() -> None:
    """Make sure OUT never points outside the project tree."""
    try:
        OUT.resolve().relative_to(PROJECT_ROOT)
    except ValueError:
        raise SystemExit(
            f"Refusing: OUT={OUT} is outside the project root ({PROJECT_ROOT}).\n"
            "This tool must not write to system directories."
        )


TARGETS = [
    (r"^dbus_", "libdbus-1.so.3"),
    (r"^xkb_", "libxkbcommon.so.0"),
    (r"^egl", "libEGL.so.1"),
    (r"^(glX|gl)", "libGL.so.1"),
]


def _qt_root() -> pathlib.Path:
    import PySide6

    return pathlib.Path(PySide6.__file__).resolve().parent / "Qt"


def collect(qt_root: pathlib.Path) -> dict[str, tuple[str, str | None]]:
    found: dict[str, tuple[str, str | None]] = {}
    candidates = set(glob.glob(str(qt_root / "lib" / "*.so*")))
    candidates.update(glob.glob(str(qt_root / "plugins" / "**" / "*.so"), recursive=True))
    for lib in sorted(candidates):
        out = subprocess.run(["readelf", "--dyn-syms", "-W", lib], capture_output=True, text=True).stdout
        for line in out.splitlines():
            parts = line.split()
            # Num: Value Size Type Bind Vis Ndx Name — imports have Ndx == UND
            if len(parts) < 8 or parts[6] != "UND":
                continue
            raw = parts[7]
            name, version = raw.split("@", 1) if "@" in raw else (raw, None)
            if not re.match(r"^(gl|glX|egl|xkb_|dbus_)", name):
                continue
            found.setdefault(name, (parts[3], version))
    return found


def build(symbols: dict[str, tuple[str, str | None]], soname: str, *, dry_run: bool = False) -> None:
    if not symbols:
        print(f"{soname}: no undefined symbols found", file=sys.stderr)
        return
    if dry_run:
        print(f"[dry-run] would build {soname} with {len(symbols)} symbols")
        return
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / f"{soname}.c"
    body = ["/* auto-generated stub — resolved but never called */"]
    for name, (stype, _version) in sorted(symbols.items()):
        body.append(f"char {name}[256] = {{0}};" if stype == "OBJECT" else f"long {name}(void) {{ return 0; }}")
    src.write_text("\n".join(body) + "\n", encoding="utf-8")

    cmd = ["gcc", "-shared", "-fPIC", "-O0", "-o", str(OUT / soname), str(src), f"-Wl,-soname,{soname}"]
    versions = sorted({v for _t, v in symbols.values() if v})
    if versions:
        vmap = OUT / f"{soname}.map"
        vmap.write_text("\n".join(f"{v} {{ global: *; }};" for v in versions) + "\n", encoding="utf-8")
        cmd.append(f"-Wl,--version-script={vmap}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"gcc failed for {soname}:\n{result.stderr}")
    print(f"{soname}: {len(symbols)} symbols, versions={versions or 'none'}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build stub GL/EGL/dbus/xkb libraries for PySide6.")
    parser.add_argument("--dry-run", action="store_true", help="Show what would be built without gcc")
    args = parser.parse_args()

    _assert_not_production()
    _assert_output_safe()

    qt_root = _qt_root()
    found = collect(qt_root)
    print(f"collected {len(found)} undefined symbols from {qt_root}")
    for pattern, soname in TARGETS:
        rx = re.compile(pattern)
        build({n: t for n, t in found.items() if rx.match(n)}, soname, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
