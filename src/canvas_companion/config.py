"""Explicit deployment configuration; no local personal credentials are imported."""

import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.fernet import Fernet


def https_origin(value: str) -> str:
    url = urlsplit(value)
    if (
        url.scheme != "https"
        or not url.hostname
        or url.username
        or url.password
        or url.path not in ("", "/")
        or url.query
        or url.fragment
        or url.port not in (None, 443)
    ):
        raise ValueError("Expected a plain HTTPS origin on port 443")
    return value.rstrip("/")


def file_host(host: str, file_id: int) -> str:
    """Expand only a file-ID placeholder into one exact, configured DNS hostname."""
    if isinstance(file_id, bool) or not isinstance(file_id, int) or file_id <= 0:
        raise ValueError("File ID must be a positive integer")
    if host.count("{file_id}") > 1:
        raise ValueError("Only one file-ID placeholder is allowed")
    expanded = host.replace("{file_id}", str(file_id))
    label = r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?"
    if len(expanded) > 253 or not re.fullmatch(rf"{label}(?:\.{label})+", expanded):
        raise ValueError("File hosts must be exact lowercase DNS names, optionally with {file_id}")
    return expanded


@dataclass(frozen=True)
class Institution:
    id: str
    name: str
    origin: str
    client_id: str
    client_secret: str = field(repr=False)
    file_hosts: tuple[str, ...] = ()

    def __post_init__(self):
        https_origin(self.origin)
        if not self.id.isalnum() or not self.client_id or not self.client_secret:
            raise ValueError("Institution needs an alphanumeric ID and OAuth credentials")
        for host in self.file_hosts:
            file_host(host, 1)


@dataclass(frozen=True)
class Settings:
    mode: str = "demo"
    public_url: str = "http://127.0.0.1:8000"
    issuer: str = ""
    oidc_client_id: str = ""
    oidc_client_secret: str = field(default="", repr=False)
    encryption_key: str = field(default="", repr=False)
    database: str = "data/connections.sqlite3"
    institutions: tuple[Institution, ...] = ()
    challenge: str = ""

    def __post_init__(self):
        if self.mode not in {"demo", "production"}:
            raise ValueError("MODE must be demo or production")
        if self.mode == "production":
            https_origin(self.public_url)
            https_origin(self.issuer)
            Fernet(self.encryption_key.encode())
            if not self.oidc_client_id or not self.oidc_client_secret or not self.institutions:
                raise ValueError("Production requires an identity provider and Canvas OAuth keys")
            if len({i.id for i in self.institutions}) != len(self.institutions):
                raise ValueError("Duplicate institution IDs")

    @property
    def resource(self):
        return self.public_url.rstrip("/") + "/mcp"

    @classmethod
    def from_env(cls):
        mode = os.getenv("MODE", "demo")
        institutions = []
        if mode == "production":
            for row in json.loads(Path(os.environ["INSTITUTIONS_FILE"]).read_text()):
                row["client_secret"] = os.environ[row.pop("client_secret_env")]
                row["file_hosts"] = tuple(row.get("file_hosts", []))
                institutions.append(Institution(**row))
        return cls(
            mode=mode,
            public_url=os.getenv("PUBLIC_URL", "http://127.0.0.1:8000"),
            issuer=os.getenv("OIDC_ISSUER", ""),
            oidc_client_id=os.getenv("OIDC_CLIENT_ID", ""),
            oidc_client_secret=os.getenv("OIDC_CLIENT_SECRET", ""),
            encryption_key=os.getenv("TOKEN_ENCRYPTION_KEY", ""),
            database=os.getenv("DATABASE_PATH", "data/connections.sqlite3"),
            institutions=tuple(institutions),
            challenge=os.getenv("OPENAI_DOMAIN_CHALLENGE", ""),
        )
