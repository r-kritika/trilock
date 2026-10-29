"""One-time liveness challenges, kept in memory.

A challenge is bound to one user, expires after a short time and is consumed by the first authentication
attempt that uses it, pass or fail, so a captured request cannot be replayed with the same challenge.
In-memory means a restart or a second server process forgets them, which only costs a new challenge."""
from __future__ import annotations

import secrets
import threading
import time
from dataclasses import dataclass

from ..biometrics.voice_liveness import new_phrase


@dataclass
class Challenge:
    id: str
    user_id: int
    direction: str
    phrase: list[str]
    expires: float


class ChallengeStore:
    def __init__(self, ttl_seconds: int = 90, max_per_user: int = 20):
        self.ttl, self.max_per_user = ttl_seconds, max_per_user
        self._items: dict[str, Challenge] = {}
        self._lock = threading.Lock()

    def _purge(self) -> None:
        now = time.monotonic()
        for k in [k for k, c in self._items.items() if c.expires < now]:
            del self._items[k]

    def issue(self, user_id: int) -> Challenge:
        with self._lock:
            self._purge()
            mine = sorted((c for c in self._items.values() if c.user_id == user_id), key=lambda c: c.expires)
            for old in mine[: max(0, len(mine) - self.max_per_user + 1)]:
                del self._items[old.id]
            ch = Challenge(secrets.token_urlsafe(16), user_id, secrets.choice(["left", "right"]), new_phrase(),
                           time.monotonic() + self.ttl)
            self._items[ch.id] = ch
            return ch

    def consume(self, challenge_id: str | None, user_id: int) -> Challenge | None:
        """Returns the challenge once, or None if unknown, expired or belonging to someone else."""
        if not challenge_id:
            return None
        with self._lock:
            ch = self._items.pop(challenge_id, None)
        if ch is None or ch.user_id != user_id or ch.expires < time.monotonic():
            return None
        return ch
