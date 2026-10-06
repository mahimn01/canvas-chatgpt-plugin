"""Single-owner stdio mode. No public HTTP listener or token-entry website."""

import asyncio
import os
import stat
from pathlib import Path
from types import SimpleNamespace

from mcp.server.stdio import stdio_server

from .canvas import CanvasClient
from .config import https_origin
from .network import Network, ServiceError


def read_token(path):
    directory = path.parent.lstat()
    if (
        not stat.S_ISDIR(directory.st_mode)
        or directory.st_uid != os.getuid()
        or stat.S_IMODE(directory.st_mode) & 0o077
    ):
        raise ServiceError("Credential directory must be owned by you with mode 0700")
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_CLOEXEC | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as handle:
        metadata = os.fstat(handle.fileno())
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) & 0o077
            or metadata.st_nlink != 1
        ):
            raise ServiceError("Token must be a private regular file with mode 0600")
        raw = handle.read(4097)
    token = raw.decode("ascii").strip()
    if not token or len(raw) > 4096 or any(ord(c) <= 32 or ord(c) == 127 for c in token):
        raise ServiceError("Invalid credential format")
    return token


async def main():
    from .server import create_server

    origin = https_origin(os.environ["CANVAS_BASE_URL"])
    path = Path(os.environ["CANVAS_TOKEN_FILE"]).expanduser()
    institution = SimpleNamespace(
        origin=origin, file_hosts=tuple(filter(None, os.getenv("CANVAS_FILE_HOSTS", "").split(",")))
    )

    async def client():
        return CanvasClient(institution, read_token(path), Network())

    server = create_server(client, personal=True)
    async with stdio_server() as (reader, writer):
        await server.run(reader, writer, server.create_initialization_options())


if __name__ == "__main__":
    asyncio.run(main())
