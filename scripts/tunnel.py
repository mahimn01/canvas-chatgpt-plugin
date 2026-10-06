#!/usr/bin/env python3
"""Manage the personal tunnel without exposing keys or verbose runtime logs."""

import argparse
import json
import os
import shlex
import shutil
import subprocess
import time
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "status", "stop"])
    parser.add_argument("--client", help="Absolute path to the official tunnel-client executable")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    private = root / "data" / "private-tunnel"
    private.mkdir(parents=True, mode=0o700, exist_ok=True)
    os.chmod(private, 0o700)
    client_file = private / "client-path"
    candidate = args.client or (client_file.read_text().strip() if client_file.exists() else None)
    candidate = candidate or str(private / "bin" / "tunnel-client")
    client = Path(candidate).expanduser().resolve()
    if not client.is_file():
        installed = shutil.which("tunnel-client")
        if not installed:
            parser.error("Supply --client with the official tunnel-client executable path")
        client = Path(installed).resolve()
    if args.action == "start":
        if not (private / "runtime-key").is_file() or not (private / "tunnel.json").is_file():
            parser.error("Run scripts/configure_private_tunnel.py first")
        launcher = private / "run-canvas.sh"
        if os.getenv("CANVAS_BASE_URL") or os.getenv("CANVAS_TOKEN_FILE") or not launcher.exists():
            origin, token = os.getenv("CANVAS_BASE_URL"), os.getenv("CANVAS_TOKEN_FILE")
            if not origin or not token:
                parser.error("First start requires CANVAS_BASE_URL and CANVAS_TOKEN_FILE")
            token = str(Path(token).expanduser().resolve())
            content = (
                "#!/bin/sh\n"
                + "\n".join(
                    "export " + name + "=" + shlex.quote(value)
                    for name, value in {
                        "CANVAS_BASE_URL": origin,
                        "CANVAS_TOKEN_FILE": token,
                        "CANVAS_FILE_HOSTS": os.getenv("CANVAS_FILE_HOSTS", ""),
                    }.items()
                )
                + "\ncd "
                + shlex.quote(str(root))
                + "\nexec "
                + shlex.quote(str(root / ".venv/bin/python"))
                + " -m canvas_companion.personal\n"
            )
            launcher.write_text(content)
            launcher.chmod(0o700)
        tunnel = json.loads((private / "tunnel.json").read_text())["tunnel_id"]
        command = [
            str(client),
            "runtimes",
            "connect",
            "--alias",
            "canvas-personal",
            "--profile",
            "canvas-personal",
            "--profile-dir",
            str(private / "profiles"),
            "--tunnel-id",
            tunnel,
            "--mcp-command",
            shlex.quote(str(launcher)),
            "--runtime-api-key",
            "file:" + str(private / "runtime-key"),
            "--json",
        ]
    else:
        command = [str(client), "runtimes", args.action, "canvas-personal", "--json"]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    try:
        data = json.loads(result.stdout)
    except ValueError:
        raise SystemExit(
            "Tunnel client did not return valid status; use its local diagnostics."
        ) from None
    client_file.write_text(str(client) + "\n")
    client_file.chmod(0o600)
    print(
        json.dumps(
            {
                k: data[k]
                for k in (
                    "alias",
                    "process_running",
                    "running",
                    "healthy",
                    "ready",
                    "runtime_state",
                    "stopped",
                )
                if k in data
            },
            indent=2,
        )
    )
    if result.returncode:
        raise SystemExit("Tunnel command failed. Check the official client's local diagnostics.")
    if args.action in {"start", "status"}:
        status = subprocess.run(
            [str(client), "runtimes", "status", "canvas-personal", "--json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        state = json.loads(status.stdout)
        if not (state.get("process_running") and state.get("healthy") and state.get("ready")):
            raise SystemExit("Runtime is not ready; inspect official tunnel-client diagnostics.")
        for attempt in range(10):
            health = subprocess.run(
                [
                    str(client),
                    "health",
                    "--url",
                    state["ui_url"].removesuffix("/ui"),
                    "--require-control-plane-poll",
                    "--json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if health.returncode == 0 or args.action != "start" or attempt == 9:
                break
            time.sleep(1)
        print(
            "OpenAI control-plane poll: "
            + ("ok" if health.returncode == 0 else "not confirmed yet; retry status")
        )
        # A new daemon can be ready before its first long-poll completes.
        # Status remains strict; successful process creation is still a successful start.
        if health.returncode and args.action == "status":
            raise SystemExit(1)


if __name__ == "__main__":
    main()
