from fastapi import APIRouter
from sqlalchemy import select, text

from app.api.deps import SessionDep
from app.api.schemas import JobOut
from app.models import JobRun

router = APIRouter(tags=["ops"])


@router.get("/health")
def health(session: SessionDep) -> dict[str, str]:
    session.execute(text("SELECT 1"))
    return {"status": "ok"}


@router.get("/jobs", response_model=list[JobOut])
def recent_jobs(session: SessionDep, limit: int = 20) -> list[JobOut]:
    runs = session.scalars(select(JobRun).order_by(JobRun.started_at.desc()).limit(limit))
    return [JobOut.model_validate(r) for r in runs]
