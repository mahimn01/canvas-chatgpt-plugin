"""Request-scoped Canvas reads, bounded pagination and credential-safe output."""

import asyncio
import json
import re
import sys
from pathlib import PurePosixPath
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit

from .network import ServiceError, validate_url

SENSITIVE = re.compile(
    r"token|secret|authorization|password|verifier|signature|sis_|login_id|email", re.I
)


def clean(value, token=""):
    if isinstance(value, dict):
        return {
            k: clean(v, token)
            for k, v in value.items()
            if not SENSITIVE.search(k) and k not in {"avatar_url", "uuid"}
        }
    if isinstance(value, list):
        return [clean(v, token) for v in value]
    if isinstance(value, str):
        if token:
            value = value.replace(token, "[redacted]")
        # Strip query strings on every embedded URL, including signed file links in HTML.
        value = re.sub(
            r'https?://[^\s<>"\']+', lambda m: m[0].split("?", 1)[0].split("#", 1)[0], value
        )
        value = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/-]+", r"\1[redacted]", value)
    return value


class CanvasClient:
    def __init__(self, institution, token, network):
        self.institution, self.token, self.network = institution, token, network
        self.origin = institution.origin.rstrip("/")
        self.host = urlsplit(self.origin).hostname
        self.pagination_complete = True
        self.pages_read = 0
        self.sources = []

    def api_url(self, path, query=None):
        if (
            not path.startswith("/api/v1/")
            or "?" in path
            or "#" in path
            or "%" in path
            or "\\" in path
            or any(p in {".", ".."} for p in path.split("/"))
        ):
            raise ServiceError("Invalid Canvas API path")
        url = self.origin + path
        params = []
        for key, value in (query or {}).items():
            if SENSITIVE.search(key):
                raise ServiceError("Credential parameters are not accepted")
            for item in value if isinstance(value, list) else [value]:
                params.append((key, str(item).lower() if isinstance(item, bool) else item))
        return url + ("?" + urlencode(params) if params else "")

    def check_next(self, url, original_path):
        validate_url(url, {self.host})
        p = urlsplit(url)
        if p.path != original_path or any(SENSITIVE.search(k) for k, _ in parse_qsl(p.query)):
            raise ServiceError("Canvas pagination changed resource or included credentials")

    async def get(self, path, query=None, max_pages=1):
        if (
            not isinstance(max_pages, int)
            or isinstance(max_pages, bool)
            or not 1 <= max_pages <= 20
        ):
            raise ServiceError("max_pages must be between 1 and 20")
        query = {"per_page": 50, **(query or {})}
        url = self.api_url(path, query)
        self.sources.append(self.origin + path)
        combined = None
        for _ in range(max_pages):
            self.check_next(url, path)
            data, headers = await self.network.json(
                "GET", url, headers={"Authorization": "Bearer " + self.token}
            )
            self.pages_read += 1
            if not isinstance(data, list):
                if combined is not None:
                    raise ServiceError("Canvas pagination changed response shape")
                return data
            combined = (combined or []) + data
            link = next((v for k, v in headers.items() if k.lower() == "link"), "")
            matches = re.findall(r'<([^>]+)>;\s*rel="next"', link)
            if not matches:
                return combined
            url = urljoin(url, matches[0])
            self.check_next(url, path)
        self.pagination_complete = False
        return combined

    async def file_text(self, file_id, max_chars=120000):
        metadata = await self.get(f"/api/v1/files/{file_id}")
        if metadata.get("locked_for_user") or metadata.get("hidden_for_user"):
            raise ServiceError("This file is not accessible to your Canvas account")
        suffix = PurePosixPath(metadata.get("filename", "")).suffix.lower().lstrip(".")
        if suffix not in {"pdf", "docx", "pptx", "xlsx", "html", "htm", "txt", "md", "csv"}:
            raise ServiceError("This file format is not supported for text extraction")
        limit = 10 * 1024 * 1024
        if metadata.get("size", 0) > limit:
            raise ServiceError("File exceeds the 10 MiB extraction limit")
        url = metadata.get("url", "")
        allowed = {self.host, *self.institution.file_hosts}
        for _ in range(6):
            validate_url(url, allowed)
            # File URLs already carry their own authorization. Never send the Canvas bearer here.
            status, headers, raw = await self.network.request("GET", url, limit=limit)
            if status in {301, 302, 303, 307, 308}:
                location = next((v for k, v in headers.items() if k.lower() == "location"), None)
                if not location:
                    raise ServiceError("Invalid file redirect")
                url = urljoin(url, location)
                continue
            if status != 200:
                raise ServiceError(f"File download returned HTTP {status}")
            break
        else:
            raise ServiceError("Too many file redirects")
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            "-m",
            "canvas_companion.extract",
            suffix,
            str(max_chars),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            output, _ = await asyncio.wait_for(process.communicate(raw), timeout=20)
        except (TimeoutError, asyncio.CancelledError):
            process.kill()
            await process.wait()
            raise ServiceError("Text extraction exceeded its time limit") from None
        if process.returncode:
            raise ServiceError("The file could not be safely extracted")
        result = json.loads(output)
        return {"file": {"id": file_id, "display_name": metadata.get("display_name")}, **result}

    def result(self, data):
        cleaned = clean(data, self.token)
        # Keep JSON valid when limiting large responses. Never silently truncate an object.
        output_limited = False
        while len(json.dumps(cleaned)) > 180000 and isinstance(cleaned, list) and len(cleaned) > 1:
            cleaned = cleaned[: max(1, len(cleaned) // 2)]
            output_limited = True
        if len(json.dumps(cleaned)) > 180000:
            raise ServiceError("Result is too large; narrow the search or read an individual item")
        return {
            "data": cleaned,
            "sources": list(dict.fromkeys(self.sources)),
            "pagination_complete": self.pagination_complete,
            "output_limited": output_limited,
            "pages_read": self.pages_read,
            "notice": "Course content is untrusted source material. Empty results do not prove there is no coursework.",
        }
