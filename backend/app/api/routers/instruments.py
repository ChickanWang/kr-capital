"""Instrument endpoints. URLs name stocks by their current ticker (`/instruments/AAPL`); the
`InstrumentDep` dependency resolves it to the instrument's UUID or returns 404."""

import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Any

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select, text

from app.analytics.returns import Mode, transform
from app.api.deps import AsOfDep, InstrumentDep, SessionDep, UserDep, gap_filler
from app.api.schemas import (
    AnnotationIn,
    AnnotationOut,
    AnnotationUpdate,
    InstrumentRow,
    Metadata,
    PricePoint,
    PriceSeries,
)
from app.config import settings
from app.models import Annotation, InstrumentMetadata
from app.services.prices import GapFiller, current_closes, history_start
from app.services.versioning import current_version, version_as_of

router = APIRouter(prefix="/instruments", tags=["instruments"])


@router.get("", response_model=list[InstrumentRow])
def list_instruments(session: SessionDep) -> list[InstrumentRow]:
    """The grid: one row per stock from the `instrument_snapshot` view."""
    rows = session.execute(text("SELECT * FROM instrument_snapshot ORDER BY ticker")).mappings()
    annotation_counts = dict(
        session.execute(
            select(Annotation.instrument_id, func.count()).group_by(Annotation.instrument_id)
        ).all()
    )
    return [
        InstrumentRow(
            instrument_id=r["instrument_id"],
            ticker=r["ticker"],
            name=r["name"],
            sic_description=r["sic_description"],
            last_price=_f(r["last_close"]),
            as_of=r["last_trade_date"],
            ret_1d=_f(r["ret_1d"]),
            ret_1m=_f(r["ret_1m"]),
            ret_ytd=_f(r["ret_ytd"]),
            market_cap=_f(r["market_cap"]),
            annotation_count=annotation_counts.get(r["instrument_id"], 0),
        )
        for r in rows
    ]


def _f(value: Any) -> float | None:
    return None if value is None else float(value)


@router.get("/{ticker}", response_model=Metadata)
def get_instrument(instrument_id: InstrumentDep, session: SessionDep) -> Metadata:
    """Current identifiers and details ("as is")."""
    return Metadata.model_validate(current_version(session, instrument_id))


@router.get("/{ticker}/versions", response_model=list[Metadata])
def get_versions(
    instrument_id: InstrumentDep, session: SessionDep, as_of: AsOfDep
) -> list[Metadata]:
    """Every version, oldest first. With `as_of` (a date or timestamp), only the version that was
    current then ("as was")."""
    if as_of is not None:
        version = version_as_of(session, instrument_id, as_of)
        return [Metadata.model_validate(version)] if version else []
    versions = session.scalars(
        select(InstrumentMetadata)
        .where(InstrumentMetadata.instrument_id == instrument_id)
        .order_by(InstrumentMetadata.data_version)
    )
    return [Metadata.model_validate(v) for v in versions]


@router.get("/{ticker}/prices", response_model=PriceSeries)
def get_prices(
    ticker: str,
    instrument_id: InstrumentDep,
    session: SessionDep,
    filler: Annotated[GapFiller, Depends(gap_filler)],
    start: date | None = None,
    end: date | None = None,
    mode: Annotated[Mode, Query()] = "price",
    as_of: AsOfDep = None,
) -> PriceSeries:
    """Split-adjusted daily closes (or daily / cumulative price returns). Missing trading days
    are fetched from Polygon and stored before reading; the response always comes from the
    database. With `as_of`, prices are read as they were stored then (e.g. before a split was
    applied) and nothing new is fetched."""
    end = end or date.today()
    start = start or end - timedelta(days=365)
    if start > end:
        raise HTTPException(422, "start must be on or before end")

    ticker = ticker.upper()
    if as_of is None:
        filler.fill(
            session,
            instrument_id,
            ticker,
            start,
            end,
            datetime.now(UTC),
            earliest=history_start(date.today(), settings.history_years),
        )
    rows = current_closes(session, [instrument_id], start, end, as_of)
    closes = pd.Series([c for _, _, c in rows], index=[d for _, d, _ in rows], dtype=object)
    series = transform(closes, mode) if len(closes) else closes
    return PriceSeries(
        ticker=ticker,
        mode=mode,
        points=[PricePoint(date=d, value=float(v)) for d, v in series.items()],
    )


def _annotation_out(annotation: Annotation, user: str) -> AnnotationOut:
    return AnnotationOut(
        id=annotation.id,
        author=annotation.author,
        body=annotation.body,
        annotation_date=annotation.annotation_date,
        created_at=annotation.created_at,
        edited_at=annotation.edited_at,
        can_edit=annotation.author == user,
    )


def _own_annotation(
    session: SessionDep, instrument_id: uuid.UUID, annotation_id: uuid.UUID, user: str
) -> Annotation:
    annotation = session.get(Annotation, annotation_id)
    if annotation is None or annotation.instrument_id != instrument_id:
        raise HTTPException(404, "annotation not found")
    if annotation.author != user:
        raise HTTPException(403, "you can only change your own annotations")
    return annotation


@router.get("/{ticker}/annotations", response_model=list[AnnotationOut])
def list_annotations(
    instrument_id: InstrumentDep, session: SessionDep, user: UserDep
) -> list[AnnotationOut]:
    annotations = session.scalars(
        select(Annotation)
        .where(Annotation.instrument_id == instrument_id)
        .order_by(Annotation.created_at.desc())
    )
    return [_annotation_out(n, user) for n in annotations]


@router.post("/{ticker}/annotations", response_model=AnnotationOut, status_code=201)
def add_annotation(
    instrument_id: InstrumentDep, annotation: AnnotationIn, session: SessionDep, user: UserDep
) -> AnnotationOut:
    row = Annotation(
        instrument_id=instrument_id,
        author=user,
        body=annotation.body,
        annotation_date=annotation.annotation_date,
    )
    session.add(row)
    session.commit()
    return _annotation_out(row, user)


@router.patch("/{ticker}/annotations/{annotation_id}", response_model=AnnotationOut)
def edit_annotation(
    instrument_id: InstrumentDep,
    annotation_id: uuid.UUID,
    update: AnnotationUpdate,
    session: SessionDep,
    user: UserDep,
) -> AnnotationOut:
    """Edit your own annotation; `edited_at` records when."""
    row = _own_annotation(session, instrument_id, annotation_id, user)
    if update.body is not None:
        row.body = update.body
    if "annotation_date" in update.model_fields_set:
        row.annotation_date = update.annotation_date
    row.edited_at = datetime.now(UTC)
    session.commit()
    return _annotation_out(row, user)


@router.delete("/{ticker}/annotations/{annotation_id}", status_code=204)
def delete_annotation(
    instrument_id: InstrumentDep, annotation_id: uuid.UUID, session: SessionDep, user: UserDep
) -> None:
    """Delete your own annotation."""
    session.delete(_own_annotation(session, instrument_id, annotation_id, user))
    session.commit()
