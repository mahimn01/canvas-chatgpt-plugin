"""Encrypted persistent connections and expiring, one-use OAuth state."""

import hashlib
import json
import os
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from cryptography.fernet import Fernet


class Store:
    def __init__(self, filename: str, key: str):
        path = Path(filename)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.filename = str(path)
        self.cipher = Fernet(key.encode())
        descriptor = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        os.close(descriptor)
        os.chmod(path, 0o600)
        with sqlite3.connect(self.filename) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS records (kind TEXT, id TEXT, value BLOB, "
                "expires REAL, PRIMARY KEY(kind, id))"
            )

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.filename, timeout=15)
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                db.execute("DELETE FROM records WHERE expires > 0 AND expires < ?", (time.time(),))
                yield db
        finally:
            db.close()

    @staticmethod
    def index(identity):
        return hashlib.sha256(identity.encode()).hexdigest()

    def put(self, kind, identity, value, ttl=0):
        encrypted = self.cipher.encrypt(
            json.dumps({"kind": kind, "identity": identity, "value": value}).encode()
        )
        with self.db() as db:
            db.execute(
                "INSERT OR REPLACE INTO records VALUES (?, ?, ?, ?)",
                (kind, self.index(identity), encrypted, time.time() + ttl if ttl else 0),
            )

    def get(self, kind, identity, consume=False):
        with self.db() as db:
            # Serializes readers consuming the same state, including separate processes.
            db.execute("BEGIN IMMEDIATE") if not db.in_transaction else None
            row = db.execute(
                "SELECT value FROM records WHERE kind=? AND id=?", (kind, self.index(identity))
            ).fetchone()
            if not row:
                return None
            if consume:
                db.execute(
                    "DELETE FROM records WHERE kind=? AND id=?", (kind, self.index(identity))
                )
            payload = json.loads(self.cipher.decrypt(row[0]))
            if payload["kind"] != kind or payload["identity"] != identity:
                raise ValueError("Encrypted record binding mismatch")
            return payload["value"]

    def delete(self, kind, identity):
        with self.db() as db:
            db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, self.index(identity)))

    def issue(self, kind, value, ttl=600):
        token = secrets.token_urlsafe(32)
        self.put(kind, token, value, ttl)
        return token
