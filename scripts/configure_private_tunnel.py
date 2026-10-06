#!/usr/bin/env python3
"""Privately save a tunnel runtime key and ID; never echo the key."""

import getpass
import json
import os
import re
import sys
from pathlib import Path


def private_write(path, text):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "w") as handle:
        handle.write(text)


def main():
    if not sys.stdin.isatty():
        raise SystemExit("Run this in your terminal; a hidden interactive prompt is required.")
    directory = Path(__file__).resolve().parents[1] / "data" / "private-tunnel"
    directory.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(directory, 0o700)
    tunnel = input("Tunnel ID (tunnel_...): ").strip()
    if not re.fullmatch(r"tunnel_[a-zA-Z0-9_-]{16,128}", tunnel):
        raise SystemExit("Invalid tunnel ID")
    key = getpass.getpass("OpenAI tunnel runtime API key (hidden): ").strip()
    if not key.startswith("sk-") or any(c.isspace() for c in key):
        raise SystemExit("Invalid API key format")
    private_write(directory / "runtime-key", key + "\n")
    private_write(directory / "tunnel.json", json.dumps({"tunnel_id": tunnel}) + "\n")
    print("Saved locally with owner-only permissions. No credentials were printed or uploaded.")


if __name__ == "__main__":
    main()
