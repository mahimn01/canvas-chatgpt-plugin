"""Hosted Streamable HTTP MCP and explicit browser account linking."""

import html
import secrets
from contextlib import asynccontextmanager
from urllib.parse import urlsplit

from mcp.server.auth.middleware.auth_context import AuthContextMiddleware, get_access_token
from mcp.server.auth.middleware.bearer_auth import BearerAuthBackend, RequireAuthMiddleware
from mcp.server.auth.routes import create_protected_resource_routes
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.middleware.authentication import AuthenticationMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse, RedirectResponse
from starlette.routing import Route

from .auth import IdentityProvider
from .canvas import CanvasClient
from .config import Settings
from .connections import Connections
from .network import Network, ServiceError
from .server import create_server
from .store import Store

COOKIE = "__Host-canvas-session"
BINDING = "__Host-canvas-login"


def page(title, body, status=200):
    return HTMLResponse(
        "<!doctype html><html lang=en><meta charset=utf-8>"
        "<meta name=viewport content='width=device-width,initial-scale=1'>"
        f"<title>{html.escape(title)}</title><main><h1>{html.escape(title)}</h1>"
        + body
        + "<p><a href='/'>Home</a> · <a href='/privacy'>Privacy</a> · "
        "<a href='/terms'>Terms</a> · <a href='/support'>Support</a></p></main></html>",
        status_code=status,
    )


def cookie(response, name, value, age=28800):
    response.set_cookie(
        name, value, secure=True, httponly=True, samesite="lax", path="/", max_age=age
    )
    return response


class SecurityHeaders:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def wrapped(message):
            if message["type"] == "http.response.start":
                message.setdefault("headers", []).extend(
                    [
                        (b"cache-control", b"no-store"),
                        (b"referrer-policy", b"no-referrer"),
                        (b"x-content-type-options", b"nosniff"),
                        (
                            b"content-security-policy",
                            b"default-src 'none'; style-src 'none'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'",
                        ),
                        (b"strict-transport-security", b"max-age=31536000"),
                    ]
                )
            await send(message)

        await self.app(scope, receive, wrapped)


def create_app(settings=None, *, network=None, identity=None):
    settings = settings or Settings.from_env()
    network = network or Network()
    production = settings.mode == "production"
    store = Store(settings.database, settings.encryption_key) if production else None
    identity = identity or IdentityProvider(settings, network)
    connections = Connections(settings, store, network) if production else None

    async def client_factory():
        if not production:
            from .demo import DemoClient

            return DemoClient()
        token = get_access_token()
        if not token or not token.subject:
            raise ServiceError("Sign in to connect your Canvas account")
        institution, credential = await connections.credentials(token.subject)
        return CanvasClient(institution, credential, network)

    server = create_server(client_factory, personal=not production)
    host = urlsplit(settings.public_url).netloc
    manager = StreamableHTTPSessionManager(
        server,
        stateless=True,
        json_response=True,
        max_request_body_size=65536,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[host],
            allowed_origins=[settings.public_url],
        ),
    )

    class MCPHandler:
        async def __call__(self, scope, receive, send):
            await manager.handle_request(scope, receive, send)

    mcp_handler = MCPHandler()

    metadata_url = settings.public_url + "/.well-known/oauth-protected-resource/mcp"
    handler = (
        RequireAuthMiddleware(mcp_handler, ["canvas:read"], metadata_url)
        if production
        else mcp_handler
    )

    @asynccontextmanager
    async def lifespan(app):
        async with manager.run():
            yield

    def session(request):
        if not production:
            raise ServiceError("Demo mode uses synthetic data and cannot connect a real account")
        value = store.get("session", request.cookies.get(COOKIE, ""))
        if not value:
            raise ServiceError("Sign in at /login to manage your Canvas connection")
        return value

    async def csrf(request):
        saved = session(request)
        if request.headers.get("origin") != settings.public_url:
            raise ServiceError("Invalid form origin")
        if int(request.headers.get("content-length", 0)) > 8192:
            raise ServiceError("Form too large")
        form = await request.form(max_fields=5, max_files=0, max_part_size=8192)
        if not secrets.compare_digest(str(form.get("csrf", "")), saved["csrf"]):
            raise ServiceError("Invalid form verification")
        return saved, form

    async def home(request):
        return page(
            "Course Companion for Canvas",
            "<p>By Mahimn Patel. Read your courses, deadlines, "
            "announcements and course materials in ChatGPT.</p><p>Independent software; "
            "not affiliated with Instructure, OpenAI, or a university.</p>"
            + (
                "<p>Deployment candidate: connect only at an institution that has approved this app.</p>"
                "<a href='/account'>Manage your connection</a>"
                if production
                else "<p>DEMO — synthetic example data only. No real accounts are connected.</p>"
            ),
        )

    async def login(request):
        if not production:
            raise ServiceError("Sign-in is disabled in demo mode")
        binding, verifier, nonce = (secrets.token_urlsafe(32) for _ in range(3))
        state = store.issue("login", {"binding": binding, "verifier": verifier, "nonce": nonce})
        return cookie(
            RedirectResponse(await identity.login_url(state, verifier, nonce)),
            BINDING,
            binding,
            600,
        )

    async def login_callback(request):
        if not production:
            raise ServiceError("Sign-in is disabled in demo mode")
        state = request.query_params.get("state", "")
        saved = store.get("login", state, consume=True)
        if not saved or not secrets.compare_digest(
            saved["binding"], request.cookies.get(BINDING, "")
        ):
            raise ServiceError("Login expired or browser verification failed")
        subject = await identity.complete_login(request.query_params.get("code", ""), saved)
        session_id = store.issue(
            "session", {"subject": subject, "csrf": secrets.token_urlsafe(32)}, ttl=28800
        )
        response = cookie(RedirectResponse("/account", status_code=303), COOKIE, session_id)
        response.delete_cookie(BINDING, path="/", secure=True, httponly=True, samesite="lax")
        return response

    async def account(request):
        if not request.cookies.get(COOKIE) and production:
            return RedirectResponse("/login")
        saved = session(request)
        csrf_field = f"<input type=hidden name=csrf value='{html.escape(saved['csrf'])}'>"
        linked = store.get("connection", saved["subject"])
        if linked:
            text = "<p>Canvas is connected. Return to ChatGPT and connect this MCP server using OAuth.</p>"
            text += f"<form action='/disconnect' method=post>{csrf_field}<button>Disconnect and delete stored Canvas credentials</button></form>"
        else:
            options = "".join(
                f"<option value='{html.escape(i.id)}'>{html.escape(i.name)}</option>"
                for i in settings.institutions
            )
            text = (
                "<p>Choose your institution and approve read access on its Canvas sign-in page.</p>"
            )
            text += f"<form action='/canvas/connect' method=post>{csrf_field}<label>Institution <select name=institution>{options}</select></label><button>Connect Canvas</button></form>"
        return page(
            "Your connection",
            text
            + f"<form action='/logout' method=post>{csrf_field}<button>Sign out</button></form>",
        )

    async def canvas_connect(request):
        saved, form = await csrf(request)
        institution = connections.institution(str(form.get("institution", "")))
        if store.get("connection", saved["subject"]):
            raise ServiceError("Disconnect the existing account first")
        state = store.issue(
            "canvas",
            {
                "session": request.cookies[COOKIE],
                "subject": saved["subject"],
                "institution": institution.id,
            },
        )
        return RedirectResponse(
            connections.authorization_url(institution.id, state), status_code=303
        )

    async def canvas_callback(request):
        current = session(request)
        saved = store.get("canvas", request.query_params.get("state", ""), consume=True)
        if (
            not saved
            or saved["subject"] != current["subject"]
            or not secrets.compare_digest(saved["session"], request.cookies.get(COOKIE, ""))
        ):
            raise ServiceError("Canvas login expired or browser verification failed")
        await connections.complete(
            saved["subject"], saved["institution"], request.query_params.get("code", "")
        )
        return RedirectResponse("/account", status_code=303)

    async def disconnect(request):
        saved, _ = await csrf(request)
        revoked = await connections.disconnect(saved["subject"])
        message = "<p>Stored Canvas credentials have been deleted.</p>"
        if not revoked:
            message += "<p>Canvas could not confirm revocation. Remove this integration in Canvas Account Settings too.</p>"
        return page("Disconnected", message)

    async def logout(request):
        await csrf(request)
        store.delete("session", request.cookies.get(COOKIE, ""))
        response = RedirectResponse("/", status_code=303)
        response.delete_cookie(COOKIE, path="/", secure=True, httponly=True, samesite="lax")
        return response

    async def privacy(request):
        return page(
            "Privacy",
            "<p>Publisher: Mahimn Patel. This software retrieves Canvas content only "
            "when you request it. Retrieved content is sent to your MCP client, including ChatGPT, "
            "and is subject to that client's data settings. No course content or grades are stored "
            "in this application's database.</p><p>Hosted mode stores encrypted Canvas access and refresh "
            "tokens associated with an identity-provider subject. Login state expires after ten minutes; "
            "web sessions expire after eight hours. Expired records are removed on database access. "
            "Disconnect deletes the active stored Canvas credentials and attempts Canvas revocation. "
            "Identity-provider accounts, ChatGPT conversations and infrastructure backups are separate. "
            "Contact the deployment operator for their retention and deletion rules.</p>"
            "<p>No advertising or analytics trackers are included. File extraction uses a short-lived "
            "local process. Server access logs must be disabled or redact callback query strings. "
            "A hosted release must name its actual hosting and identity providers and backup retention "
            "before public submission; this is a development policy.</p>",
        )

    async def terms(request):
        return page(
            "Development terms",
            "<p>Independent experimental software provided under the MIT license. "
            "Use only accounts and materials you are authorized to access. Respect your institution's "
            "assessment and API rules. Verify deadlines and grades in Canvas. This application cannot "
            "submit work, send messages, change grades or provide access to locked materials. "
            "A production deployment needs published operator terms before directory submission.</p>",
        )

    async def support(request):
        return page(
            "Support",
            "<p><a href='https://github.com/mahimn01/canvas-chatgpt-plugin/issues'>"
            "Report a non-sensitive issue on GitHub</a>. Do not include tokens, grades or private course "
            "content. Use GitHub private vulnerability reporting for security reports when enabled.</p>",
        )

    async def health(request):
        return JSONResponse({"status": "ok", "mode": settings.mode})

    async def challenge(request):
        return PlainTextResponse(settings.challenge, status_code=200 if settings.challenge else 404)

    async def error(request, exc):
        return page("Connection error", f"<p>{html.escape(str(exc))}</p>", 400)

    async def unexpected(request, exc):
        return page("Service error", "<p>Request failed safely. Please try again.</p>", 500)

    routes = [
        Route(path, fn, methods=methods)
        for path, fn, methods in [
            ("/", home, ["GET"]),
            ("/login", login, ["GET"]),
            ("/auth/callback", login_callback, ["GET"]),
            ("/account", account, ["GET"]),
            ("/canvas/connect", canvas_connect, ["POST"]),
            ("/canvas/callback", canvas_callback, ["GET"]),
            ("/disconnect", disconnect, ["POST"]),
            ("/logout", logout, ["POST"]),
            ("/privacy", privacy, ["GET"]),
            ("/terms", terms, ["GET"]),
            ("/support", support, ["GET"]),
            ("/healthz", health, ["GET"]),
            ("/.well-known/openai-apps-challenge", challenge, ["GET"]),
        ]
    ]
    if production:
        routes.extend(
            create_protected_resource_routes(
                resource_url=AnyHttpUrl(settings.resource),
                authorization_servers=[AnyHttpUrl(settings.issuer)],
                scopes_supported=["canvas:read"],
            )
        )
    # A callable ASGI object avoids redirects and preserves the canonical OAuth resource.
    routes.append(Route("/mcp", endpoint=handler, methods=["GET", "POST", "DELETE"]))
    middleware = [
        Middleware(SecurityHeaders),
        Middleware(TrustedHostMiddleware, allowed_hosts=[urlsplit(settings.public_url).hostname]),
    ]
    if production:
        middleware.extend(
            [
                Middleware(
                    AuthenticationMiddleware,
                    backend=BearerAuthBackend(
                        identity, resource_server_url=AnyHttpUrl(settings.resource)
                    ),
                ),
                Middleware(AuthContextMiddleware),
            ]
        )
    app = Starlette(
        routes=routes,
        middleware=middleware,
        lifespan=lifespan,
        exception_handlers={ServiceError: error, Exception: unexpected},
    )
    app.state.store, app.state.connections = store, connections
    return app
