"""`job_run` bookkeeping. Status rows are committed in their own session so a failed job still
leaves a FAILED record behind."""

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import sessionmaker

from app.models import JobRun


@dataclass
class JobProgress:
    rows_written: int = 0


@contextmanager
def track_job(
    sessions: sessionmaker, job: str, params: dict[str, Any] | None = None
) -> Iterator[JobProgress]:
    with sessions() as s:
        run = JobRun(job=job, params=params, status="RUNNING", started_at=datetime.now(UTC))
        s.add(run)
        s.commit()
        run_id = run.id
    progress = JobProgress()
    try:
        yield progress
    except BaseException as exc:
        _finish(sessions, run_id, "FAILED", progress, repr(exc))
        raise
    _finish(sessions, run_id, "SUCCEEDED", progress, None)


def _finish(
    sessions: sessionmaker, run_id: uuid.UUID, status: str, progress: JobProgress, error: str | None
) -> None:
    with sessions() as s:
        run = s.get_one(JobRun, run_id)
        run.status = status
        run.finished_at = datetime.now(UTC)
        run.rows_written = progress.rows_written
        run.error = error
        s.commit()
