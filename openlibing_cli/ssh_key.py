"""SSH key handling — read existing or generate a new RSA 2048 keypair.

Mirrors `readLocalPublicKey` / `generateSSHKeyPair` in the extension.
"""

import os
import subprocess
from pathlib import Path

from .constants import DEFAULT_KEY_NAME, DEFAULT_KEY_COMMENT


def ssh_dir():
    return Path(os.path.expanduser("~/.ssh"))


def key_path():
    return ssh_dir() / DEFAULT_KEY_NAME


def pub_path():
    return ssh_dir() / f"{DEFAULT_KEY_NAME}.pub"


def read_public_key():
    """Return contents of ~/.ssh/id_rsa.pub, or None if missing."""
    p = pub_path()
    if not p.exists():
        return None
    return p.read_text().strip()


def keypair_exists():
    return key_path().exists() and pub_path().exists()


def generate_keypair(force=False, comment=None):
    """Generate RSA 2048 keypair with ssh-keygen, return the public key text.

    Mirrors the extension's call shape:
        ssh-keygen -t rsa -b 2048 -f ~/.ssh/id_rsa -N "" -C "resource-manager-vscode-plugin"
    """
    if keypair_exists() and not force:
        return read_public_key()

    d = ssh_dir()
    d.mkdir(mode=0o700, parents=True, exist_ok=True)

    comment = comment or DEFAULT_KEY_COMMENT
    cmd = [
        "ssh-keygen",
        "-t", "rsa",
        "-b", "2048",
        "-f", str(key_path()),
        "-N", "",
        "-C", comment,
    ]
    # We don't have a TTY here in most script contexts, so ssh-keygen with
    # -N "" should be non-interactive. Capture stderr for diagnostics.
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise RuntimeError(
            f"ssh-keygen failed (rc={result.returncode}): {result.stderr.strip()}"
        )
    try:
        os.chmod(key_path(), 0o600)
    except OSError:
        pass
    return read_public_key()


def ensure_public_key(*, auto_generate=False, force=False):
    """Read pub key, optionally generating it.

    Raises FileNotFoundError if missing and auto_generate is False.
    """
    if not force:
        existing = read_public_key()
        if existing:
            return existing
    if not auto_generate:
        raise FileNotFoundError(
            f"No public key at {pub_path()}. "
            f"Re-run with --generate-key to create one."
        )
    return generate_keypair(force=force)
