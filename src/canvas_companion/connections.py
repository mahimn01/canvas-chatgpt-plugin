"""Canvas OAuth grants are separate from ChatGPT bearer tokens."""

import asyncio
import hashlib
import time
from urllib.parse import urlencode

from .network import ServiceError
from .scopes import SCOPES


class Connections:
    def __init__(self, settings, store, network):
        self.settings, self.store, self.network = settings, store, network
        # Bounded locks. Run one ASGI worker per SQLite database (documented deployment contract).
        self.locks = [asyncio.Lock() for _ in range(128)]

    def lock(self, subject):
        return self.locks[int(hashlib.sha256(subject.encode()).hexdigest(), 16) % 128]

    def institution(self, identifier):
        for institution in self.settings.institutions:
            if institution.id == identifier:
                return institution
        raise ServiceError("This institution has not been configured")

    def authorization_url(self, institution_id, state):
        institution = self.institution(institution_id)
        return (
            institution.origin
            + "/login/oauth2/auth?"
            + urlencode(
                {
                    "client_id": institution.client_id,
                    "response_type": "code",
                    "state": state,
                    "redirect_uri": self.settings.public_url + "/canvas/callback",
                    "scope": " ".join(SCOPES),
                }
            )
        )

    async def complete(self, subject, institution_id, code):
        institution = self.institution(institution_id)
        async with self.lock(subject):
            # Explicit disconnect first avoids silently orphaning old grants on replacement.
            if self.store.get("connection", subject):
                raise ServiceError(
                    "Disconnect the existing Canvas account before connecting another"
                )
            token, _ = await self.network.json(
                "POST",
                institution.origin + "/login/oauth2/token",
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": institution.client_id,
                    "client_secret": institution.client_secret,
                    "redirect_uri": self.settings.public_url + "/canvas/callback",
                },
            )
            self._save(subject, institution.id, token)

    def _save(self, subject, institution, token, previous=None):
        refresh = token.get("refresh_token") or (previous or {}).get("refresh_token")
        if not token.get("access_token") or not refresh:
            raise ServiceError("Canvas did not issue the required OAuth credentials")
        self.store.put(
            "connection",
            subject,
            {
                "institution": institution,
                "access_token": token["access_token"],
                "refresh_token": refresh,
                "expires_at": time.time() + int(token.get("expires_in", 3600)),
            },
        )

    async def credentials(self, subject):
        async with self.lock(subject):
            stored = self.store.get("connection", subject)
            if not stored:
                raise ServiceError(
                    "Connect your Canvas account at " + self.settings.public_url + "/account"
                )
            institution = self.institution(stored["institution"])
            if stored["expires_at"] <= time.time() + 60:
                fresh, _ = await self.network.json(
                    "POST",
                    institution.origin + "/login/oauth2/token",
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": stored["refresh_token"],
                        "client_id": institution.client_id,
                        "client_secret": institution.client_secret,
                    },
                )
                self._save(subject, institution.id, fresh, stored)
                stored = self.store.get("connection", subject)
            return institution, stored["access_token"]

    async def disconnect(self, subject):
        async with self.lock(subject):
            stored = self.store.get("connection", subject)
            revoked = True
            if stored:
                institution = self.institution(stored["institution"])
                try:
                    status, _, _ = await self.network.request(
                        "DELETE",
                        institution.origin + "/login/oauth2/token",
                        headers={"Authorization": "Bearer " + stored["access_token"]},
                    )
                    revoked = 200 <= status < 300
                except ServiceError:
                    revoked = False
                self.store.delete("connection", subject)
            return revoked
