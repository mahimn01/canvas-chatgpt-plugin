"""Bounded HTTPS with DNS answers validated at the actual connection boundary."""

import ipaddress
import json
import socket
from urllib.parse import urlsplit

import aiohttp


class ServiceError(Exception):
    """Safe, user-visible error. Never include upstream bodies or credential URLs."""


def public_ip(address: str):
    ip = ipaddress.ip_address(address)
    if not ip.is_global or (getattr(ip, "ipv4_mapped", None) and not ip.ipv4_mapped.is_global):
        raise ServiceError("Private or reserved network destinations are blocked")


def validate_url(url: str, hosts: set[str] | None = None):
    try:
        p = urlsplit(url)
        if (
            p.scheme != "https"
            or not p.hostname
            or p.username
            or p.password
            or p.fragment
            or p.port not in (None, 443)
            or "\\" in url
            or any(ord(c) < 33 for c in url)
        ):
            raise ValueError()
        if hosts is not None and p.hostname not in hosts:
            raise ServiceError("Destination is outside the configured host allowlist")
        try:
            ipaddress.ip_address(p.hostname)
        except ValueError:
            if p.hostname == "localhost" or p.hostname.endswith(".localhost"):
                raise ServiceError("Local destinations are blocked")
        else:
            public_ip(p.hostname)
    except ValueError:
        raise ServiceError("Invalid HTTPS destination") from None


class PublicResolver(aiohttp.ThreadedResolver):
    async def resolve(self, host, port=0, family=socket.AF_INET):
        records = await super().resolve(host, port, family)
        for record in records:
            public_ip(record["host"])
        return records


class Network:
    async def request(self, method, url, *, headers=None, data=None, limit=2_000_000):
        validate_url(url)
        try:
            # DNS records are passed directly to the connector, never re-resolved after checking.
            async with aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(resolver=PublicResolver()),
                cookie_jar=aiohttp.DummyCookieJar(),
                trust_env=False,
                timeout=aiohttp.ClientTimeout(total=25),
                auto_decompress=False,
                headers={"Accept-Encoding": "identity", "User-Agent": "CanvasCompanion/0.1"},
            ) as session:
                async with session.request(
                    method, url, headers=headers, data=data, allow_redirects=False
                ) as response:
                    body = bytearray()
                    async for chunk in response.content.iter_chunked(65536):
                        body.extend(chunk)
                        if len(body) > limit:
                            raise ServiceError("Upstream response exceeds the size limit")
                    return response.status, dict(response.headers), bytes(body)
        except (aiohttp.ClientError, TimeoutError, OSError):
            raise ServiceError("Upstream connection failed; retry later") from None

    async def json(self, method, url, **kwargs):
        status, headers, body = await self.request(method, url, **kwargs)
        if status < 200 or status >= 300:
            raise ServiceError(f"Upstream returned HTTP {status}; access may be unavailable")
        try:
            return json.loads(body), headers
        except (ValueError, UnicodeError):
            raise ServiceError("Upstream returned invalid JSON") from None
