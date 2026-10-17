"""Async client for the YouCam REST API (https://yce-api-01.makeupar.com).

Flow implemented, per the official docs:

1. POST /s2s/v2.0/file            -> file_id + pre-signed PUT request
2. PUT  <pre-signed url>           -> actually upload the bytes (the File API
                                      call alone does NOT upload anything)
3. POST /s2s/v2.0/task/<feature>   -> task_id
4. GET  /s2s/v2.0/task/<feature>/<task_id> until task_status is success/error

Responses are wrapped as {"status": 200, "data": {...}}; errors look like
{"status": 400, "error": "...", "error_code": "..."}.
"""

from __future__ import annotations

import asyncio
import logging
import random
from collections.abc import Awaitable, Callable
from typing import Any

import httpx

from ..config import Settings
from .errors import YouCamError, YouCamTaskError, YouCamTimeout

log = logging.getLogger("dermastyle.youcam")

# Content types the File API examples use. Only jpg/jpeg/png are supported.
_FILE_API_CONTENT_TYPES = {"image/jpeg": "image/jpg", "image/jpg": "image/jpg", "image/png": "image/png"}
_RETRY_STATUSES = {429, 500, 502, 503, 504}
_TERMINAL_OK = "success"
_TERMINAL_ERR = "error"

Sleep = Callable[[float], Awaitable[None]]


class YouCamClient:
    def __init__(
        self,
        settings: Settings,
        http: httpx.AsyncClient | None = None,
        sleep: Sleep = asyncio.sleep,
    ) -> None:
        self._s = settings
        self._owns_http = http is None
        self._http = http or httpx.AsyncClient(timeout=settings.youcam_timeout_s)
        self._sleep = sleep

    async def aclose(self) -> None:
        if self._owns_http:
            await self._http.aclose()

    # ------------------------------------------------------------------ core
    def _auth(self) -> dict[str, str]:
        if not self._s.youcam_api_key:
            raise YouCamError(
                "YOUCAM_API_KEY is not configured", code="InvalidAccessToken", http_status=401
            )
        return {"Authorization": f"Bearer {self._s.youcam_api_key}"}

    def _url(self, path: str) -> str:
        return f"{self._s.youcam_base_url.rstrip('/')}{path}"

    async def _request(self, method: str, path: str, json: dict | None = None) -> dict[str, Any]:
        """Authenticated JSON request with retry on 429/5xx/transport errors."""
        last: YouCamError | None = None
        for attempt in range(self._s.youcam_max_retries + 1):
            try:
                resp = await self._http.request(
                    method, self._url(path), json=json, headers=self._auth()
                )
            except httpx.TransportError as exc:
                last = YouCamError(f"network error: {exc}", retryable=True)
            else:
                body = self._parse_body(resp)
                body_status = body.get("status", resp.status_code)
                if resp.status_code < 400 and body_status < 400:
                    return body
                last = YouCamError(
                    str(body.get("error") or f"HTTP {resp.status_code}"),
                    code=body.get("error_code"),
                    http_status=resp.status_code if resp.status_code >= 400 else body_status,
                    retryable=resp.status_code in _RETRY_STATUSES,
                )
                # Credits / auth / validation problems will not fix themselves.
                if not last.retryable:
                    raise last
            if attempt < self._s.youcam_max_retries:
                delay = self._s.youcam_retry_base_s * (2**attempt) * (0.75 + random.random() / 2)
                log.warning("YouCam %s %s failed (%s); retry in %.1fs", method, path, last, delay)
                await self._sleep(delay)
        assert last is not None
        raise last

    @staticmethod
    def _parse_body(resp: httpx.Response) -> dict[str, Any]:
        try:
            body = resp.json()
        except ValueError:
            return {"status": resp.status_code, "error": resp.text[:200]}
        return body if isinstance(body, dict) else {"status": resp.status_code, "data": body}

    # ----------------------------------------------------------------- files
    async def upload_image(self, data: bytes, file_name: str, content_type: str) -> str:
        """Register + upload an image. Returns the file_id for task creation."""
        ct = _FILE_API_CONTENT_TYPES.get(content_type.lower())
        if ct is None:
            raise YouCamError(f"unsupported content type {content_type}", code="invalid_parameter")
        body = await self._request(
            "POST",
            "/s2s/v2.0/file",
            json={"files": [{"content_type": ct, "file_name": file_name, "file_size": len(data)}]},
        )
        try:
            entry = body["data"]["files"][0]
            file_id: str = entry["file_id"]
            put = entry["requests"][0]
        except (KeyError, IndexError, TypeError) as exc:
            raise YouCamError("unexpected File API response shape") from exc

        # The pre-signed URL is on S3: no Authorization header, use the
        # headers the API told us to send, verbatim.
        headers = dict(put.get("headers") or {})
        for attempt in range(self._s.youcam_max_retries + 1):
            try:
                resp = await self._http.put(put["url"], content=data, headers=headers)
                if resp.status_code < 300:
                    return file_id
                if resp.status_code not in _RETRY_STATUSES:
                    raise YouCamError(
                        f"upload rejected (HTTP {resp.status_code})", http_status=resp.status_code
                    )
            except httpx.TransportError as exc:
                log.warning("upload transport error: %s", exc)
            if attempt < self._s.youcam_max_retries:
                await self._sleep(self._s.youcam_retry_base_s * (2**attempt))
        raise YouCamError("upload to pre-signed URL failed", retryable=True)

    # ----------------------------------------------------------------- tasks
    async def create_task(self, feature: str, payload: dict[str, Any]) -> str:
        body = await self._request("POST", f"/s2s/v2.0/task/{feature}", json=payload)
        try:
            return body["data"]["task_id"]
        except (KeyError, TypeError) as exc:
            raise YouCamError("task creation response had no task_id") from exc

    async def poll_task(self, feature: str, task_id: str) -> dict[str, Any]:
        """Poll until success; returns the `data` object. Raises on error/timeout."""
        waited = 0.0
        delay = self._s.youcam_poll_initial_s
        while True:
            body = await self._request("GET", f"/s2s/v2.0/task/{feature}/{task_id}")
            data = body.get("data") or {}
            status = data.get("task_status")
            if status == _TERMINAL_OK:
                return data
            if status == _TERMINAL_ERR:
                code = _extract_error_code(data)
                raise YouCamTaskError(
                    f"task failed: {code or data.get('error')}", code=code
                )
            if waited >= self._s.youcam_poll_deadline_s:
                raise YouCamTimeout(task_id, waited)
            await self._sleep(delay)
            waited += delay
            delay = min(delay * 1.5, self._s.youcam_poll_max_s)

    async def run_task(self, feature: str, payload: dict[str, Any]) -> dict[str, Any]:
        task_id = await self.create_task(feature, payload)
        log.info("YouCam task %s created (%s)", task_id, feature)
        return await self.poll_task(feature, task_id)


def _extract_error_code(data: dict[str, Any]) -> str | None:
    """The status payload's `error` may be a string code or an object."""
    err = data.get("error")
    if isinstance(err, str):
        return err
    if isinstance(err, dict):
        return err.get("error_code") or err.get("code") or err.get("message")
    return data.get("error_code") or data.get("error_message")
