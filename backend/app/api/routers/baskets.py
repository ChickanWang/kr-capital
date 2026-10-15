import uuid
from datetime import date, timedelta

import pandas as pd
from fastapi import APIRouter, HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from app.analytics.returns import portfolio_values
from app.api.deps import AsOfDep, SessionDep, UserDep
from app.api.schemas import BasketDetail, BasketIn, BasketOut, MemberIn, MemberOut, PortfolioPoint
from app.models import Basket, BasketMember
from app.services.prices import current_closes
from app.services.versioning import current_version, instrument_for_ticker

router = APIRouter(prefix="/baskets", tags=["baskets"])


@router.get("", response_model=list[BasketOut])
def list_baskets(session: SessionDep, user: UserDep) -> list[BasketOut]:
    query = select(Basket).where(Basket.created_by == user).order_by(Basket.name)
    return [BasketOut.model_validate(b) for b in session.scalars(query)]


@router.post("", response_model=BasketOut, status_code=201)
def create_basket(basket: BasketIn, session: SessionDep, user: UserDep) -> BasketOut:
    row = Basket(name=basket.name, created_by=user)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        raise HTTPException(409, f"you already have a basket named {basket.name!r}") from None
    return BasketOut.model_validate(row)


@router.get("/{basket_id}", response_model=BasketDetail)
def get_basket(basket_id: uuid.UUID, session: SessionDep) -> BasketDetail:
    basket = _basket(session, basket_id)
    members = session.scalars(select(BasketMember).where(BasketMember.basket_id == basket_id))
    return BasketDetail(
        **BasketOut.model_validate(basket).model_dump(),
        members=[_member_out(session, m) for m in members],
    )


@router.delete("/{basket_id}", status_code=204)
def delete_basket(basket_id: uuid.UUID, session: SessionDep) -> None:
    session.delete(_basket(session, basket_id))
    session.commit()


@router.post("/{basket_id}/members", response_model=MemberOut, status_code=201)
def add_member(
    basket_id: uuid.UUID, member: MemberIn, session: SessionDep, user: UserDep
) -> MemberOut:
    """Add (or update) a stock. `target_quantity` is optional; give every member one to use the
    basket as a portfolio."""
    _basket(session, basket_id)
    instrument_id = _instrument(session, member.ticker)

    row = session.get(BasketMember, (basket_id, instrument_id))
    if row is None:
        row = BasketMember(basket_id=basket_id, instrument_id=instrument_id, added_by=user)
        session.add(row)
    row.target_quantity = member.target_quantity
    session.commit()
    return _member_out(session, row)


@router.delete("/{basket_id}/members/{ticker}", status_code=204)
def remove_member(basket_id: uuid.UUID, ticker: str, session: SessionDep) -> None:
    _basket(session, basket_id)
    instrument_id = _instrument(session, ticker)
    session.execute(
        delete(BasketMember).where(
            BasketMember.basket_id == basket_id, BasketMember.instrument_id == instrument_id
        )
    )
    session.commit()


@router.get("/{basket_id}/returns", response_model=list[PortfolioPoint])
def portfolio_returns(
    basket_id: uuid.UUID,
    session: SessionDep,
    as_of: AsOfDep,
    start: date | None = None,
    end: date | None = None,
) -> list[PortfolioPoint]:
    """Fixed-quantity portfolio value and price returns over [start, end]. The basket acts as a
    portfolio, so every member needs a target_quantity. With `as_of`, prices are read as they
    were stored then."""
    _basket(session, basket_id)
    end = end or date.today()
    start = start or end - timedelta(days=365)

    members = session.scalars(select(BasketMember).where(BasketMember.basket_id == basket_id)).all()
    quantities = {
        m.instrument_id: m.target_quantity for m in members if m.target_quantity is not None
    }
    if not members or len(quantities) != len(members):
        raise HTTPException(422, "returns need every member to have a target_quantity")
    rows = current_closes(session, list(quantities), start, end, as_of)
    frame = pd.DataFrame(rows, columns=["instrument_id", "trade_date", "close"])
    closes = {
        iid: group.set_index("trade_date")["close"].sort_index()
        for iid, group in frame.groupby("instrument_id")
    }
    if set(closes) != set(quantities):
        return []
    values = portfolio_values(closes, quantities)
    return [
        PortfolioPoint(
            date=d,
            value=row.value,
            daily_return=None if pd.isna(row.daily_return) else row.daily_return,
            cumulative_return=row.cumulative_return,
        )
        for d, row in values.iterrows()
    ]


def _instrument(session: SessionDep, ticker: str) -> uuid.UUID:
    instrument_id = instrument_for_ticker(session, ticker.upper())
    if instrument_id is None:
        raise HTTPException(404, f"no instrument with ticker {ticker!r}")
    return instrument_id


def _member_out(session: SessionDep, member: BasketMember) -> MemberOut:
    current = current_version(session, member.instrument_id)
    return MemberOut(
        ticker=current.ticker if current else None,
        instrument_id=member.instrument_id,
        target_quantity=member.target_quantity,
        added_by=member.added_by,
        added_at=member.added_at,
    )


def _basket(session: SessionDep, basket_id: uuid.UUID) -> Basket:
    basket = session.get(Basket, basket_id)
    if basket is None:
        raise HTTPException(404, f"basket {basket_id} not found")
    return basket
