"""Tiny background-job runner for long YouCam tasks (they can take a minute).

The HTTP request returns a job id immediately; the browser polls /api/jobs/{id}.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any

from pydantic import BaseModel

from .youcam.errors import YouCamError

log = logging.getLogger("dermastyle.jobs")


class JobState(str, Enum):
    running = "running"
    done = "done"
    failed = "failed"


class Job(BaseModel):
    id: str
    kind: str
    state: JobState = JobState.running
    result: Any = None
    error: str | None = None
    error_code: str | None = None
    created: float


class JobRunner:
    def __init__(self, ttl_s: int = 3600) -> None:
        self._jobs: dict[str, Job] = {}
        self._tasks: set[asyncio.Task] = set()
        self._ttl = ttl_s

    def submit(self, kind: str, fn: Callable[[], Awaitable[Any]]) -> Job:
        self._gc()
        job = Job(id=uuid.uuid4().hex, kind=kind, created=time.time())
        self._jobs[job.id] = job

        async def _run() -> None:
            try:
                job.result = await fn()
                job.state = JobState.done
            except YouCamError as exc:
                log.warning("job %s (%s) failed: %s", job.id, kind, exc)
                job.state, job.error, job.error_code = JobState.failed, exc.user_message, exc.code
            except Exception:  # noqa: BLE001 - never leak internals to the browser
                log.exception("job %s (%s) crashed", job.id, kind)
                job.state, job.error = JobState.failed, "Something went wrong. Please try again."

        task = asyncio.create_task(_run())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return job

    def get(self, job_id: str) -> Job | None:
        return self._jobs.get(job_id)

    def _gc(self) -> None:
        now = time.time()
        for k in [k for k, j in self._jobs.items() if now - j.created > self._ttl]:
            del self._jobs[k]
