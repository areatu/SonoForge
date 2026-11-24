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
    # the script picked per platform. GPG_BIN pins the fake everywhere.
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
    )
    fake.chmod(0o700)
    gpgconf = tmp_path / "gpgconf"
    gpgconf.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    gpgconf.chmod(0o700)
    manifest = tmp_path / "SHA256SUMS"
    manifest.write_text("test\n", encoding="utf-8")
    env = {
        **os.environ,
        "RUNNER_TEMP": str(tmp_path),
        "GPG_BIN": fake.as_posix(),
        "GPGCONF_BIN": gpgconf.as_posix(),
        "CALLS": str(tmp_path / "calls"),
        "PRIMARY": PRIMARY,
        "VALIDSIG": SUBKEY,
        "GPG_PRIVATE_KEY": "private-test-data",
        "GPG_PASSPHRASE": "private-test-passphrase",
        "GPG_SIGNING_SUBKEY": SUBKEY,
        "GITHUB_OUTPUT": str(tmp_path / "output"),
    }
    return env, manifest


def _sign(env: dict[str, str], manifest: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["bash", str(SCRIPT), str(manifest)], env=env, capture_output=True, text=True, check=False)


def test_signs_with_explicit_subkey_and_cleans_isolated_keyring(signing_environment) -> None:
    env, manifest = signing_environment
    result = _sign(env, manifest)
    assert result.returncode == 0, result.stderr
    calls = Path(env["CALLS"]).read_text(encoding="utf-8")
    assert f"--local-user {SUBKEY}!" in calls
    assert "--passphrase-fd 3" in calls
    assert env["GPG_PASSPHRASE"] not in calls + result.stdout + result.stderr
    assert env["GPG_PRIVATE_KEY"] not in result.stdout + result.stderr
    assert Path(env["GITHUB_OUTPUT"]).read_text(encoding="utf-8") == f"fingerprint={PRIMARY}\n"
    assert not list(manifest.parent.glob("sonoforge-gpg.*"))


def test_rejects_signature_from_another_subkey(signing_environment) -> None:
    env, manifest = signing_environment
    env["VALIDSIG"] = PRIMARY
    result = _sign(env, manifest)
    assert result.returncode != 0
    assert "does not match GPG_SIGNING_SUBKEY" in result.stderr
    assert not list(manifest.parent.glob("sonoforge-gpg.*"))


def test_rejects_invalid_fingerprint(signing_environment) -> None:
    env, manifest = signing_environment
    env["GPG_SIGNING_SUBKEY"] = "bad fingerprint"
    result = _sign(env, manifest)
    assert result.returncode != 0
    assert "full 40-character fingerprint" in result.stderr


def test_preserves_existing_primary_key_selection_without_subkey_variable(signing_environment) -> None:
    env, manifest = signing_environment
    env.pop("GPG_SIGNING_SUBKEY")
    env.pop("GPG_PASSPHRASE")
    result = _sign(env, manifest)
    assert result.returncode == 0, result.stderr
    calls = Path(env["CALLS"]).read_text(encoding="utf-8")
    assert f"--local-user {PRIMARY}" in calls
    assert "--passphrase-fd" not in calls
