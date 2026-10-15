import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class InstrumentRow(BaseModel):
    """One grid row, from the last stored daily close (`as_of`)."""

    instrument_id: uuid.UUID
    ticker: str
    name: str | None
    sic_description: str | None
    last_price: float | None
    as_of: date | None
    ret_1d: float | None
    ret_1m: float | None
    ret_ytd: float | None
    market_cap: float | None
    annotation_count: int


class Metadata(BaseModel):
    """One version of a stock's identifiers and details."""

    model_config = ConfigDict(from_attributes=True)

    instrument_id: uuid.UUID
    ticker: str | None
    figi: str | None
    name: str
    sic_code: str | None
    sic_description: str | None
    primary_exchange: str | None
    currency: str
    shares_outstanding: int | None
    listing_status: str
    description: str | None
    homepage_url: str | None
    total_employees: int | None
    list_date: date | None
    hq_city: str | None
    hq_state: str | None
    data_version: datetime


class PricePoint(BaseModel):
    date: date
    value: float


class PriceSeries(BaseModel):
    ticker: str
    mode: Literal["price", "daily", "cumulative"]
    points: list[PricePoint]


class AnnotationIn(BaseModel):
    body: str = Field(min_length=1)
    annotation_date: date | None = (
        None  # optional: the day the annotation is about, e.g. an earnings date
    )


class AnnotationUpdate(BaseModel):
    """Fields left out are unchanged; send `annotation_date: null` to clear the date."""

    body: str | None = Field(default=None, min_length=1)
    annotation_date: date | None = None


class AnnotationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    author: str
    body: str
    annotation_date: date | None
    created_at: datetime
    edited_at: datetime | None
    can_edit: bool  # whether the current user wrote it, and so may edit or delete it


class BasketIn(BaseModel):
    name: str = Field(min_length=1)


class MemberIn(BaseModel):
    ticker: str
    target_quantity: Decimal | None = None


class MemberOut(BaseModel):
    ticker: str | None  # None if the stock no longer has a ticker
    instrument_id: uuid.UUID
    target_quantity: Decimal | None
    added_by: str
    added_at: datetime


class BasketOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    created_by: str
    created_at: datetime


class BasketDetail(BasketOut):
    members: list[MemberOut]


class PortfolioPoint(BaseModel):
    date: date
    value: float
    daily_return: float | None
    cumulative_return: float


class JobOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    job: str
    status: str
    started_at: datetime
    finished_at: datetime | None
    rows_written: int | None
    error: str | None
