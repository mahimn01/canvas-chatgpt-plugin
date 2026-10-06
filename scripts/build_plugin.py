#!/usr/bin/env python3
"""Build an allowlisted plugin ZIP after a real deployment and review video exist."""

import argparse
import json
from pathlib import Path
from urllib.parse import urlsplit
from zipfile import ZIP_DEFLATED, ZipFile


def public_https(value):
    p = urlsplit(value)
    if (
        p.scheme != "https"
        or not p.hostname
        or p.username
        or p.password
        or p.query
        or p.fragment
        or p.port not in (None, 443)
        or p.hostname.endswith((".example.com", ".localhost", ".invalid"))
        or p.hostname in {"example.com", "localhost"}
    ):
        raise argparse.ArgumentTypeError(
            "Supply a real public HTTPS URL without credentials or queries"
        )
    return value.rstrip("/")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", type=public_https, required=True)
    parser.add_argument("--video-url", type=public_https, required=True)
    parser.add_argument("--logo", type=Path, required=True, help="PNG logo for the listing")
    parser.add_argument(
        "--screenshot",
        type=Path,
        required=True,
        help="PNG screenshot containing synthetic data only",
    )
    args = parser.parse_args()
    if urlsplit(args.base_url).path:
        parser.error("--base-url must be a plain origin")
    root = Path(__file__).resolve().parents[1]
    template = root / "plugin-template"
    manifest = json.loads(
        (template / ".codex-plugin/plugin.json")
        .read_text()
        .replace("https://canvas-companion.example.com", args.base_url)
    )
    manifest["extensions"]["com.openai"]["review"]["demo_recording_url"] = args.video_url
    manifest["interface"].update(
        {
            "logo": "./assets/logo.png",
            "composerIcon": "./assets/logo.png",
            "screenshots": ["./assets/screenshot.png"],
        }
    )
    assets = {}
    for source, target in [
        (args.logo, "assets/logo.png"),
        (args.screenshot, "assets/screenshot.png"),
    ]:
        raw = source.read_bytes()
        if not raw.startswith(b"\x89PNG\r\n\x1a\n") or len(raw) > 10 * 1024 * 1024:
            parser.error("Assets must be PNG files no larger than 10 MiB")
        assets[target] = raw
    destination = root / "dist/course-companion-canvas.zip"
    destination.parent.mkdir(exist_ok=True)
    with ZipFile(destination, "w", ZIP_DEFLATED) as archive:
        archive.writestr(".codex-plugin/plugin.json", json.dumps(manifest, indent=2) + "\n")
        for name in [".mcp.json", "skills/get-started/SKILL.md"]:
            archive.writestr(
                name,
                (template / name)
                .read_text()
                .replace("https://canvas-companion.example.com", args.base_url),
            )
        archive.writestr("LICENSE", (root / "LICENSE").read_text())
        for name, raw in assets.items():
            archive.writestr(name, raw)
    print(f"Built {destination}. This does not validate hosting or constitute submission approval.")


if __name__ == "__main__":
    main()
