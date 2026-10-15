"""Shared API dependencies: database session, current user, ticker lookup, upstream client."""

import uuid
from datetime import UTC, date, datetime, time
from functools import lru_cache
from typing import Annotated
from zoneinfo import ZoneInfo

from fastapi import Depends, Header, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_session
from app.providers.polygon import PolygonClient
from app.services.prices import GapFiller
from app.services.versioning import instrument_for_ticker

SessionDep = Annotated[Session, Depends(get_session)]


def current_user(x_user_id: Annotated[str | None, Header()] = None) -> str:
    """No login yet: a mock user id from the X-User-Id header, else the configured default."""
    return x_user_id or settings.app_user_id


UserDep = Annotated[str, Depends(current_user)]


def resolve_ticker(ticker: str, session: SessionDep) -> uuid.UUID:
    """URLs name stocks by their current ticker; everything internal uses the instrument UUID."""
    instrument_id = instrument_for_ticker(session, ticker.upper())
    if instrument_id is None:
        raise HTTPException(404, f"no instrument with ticker {ticker!r}")
    return instrument_id


InstrumentDep = Annotated[uuid.UUID, Depends(resolve_ticker)]

NEW_YORK = ZoneInfo("America/New_York")


def as_of_cutoff(as_of: str | None = None) -> datetime | None:
    """`as_of` selects which data version to read: the latest version recorded at or before it.
    A plain date (`2026-10-14`) means the end of that day in New York, so it includes that
    evening's nightly run; a full timestamp is used as given (UTC if it has no offset)."""
    if as_of is None:
        return None
    try:
        if len(as_of) == 10:
            return datetime.combine(date.fromisoformat(as_of), time.max, tzinfo=NEW_YORK)
        parsed = datetime.fromisoformat(as_of)
    except ValueError:
        raise HTTPException(422, f"as_of must be a date or ISO timestamp, got {as_of!r}") from None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


AsOfDep = Annotated[datetime | None, Depends(as_of_cutoff)]


@lru_cache(maxsize=1)
def gap_filler() -> GapFiller:
    polygon = PolygonClient(
        settings.polygon_api_key, settings.polygon_base_url, settings.polygon_calls_per_minute
    )
    return GapFiller(polygon, settings.gap_fill_cooldown_seconds)
