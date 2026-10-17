"""Explicit shopping-session state machine.

States only move along allowed edges, so the UI, API and tests share one
definition of "where are we in the journey".
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from ..youcam.skin import SkinReport
from ..youcam.vto import TryOnResult
from .preferences import Preferences


class Stage(str, Enum):
    intake = "intake"
    skin_running = "skin_running"
    skin_done = "skin_done"
    recommended = "recommended"
    tryon_running = "tryon_running"
    planned = "planned"


_EDGES: dict[Stage, set[Stage]] = {
    Stage.intake: {Stage.skin_running, Stage.recommended, Stage.tryon_running, Stage.planned},
    Stage.skin_running: {Stage.skin_done, Stage.intake},
    Stage.skin_done: {Stage.recommended, Stage.skin_running, Stage.intake},
    Stage.recommended: {Stage.tryon_running, Stage.planned, Stage.skin_running, Stage.recommended, Stage.intake},
    Stage.tryon_running: {Stage.recommended, Stage.planned, Stage.intake},
    Stage.planned: {Stage.tryon_running, Stage.recommended, Stage.skin_running, Stage.planned, Stage.intake},
}


class InvalidTransition(RuntimeError):
    pass


class Session(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    created: float = Field(default_factory=time.time)
    stage: Stage = Stage.intake
    prefs: Preferences | None = None
    skin: SkinReport | None = None
    tryons: dict[str, TryOnResult] = Field(default_factory=dict)  # garment key -> result
    consent_face: bool = False
    consent_body: bool = False
    selected_garment: str | None = None
    events: list[dict[str, Any]] = Field(default_factory=list)  # product analytics, no PII

    def go(self, nxt: Stage) -> None:
        if nxt not in _EDGES[self.stage]:
            raise InvalidTransition(f"{self.stage.value} -> {nxt.value} is not allowed")
        self.stage = nxt

    def log(self, name: str, **props: Any) -> None:
        self.events.append({"t": round(time.time(), 2), "name": name, **props})

    def wipe_images_and_results(self) -> None:
        """Consent withdrawal: drop everything derived from the shopper's photos."""
        self.skin = None
        self.tryons.clear()
        self.consent_face = False
        self.consent_body = False
        self.stage = Stage.intake
        self.log("data_deleted")


class SessionStore:
    """In-memory store with TTL. Swap for PostgreSQL behind this same interface."""

    def __init__(self, ttl_s: int = 6 * 3600) -> None:
        self._s: dict[str, Session] = {}
        self._ttl = ttl_s

    def create(self) -> Session:
        self._gc()
        s = Session()
        self._s[s.id] = s
        return s

    def get(self, sid: str) -> Session | None:
        s = self._s.get(sid)
        if s and time.time() - s.created > self._ttl:
            del self._s[sid]
            return None
        return s

    def delete(self, sid: str) -> None:
        self._s.pop(sid, None)

    def _gc(self) -> None:
        now = time.time()
        for k in [k for k, v in self._s.items() if now - v.created > self._ttl]:
            del self._s[k]
