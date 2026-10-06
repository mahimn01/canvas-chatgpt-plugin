import asyncio
import json
import sqlite3
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import jwt
import pytest
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from canvas_companion.auth import IdentityProvider
from canvas_companion.canvas import CanvasClient, clean
from canvas_companion.config import Institution, Settings, file_host
from canvas_companion.connections import Connections
from canvas_companion.network import ServiceError, validate_url
from canvas_companion.operations import tool_get_inbox_conversation
from canvas_companion.personal import read_token
from canvas_companion.server import catalog
from canvas_companion.store import Store
from canvas_companion.web import COOKIE, create_app


class QueueNetwork:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    async def json(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)

    async def request(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        return self.responses.pop(0)


def production(tmp_path):
    return Settings(
        mode="production",
        public_url="https://companion.example.com",
        issuer="https://identity.example.com",
        oidc_client_id="browser-client",
        oidc_client_secret="test-secret",
        encryption_key=Fernet.generate_key().decode(),
        database=str(tmp_path / "private" / "connections.sqlite3"),
        institutions=(
            Institution("demo", "Test institution", "https://canvas.example.edu", "id", "secret"),
        ),
    )


def canvas(network):
    return CanvasClient(
        SimpleNamespace(origin="https://canvas.example.edu", file_hosts=()),
        "private-token",
        network,
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://canvas.example.edu",
        "https://127.0.0.1/x",
        "https://[::1]/x",
        "https://169.254.169.254/",
        "https://10.0.0.1/",
        "https://localhost/",
        "https://canvas.example.edu:444/",
        "https://secret@canvas.example.edu/",
        "https://canvas.example.edu/\\bad",
        "https://canvas.example.edu/#fragment",
    ],
)
def test_reject_unsafe_destinations(url):
    with pytest.raises(ServiceError):
        validate_url(url)


@pytest.mark.parametrize(
    "next_url",
    [
        "https://other.example.com/api/v1/courses?page=2",
        "https://canvas.example.edu/api/v1/files?page=2",
        "https://canvas.example.edu/api/v1/courses?access_token=secret",
    ],
)
async def test_pagination_cannot_forward_bearer_elsewhere(next_url):
    network = QueueNetwork(([{"id": 1}], {"Link": f'<{next_url}>; rel="next"'}))
    with pytest.raises(ServiceError):
        await canvas(network).get("/api/v1/courses", max_pages=2)
    assert len(network.calls) == 1


async def test_pagination_signals_incomplete_result():
    network = QueueNetwork(
        ([{"id": 1}], {"Link": '<https://canvas.example.edu/api/v1/courses?page=2>; rel="next"'})
    )
    client = canvas(network)
    result = client.result(await client.get("/api/v1/courses"))
    assert not result["pagination_complete"]
    assert result["pages_read"] == 1


async def test_inbox_read_does_not_mark_read():
    network = QueueNetwork(({"id": 2}, {}))
    await tool_get_inbox_conversation(canvas(network), {"conversation_id": 2})
    method, url, _ = network.calls[0]
    assert method == "GET"
    assert parse_qs(urlsplit(url).query)["auto_mark_as_read"] == ["false"]


async def test_file_redirect_never_receives_canvas_token():
    network = QueueNetwork(
        (
            {
                "filename": "sample.txt",
                "size": 5,
                "url": "https://canvas.example.edu/files/1?verifier=private",
            },
            {},
        ),
        (302, {"Location": "https://other.example.com/stolen"}, b""),
    )
    with pytest.raises(ServiceError):
        await canvas(network).file_text(1)
    assert len(network.calls) == 2
    assert "headers" not in network.calls[1][2]


async def test_locked_file_is_never_downloaded():
    network = QueueNetwork(({"locked_for_user": True}, {}))
    with pytest.raises(ServiceError):
        await canvas(network).file_text(1)
    assert len(network.calls) == 1


async def test_file_specific_storage_host_allows_only_requested_file():
    network = QueueNetwork(
        ({"filename": "sample.txt", "size": 5, "url": "https://canvas.example.edu/files/42"}, {}),
        (302, {"Location": "https://account-42.storage.example.edu/file"}, b""),
        (200, {}, b"hello"),
    )
    client = canvas(network)
    client.institution.file_hosts = ("account-{file_id}.storage.example.edu",)
    assert (await client.file_text(42))["text"] == "hello"
    assert all("headers" not in call[2] for call in network.calls[1:])
    network.responses = [
        ({"filename": "sample.txt", "url": "https://account-43.storage.example.edu/file"}, {}),
    ]
    with pytest.raises(ServiceError):
        await client.file_text(42)
    for host in [
        "*.example.edu",
        "account-{other}.example.edu",
        "evil.example/path",
        "UPPER.example",
    ]:
        with pytest.raises(ValueError):
            file_host(host, 42)


def test_output_redacts_credentials_and_keeps_valid_json():
    result = clean(
        {
            "access_token": "secret",
            "text": 'private-token <a href="https://files.example/a?verifier=secret">File</a>',
        },
        "private-token",
    )
    serialized = json.dumps(result)
    assert "secret" not in serialized and "private-token" not in serialized
    result = canvas(None).result([{"text": "a" * 90000}, {"text": "b" * 90000}])
    assert result["output_limited"] and len(result["data"]) == 1


def test_store_encryption_isolation_one_use_and_expiry(tmp_path):
    store = Store(str(tmp_path / "store.sqlite3"), Fernet.generate_key().decode())
    store.put("connection", "alice", {"token": "very-private-secret"})
    assert store.get("connection", "bob") is None
    assert b"very-private-secret" not in (tmp_path / "store.sqlite3").read_bytes()
    state = store.issue("oauth", {"subject": "alice"})
    assert store.get("oauth", state, consume=True) == {"subject": "alice"}
    assert store.get("oauth", state, consume=True) is None
    store.put("old", "expired", {"x": 1}, ttl=-1)
    assert store.get("old", "expired") is None
    # Moving encrypted data between account IDs cannot rebind the credential.
    with sqlite3.connect(store.filename) as db:
        db.execute("UPDATE records SET id=? WHERE kind='connection'", (store.index("bob"),))
    with pytest.raises(ValueError):
        store.get("connection", "bob")


async def test_refresh_is_serialized_per_subject_and_preserves_refresh_token(tmp_path):
    settings = production(tmp_path)
    store = Store(settings.database, settings.encryption_key)
    network = QueueNetwork(({"access_token": "fresh", "expires_in": 3600}, {}))
    connections = Connections(settings, store, network)
    connections._save(
        "alice", "demo", {"access_token": "old", "refresh_token": "refresh", "expires_in": -1}
    )
    a, b = await asyncio.gather(connections.credentials("alice"), connections.credentials("alice"))
    assert a[1] == b[1] == "fresh" and len(network.calls) == 1
    assert store.get("connection", "alice")["refresh_token"] == "refresh"
    with pytest.raises(ServiceError):
        await connections.credentials("bob")


async def test_jwt_rejects_wrong_audience_expiry_signature_and_scope(tmp_path):
    settings = production(tmp_path)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    identity = IdentityProvider(settings, QueueNetwork())
    identity._keys, identity._keys_at = {"test": key.public_key()}, time.time()
    claims = {
        "iss": settings.issuer,
        "aud": settings.resource,
        "sub": "alice",
        "iat": int(time.time()),
        "exp": int(time.time()) + 300,
        "scope": "canvas:read",
    }

    def encode(payload, private=key):
        return jwt.encode(payload, private, algorithm="RS256", headers={"kid": "test"})

    assert (await identity.verify_token(encode(claims))).subject == "alice"
    for payload in [
        {**claims, "aud": "different-resource"},
        {**claims, "exp": 1},
        {**claims, "scope": "profile"},
    ]:
        assert await identity.verify_token(encode(payload)) is None
    assert await identity.verify_token(encode(claims, other)) is None


def test_personal_token_file_rejects_symlink_and_open_permissions(tmp_path):
    directory = tmp_path / "credentials"
    directory.mkdir(mode=0o700)
    token = directory / "token"
    token.write_text("example-credential")
    token.chmod(0o600)
    assert read_token(token) == "example-credential"
    link = directory / "link"
    link.symlink_to(token)
    with pytest.raises(OSError):
        read_token(link)
    token.chmod(0o644)
    with pytest.raises(ServiceError):
        read_token(token)


def test_http_oauth_challenge_and_csrf(tmp_path):
    settings = production(tmp_path)
    app = create_app(settings)
    with TestClient(app, base_url=settings.public_url) as client:
        response = client.post("/mcp", json={})
        assert response.status_code == 401
        assert "/.well-known/oauth-protected-resource/mcp" in response.headers["www-authenticate"]
        metadata = client.get("/.well-known/oauth-protected-resource/mcp").json()
        assert metadata["resource"] == settings.resource
        session = app.state.store.issue("session", {"subject": "alice", "csrf": "test-csrf"})
        client.cookies.set(COOKIE, session)
        response = client.post(
            "/disconnect",
            data={"csrf": "test-csrf"},
            headers={"Origin": "https://attacker.example"},
        )
        assert response.status_code == 400
        assert "Invalid form origin" in response.text


def test_demo_mcp_protocol_and_input_validation():
    with TestClient(create_app(), base_url="http://127.0.0.1:8000") as client:

        def rpc(method, params=None):
            result = client.post(
                "/mcp",
                headers={"Accept": "application/json, text/event-stream"},
                json={"jsonrpc": "2.0", "id": 1, "method": method, "params": params or {}},
            )
            assert result.status_code == 200
            return result.json()["result"]

        assert (
            rpc(
                "initialize",
                {
                    "protocolVersion": "2025-03-26",
                    "capabilities": {},
                    "clientInfo": {"name": "test", "version": "1"},
                },
            )["serverInfo"]["name"]
            == "canvas-companion"
        )
        tools = rpc("tools/list")["tools"]
        assert len(tools) == 23 and all(t["annotations"]["readOnlyHint"] for t in tools)
        result = rpc("tools/call", {"name": "canvas_list_courses", "arguments": {}})
        assert result["structuredContent"]["data"][0]["id"] == 101
        identifiers = {
            "course_id": 101,
            "assignment_id": 201,
            "module_id": 301,
            "page_url": "syllabus",
            "topic_id": 801,
            "file_id": 701,
            "conversation_id": 601,
        }
        for tool in tools:
            arguments = {key: identifiers[key] for key in tool["inputSchema"].get("required", [])}
            result = rpc("tools/call", {"name": tool["name"], "arguments": arguments})
            assert not result.get("isError"), (tool["name"], result)
            assert "data" in result["structuredContent"]
        result = rpc(
            "tools/call", {"name": "canvas_get_course", "arguments": {"course_id": "../../secrets"}}
        )
        assert result["isError"]
        result = rpc("tools/call", {"name": "canvas_delete_course", "arguments": {}})
        assert result["isError"]
        assert client.get("/login").status_code == 400


def test_no_mutating_or_unrestricted_tools():
    tools = catalog()
    assert all(t.annotations.readOnlyHint and not t.annotations.destructiveHint for t in tools)
    assert not any(t.name in {"canvas_api_get", "canvas_download_file"} for t in tools)
