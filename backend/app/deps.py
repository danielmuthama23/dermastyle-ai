"""Process-wide singletons, overridable in tests via app.dependency_overrides."""

from __future__ import annotations

from functools import lru_cache

from fastapi import Depends, HTTPException

from .agent.workflow import Session, SessionStore
from .catalog.repository import Catalog, get_catalog as _get_catalog
from .config import Settings, get_settings
from .jobs import JobRunner
from .youcam import YouCamClient


@lru_cache
def get_store() -> SessionStore:
    return SessionStore()


@lru_cache
def get_jobs() -> JobRunner:
    return JobRunner()


@lru_cache
def _client(settings_key: str) -> YouCamClient:  # keyed so tests can reset
    return YouCamClient(get_settings())


def get_youcam() -> YouCamClient:
    return _client(get_settings().youcam_base_url)


def get_catalog() -> Catalog:
    return _get_catalog(get_settings().catalog_path)


def get_session(
    session_id: str, store: SessionStore = Depends(get_store)
) -> Session:
    s = store.get(session_id)
    if s is None:
        raise HTTPException(404, "Session not found or expired. Start a new one.")
    return s


SettingsDep = Depends(get_settings)
__all__ = ["Settings", "get_settings"]
