"""Local dev helper: build stub system libraries for PySide6.

In sandboxes without apt access (and without `libGL.so.1`, `libEGL.so.1`,
`libdbus-1.so.3`, `libxkbcommon.so.0`) Qt refuses to start at all, which blocks
every GUI test. The same applies to QtWebEngine, which additionally wants NSS,
GBM, ALSA and a handful of X11 extensions; without them fifteen test modules
cannot even be imported locally, so CI is the first place their failures show
up — which is exactly how the ubuntu job caught bugs the local sweep missed
(plan §5.4). This script scans the PySide6 libraries/plugins for *undefined*
symbols and emits minimal shared objects exporting exactly those names, with the
required ELF version scripts (e.g. `dbus_server_get_address@LIBDBUS_1_3`).

Usage:
    python3 tools/qtstub/mkstub.py            # writes build output to lib/
    LD_LIBRARY_PATH=tools/qtstub/lib QT_QPA_PLATFORM=offscreen pytest tests/unit

Not part of the application — it only exists so GUI tests can run in a bare
container. The generated libraries are never called, they only need to resolve.
"""

from __future__ import annotations

import glob
import pathlib
import re
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
OUT = HERE / "lib"
#: ``(symbol regex, soname)``. Order matters: the first pattern that matches a
#: symbol claims it, so narrow prefixes must come before broad ones.
TARGETS = [
    (r"^dbus_", "libdbus-1.so.3"),
    (r"^(xkb_file_|XkbRF_|XkbCF|XkbNameMatchesAny|XkbFindSrvLedInfo)", "libxkbfile.so.1"),
    (r"^xkb_", "libxkbcommon.so.0"),
    (r"^egl", "libEGL.so.1"),
    # QtWebEngine dependencies (needed to import presentation.web_reference).
    (r"^(PR_|PL_|PORT_)", "libnspr4.so"),
    (r"^(NSS_|CERT_|PK11_|SEC_|SECKEY_|SECITEM_|SECOID_|SECMOD_|HASH_|VFY_|NSSBase64|SGN_|DER_)", "libnss3.so"),
    (r"^(SMIME|NSSSMIME)", "libsmime3.so"),
    (r"^(ATOB_|BTOA_|NSSUTIL_|PORT_Alloc|SECITEM_Alloc)", "libnssutil3.so"),
    (r"^gbm_", "libgbm.so.1"),
    (r"^snd_", "libasound.so.2"),
    (r"^xcb_dri3_", "libxcb-dri3.so.0"),
    (r"^XComposite", "libXcomposite.so.1"),
    (r"^XDamage", "libXdamage.so.1"),
    (r"^XFixes", "libXfixes.so.3"),
    (r"^(XRR|XRandr)", "libXrandr.so.2"),
    (r"^XTest", "libXtst.so.6"),
    (r"^(glX|gl)", "libGL.so.1"),
]

#: Version nodes a stub must declare even when no collected symbol carries
#: them (the consumer's ELF still lists the dependency).
EXTRA_VERSIONS: dict[str, tuple[str, ...]] = {
    "libnss3.so": ("NSS_3.5",),
    "libnspr4.so": ("NSPR_4.0",),
    "libnssutil3.so": ("NSSUTIL_3.12.3",),
    "libsmime3.so": ("NSS_3.10",),
}

#: Symbol prefixes worth collecting at all (everything else is resolved by the
#: real libc/libstdc++ present in the container).
_WANTED = re.compile(
    r"^(gl|glX|egl|xkb_|dbus_|PR_|PL_|PORT_|NSS|CERT_|PK11_|SEC_|SECKEY_|SECITEM_|SECOID_|SECMOD_"
    r"|HASH_|VFY_|SGN_|DER_|SMIME|ATOB_|BTOA_|gbm_|snd_|xcb_dri3_|XComposite|XDamage|XFixes|XRR"
    r"|XRandr|XTest|Xkb|xkb)"
)


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
            if not _WANTED.match(name):
                continue
            found.setdefault(name, (parts[3], version))
    return found


def build(symbols: dict[str, tuple[str, str | None]], soname: str) -> None:
    # A library can be needed even when nothing imports a symbol from it: the
    # dynamic loader still refuses to start if the DT_NEEDED entry cannot be
    # resolved. Emit an empty object in that case instead of skipping it.
    if not symbols:
        print(f"{soname}: no undefined symbols — emitting an empty stub")
    OUT.mkdir(parents=True, exist_ok=True)
    src = OUT / f"{soname}.c"
    body = ["/* auto-generated stub — resolved but never called */"]
    for name, (stype, _version) in sorted(symbols.items()):
        body.append(f"char {name}[256] = {{0}};" if stype == "OBJECT" else f"long {name}(void) {{ return 0; }}")
    src.write_text("\n".join(body) + "\n", encoding="utf-8")

    cmd = ["gcc", "-shared", "-fPIC", "-O0", "-o", str(OUT / soname), str(src), f"-Wl,-soname,{soname}"]
    # Every version node the consumers ask for must exist in the stub, even if
    # the symbol that carried it ended up in a sibling library: the loader
    # verifies version nodes per DT_NEEDED entry, not per symbol.
    versions = sorted({v for _t, v in symbols.values() if v} | set(EXTRA_VERSIONS.get(soname, ())))
    if versions:
        # Each symbol must land in the version node its consumer asks for.
        # A script of several `{ global: *; }` nodes puts everything into the
        # last one, and the loader then reports the symbol as undefined "with
        # version X" even though the name is present — which is precisely how
        # `snd_midi_event_free@ALSA_0.9` stayed unresolved.
        by_version: dict[str, list[str]] = {v: [] for v in versions}
        unversioned: list[str] = []
        for name, (_stype, version) in sorted(symbols.items()):
            (by_version[version] if version else unversioned).append(name)
        lines: list[str] = []
        for version in versions:
            names = by_version.get(version) or []
            body = " ".join(f"{n};" for n in names) if names else ""
            lines.append(f"{version} {{ global: {body} }};" if body else f"{version} {{ }};")
        if unversioned:
            # An anonymous tag cannot be combined with named ones, so the
            # version-less symbols go into a private base node instead.
            base = f"{soname.replace('.', '_').replace('-', '_').upper()}_BASE"
            lines.insert(0, f"{base} {{ global: " + " ".join(f"{n};" for n in unversioned) + " };")
        vmap = OUT / f"{soname}.map"
        vmap.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd.append(f"-Wl,--version-script={vmap}")
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise SystemExit(f"gcc failed for {soname}:\n{result.stderr}")
    print(f"{soname}: {len(symbols)} symbols, versions={versions or 'none'}")


def main() -> None:
    qt_root = _qt_root()
    found = collect(qt_root)
    print(f"collected {len(found)} undefined symbols from {qt_root}")
    claimed: set[str] = set()
    for pattern, soname in TARGETS:
        rx = re.compile(pattern)
        batch = {n: t for n, t in found.items() if n not in claimed and rx.match(n)}
        claimed.update(batch)
        build(batch, soname)


if __name__ == "__main__":
    main()
