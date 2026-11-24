#!/usr/bin/env bash
# Sign one manifest using the same path for a release and its opt-in dry run.
set -euo pipefail

manifest=${1:?manifest path required}
: "${GPG_PRIVATE_KEY:?GPG_PRIVATE_KEY is required}"
# Ephemeral keyring; never print the secret or put it in the workspace.
export GNUPGHOME
GNUPGHOME=$(mktemp -d "${RUNNER_TEMP:-${TMPDIR:-/tmp}}/sonoforge-gpg.XXXXXXXX")
chmod 700 "$GNUPGHOME"
trap 'gpgconf --homedir "$GNUPGHOME" --kill gpg-agent >/dev/null 2>&1 || true; rm -rf -- "$GNUPGHOME"' EXIT
printf '%s\n' "$GPG_PRIVATE_KEY" | gpg --batch --yes --import
primary=$(gpg --batch --with-colons --list-secret-keys | awk -F: '/^fpr:/ {print $10; exit}')
if [ -z "$primary" ]; then
  echo 'GPG_PRIVATE_KEY imported but contains no secret key' >&2
  exit 1
fi
keyid=$primary
if [ -n "${GPG_SIGNING_SUBKEY:-}" ]; then
  if [[ ! "$GPG_SIGNING_SUBKEY" =~ ^[0-9a-fA-F]{40}$ ]]; then
    echo 'GPG_SIGNING_SUBKEY must be a full 40-character fingerprint' >&2
    exit 1
  fi
  keyid="${GPG_SIGNING_SUBKEY^^}!"
fi
args=(--batch --yes --armor --detach-sign --local-user "$keyid")
if [ -n "${GPG_PASSPHRASE:-}" ]; then
  args+=(--pinentry-mode loopback --passphrase-fd 3)
fi
gpg "${args[@]}" "$manifest" 3<<<"${GPG_PASSPHRASE:-}"
status=$(gpg --batch --status-fd 1 --verify "$manifest.asc" "$manifest")
if [ -n "${GPG_SIGNING_SUBKEY:-}" ] && ! grep -Fq "[GNUPG:] VALIDSIG ${GPG_SIGNING_SUBKEY^^} " <<<"$status"; then
  echo 'Signature does not match GPG_SIGNING_SUBKEY' >&2
  exit 1
fi
echo "Signed $manifest with primary fingerprint $primary"
if [ -n "${GITHUB_OUTPUT:-}" ]; then
  printf 'fingerprint=%s\n' "$primary" >> "$GITHUB_OUTPUT"
fi
