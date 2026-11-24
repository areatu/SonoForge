"""Release signing checks without private keys or external GPG dependencies."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools/release/sign_checksums.sh"
PRIMARY = "E231CA97068B6FD9DBA2696B56A26E00755AA57A"
SUBKEY = "1A5627BF368987B7F1DCC9409EE80D1A063BE8C8"


@pytest.fixture
def signing_environment(tmp_path: Path) -> tuple[dict[str, str], Path]:
    # The script takes GPG_BIN/GPGCONF_BIN instead of a PATH injection: the
    # native PATH separator on Windows is ";" and Git Bash cannot resolve a
    # prepended backslash temp directory, which silently changed which binary
    # the script picked per platform. GPG_BIN pins the fake everywhere. Every
    # path handed to bash is POSIX-shaped and every fake is LF-only: Python on
    # Windows would otherwise write CRLF files, and bash on other platforms
    # rejects CRLF scripts outright.
    fake = tmp_path / "gpg"
    fake.write_text(
        "#!/usr/bin/env bash\n"
        "set -e\n"
        'printf "%s\\n" "$*" >> "$CALLS"\n'
        'if [[ "$*" == *--import* ]]; then cat >/dev/null; '
        'elif [[ "$*" == *--list-secret-keys* ]]; then printf "sec#:::::::::\\nfpr:::::::::%s:\\n" "$PRIMARY"; '
        'elif [[ "$*" == *--detach-sign* ]]; then for last; do :; done; touch "$last.asc"; '
        'elif [[ "$*" == *--verify* ]]; then printf "[GNUPG:] VALIDSIG %s 2026-01-01\\n" "$VALIDSIG"; fi\n',
        encoding="utf-8",
        newline="\n",
    )
    fake.chmod(0o700)
    gpgconf = tmp_path / "gpgconf"
    gpgconf.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8", newline="\n")
    gpgconf.chmod(0o700)
    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text("test\n", encoding="utf-8", newline="\n")
    env = {
        **os.environ,
        "RUNNER_TEMP": tmp_path.as_posix(),
        "GPG_BIN": fake.as_posix(),
        "GPGCONF_BIN": gpgconf.as_posix(),
        "CALLS": (tmp_path / "calls").as_posix(),
        "PRIMARY": PRIMARY,
        "VALIDSIG": SUBKEY,
        "GPG_PRIVATE_KEY": "private-test-data",
        "GPG_PASSPHRASE": "private-test-passphrase",
        "GPG_SIGNING_SUBKEY": SUBKEY,
        "GITHUB_OUTPUT": (tmp_path / "output").as_posix(),
    }
    return env, manifest.as_posix()


def _sign(env: dict[str, str], manifest: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", SCRIPT.as_posix(), manifest], env=env, capture_output=True, text=True, check=False)


def _context(env: dict[str, str], result: subprocess.CompletedProcess[str]) -> str:
    """One line carrying everything needed to read a failure from CI annotations."""
    calls_path = Path(env["CALLS"])
    calls = calls_path.read_text(encoding="utf-8").replace("\n", " ; ") if calls_path.exists() else "<no calls file>"
    output_path = Path(env["GITHUB_OUTPUT"])
    listing = " , ".join(sorted(p.name for p in output_path.parent.iterdir()))
    return (
        f"rc={result.returncode} | stderr={result.stderr!r} | stdout={result.stdout!r} "
        f"| calls=[{calls}] | dir=[{listing}]"
    )


def test_signs_with_explicit_subkey_and_cleans_isolated_keyring(signing_environment) -> None:
    env, manifest = signing_environment
    result = _sign(env, manifest)
    assert result.returncode == 0, _context(env, result)
    calls = Path(env["CALLS"]).read_text(encoding="utf-8")
    assert f"--local-user {SUBKEY}!" in calls, _context(env, result)
    assert "--passphrase-fd 3" in calls, _context(env, result)
    assert env["GPG_PASSPHRASE"] not in calls + result.stdout + result.stderr, _context(env, result)
    assert env["GPG_PRIVATE_KEY"] not in result.stdout + result.stderr, _context(env, result)
    output = Path(env["GITHUB_OUTPUT"])
    assert output.exists(), _context(env, result)
    assert output.read_text(encoding="utf-8") == f"fingerprint={PRIMARY}\n", _context(env, result)
    assert not list(Path(manifest).parent.glob("sonoforge-gpg.*")), _context(env, result)


def test_rejects_signature_from_another_subkey(signing_environment) -> None:
    env, manifest = signing_environment
    env["VALIDSIG"] = PRIMARY
    result = _sign(env, manifest)
    assert result.returncode != 0, _context(env, result)
    assert "does not match GPG_SIGNING_SUBKEY" in result.stderr, _context(env, result)
    assert not list(Path(manifest).parent.glob("sonoforge-gpg.*")), _context(env, result)


def test_rejects_invalid_fingerprint(signing_environment) -> None:
    env, manifest = signing_environment
    env["GPG_SIGNING_SUBKEY"] = "bad fingerprint"
    result = _sign(env, manifest)
    assert result.returncode != 0, _context(env, result)
    assert "full 40-character fingerprint" in result.stderr, _context(env, result)


def test_preserves_existing_primary_key_selection_without_subkey_variable(signing_environment) -> None:
    env, manifest = signing_environment
    env.pop("GPG_SIGNING_SUBKEY")
    env.pop("GPG_PASSPHRASE")
    result = _sign(env, manifest)
    assert result.returncode == 0, _context(env, result)
    calls = Path(env["CALLS"]).read_text(encoding="utf-8")
    assert f"--local-user {PRIMARY}" in calls, _context(env, result)
    assert "--passphrase-fd" not in calls, _context(env, result)
