"""Use an established OIDC provider for ChatGPT OAuth and web sign-in."""

import asyncio
import base64
import hashlib
import secrets
import time
from urllib.parse import urlencode

import jwt
from mcp.server.auth.provider import AccessToken, TokenVerifier

from .network import ServiceError, validate_url


def pkce(verifier):
    return (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    )


class IdentityProvider(TokenVerifier):
    def __init__(self, settings, network):
        self.settings, self.network = settings, network
        self._metadata = None
        self._keys, self._keys_at = {}, 0
        self._key_lock = asyncio.Lock()

    async def metadata(self):
        if self._metadata is None:
            metadata, _ = await self.network.json(
                "GET", self.settings.issuer.rstrip("/") + "/.well-known/openid-configuration"
            )
            if metadata.get("issuer") != self.settings.issuer:
                raise ServiceError("Identity-provider issuer mismatch")
            for field in (
                "authorization_endpoint",
                "token_endpoint",
                "jwks_uri",
                "userinfo_endpoint",
            ):
                validate_url(metadata[field])
            if "S256" not in metadata.get("code_challenge_methods_supported", []):
                raise ServiceError("Identity provider must advertise PKCE S256")
            if not {"openid", "email"}.issubset(metadata.get("scopes_supported", [])):
                raise ServiceError("Identity provider must support openid and email scopes")
            self._metadata = metadata
        return self._metadata

    async def decode(self, token, audience, *, nonce=None):
        try:
            header = jwt.get_unverified_header(token)
            if header.get("alg") != "RS256" or not isinstance(header.get("kid"), str):
                raise ValueError()
            async with self._key_lock:
                age = time.time() - self._keys_at
                if age > 300 or (header["kid"] not in self._keys and age > 5):
                    metadata = await self.metadata()
                    keys, _ = await self.network.json("GET", metadata["jwks_uri"])
                    self._keys = {
                        k["kid"]: jwt.PyJWK.from_dict(k).key
                        for k in keys["keys"]
                        if k.get("kty") == "RSA"
                        and k.get("use", "sig") == "sig"
                        and k.get("alg", "RS256") == "RS256"
                    }
                    self._keys_at = time.time()
            payload = jwt.decode(
                token,
                self._keys[header["kid"]],
                algorithms=["RS256"],
                issuer=self.settings.issuer,
                audience=audience,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            if not isinstance(payload["sub"], str) or not payload["sub"]:
                raise ValueError()
            if nonce is not None:
                if not secrets.compare_digest(payload.get("nonce", ""), nonce):
                    raise ValueError()
                aud = payload["aud"]
                if (isinstance(aud, list) and len(aud) > 1) or "azp" in payload:
                    if payload.get("azp") != audience:
                        raise ValueError()
            return payload
        except (jwt.PyJWTError, KeyError, ValueError, TypeError):
            raise ServiceError("Invalid or expired authentication token") from None

    async def verify_token(self, token):
        try:
            claims = await self.decode(token, self.settings.resource)
            scopes = claims.get("scope", "").split()
            if "canvas:read" not in scopes:
                return None
            return AccessToken(
                token=token,
                client_id=claims.get("azp", "oidc-client"),
                scopes=scopes,
                expires_at=claims["exp"],
                resource=self.settings.resource,
                subject=claims["sub"],
            )
        except (ServiceError, AttributeError):
            return None

    async def login_url(self, state, verifier, nonce):
        metadata = await self.metadata()
        return (
            metadata["authorization_endpoint"]
            + "?"
            + urlencode(
                {
                    "client_id": self.settings.oidc_client_id,
                    "response_type": "code",
                    "redirect_uri": self.settings.public_url + "/auth/callback",
                    "scope": "openid email",
                    "state": state,
                    "nonce": nonce,
                    "code_challenge": pkce(verifier),
                    "code_challenge_method": "S256",
                }
            )
        )

    async def complete_login(self, code, saved):
        metadata = await self.metadata()
        tokens, _ = await self.network.json(
            "POST",
            metadata["token_endpoint"],
            data={
                "grant_type": "authorization_code",
                "code": code,
                "client_id": self.settings.oidc_client_id,
                "client_secret": self.settings.oidc_client_secret,
                "redirect_uri": self.settings.public_url + "/auth/callback",
                "code_verifier": saved["verifier"],
            },
        )
        claims = await self.decode(
            tokens["id_token"], self.settings.oidc_client_id, nonce=saved["nonce"]
        )
        profile, _ = await self.network.json(
            "GET",
            metadata["userinfo_endpoint"],
            headers={"Authorization": "Bearer " + tokens["access_token"]},
        )
        if (
            profile.get("sub") != claims["sub"]
            or profile.get("email_verified") is not True
            or not isinstance(profile.get("email"), str)
            or "@" not in profile["email"]
        ):
            raise ServiceError("A verified email identity is required")
        # Do not retain the email, ID token or identity-provider access token.
        return claims["sub"]
