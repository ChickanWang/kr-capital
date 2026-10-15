import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.models import InstrumentMetadata
from app.services.versioning import (
    FIELDS,
    apply_metadata,
    current_tickers,
    current_version,
    resolve,
    version_as_of,
)
from tests.conftest import reference

T0 = datetime(2026, 1, 5, 22, 0, tzinfo=UTC)
T1 = T0 + timedelta(days=1)
T2 = T0 + timedelta(days=2)


def rows(session, instrument_id=None):
    query = select(InstrumentMetadata).order_by(
        InstrumentMetadata.data_version, InstrumentMetadata.instrument_id
    )
    if instrument_id is not None:
        query = query.where(InstrumentMetadata.instrument_id == instrument_id)
    return list(session.scalars(query))


def changes(session, instrument_id):
    """(field, old, new) for every field that differs between consecutive versions."""
    versions = rows(session, instrument_id)
    return [
        (field, getattr(old, field), getattr(new, field))
        for old, new in zip(versions, versions[1:], strict=False)
        for field in FIELDS
        if getattr(old, field) != getattr(new, field)
    ]


def test_first_fetch_creates_one_row_and_no_changes(session):
    iid = resolve(session, reference(), T0)
    session.commit()

    (row,) = rows(session)
    assert (row.instrument_id, row.ticker, row.figi, row.data_version) == (
        iid,
        "AAPL",
        "BBG000B9XRY4",
        T0,
    )
    assert changes(session, iid) == []


def test_unchanged_record_is_a_no_op(session):
    iid = resolve(session, reference(), T0)
    assert apply_metadata(session, iid, reference(), T1) is False
    session.commit()
    assert len(rows(session)) == 1


def test_changed_record_adds_a_version_with_field_level_changes(session):
    iid = resolve(session, reference(), T0)
    assert apply_metadata(
        session, iid, reference(sic_code="3663", sic_description="RADIO & TV EQUIPMENT"), T1
    )
    session.commit()

    assert set(changes(session, iid)) == {
        ("sic_code", "3571", "3663"),
        ("sic_description", "ELECTRONIC COMPUTERS", "RADIO & TV EQUIPMENT"),
    }
    old, new = rows(session)
    assert (old.data_version, new.data_version) == (T0, T1)
    assert current_version(session, iid).data_version == new.data_version


def test_as_of_returns_the_version_current_at_that_time(session):
    iid = resolve(session, reference(name="Apple Computer"), T0)
    apply_metadata(session, iid, reference(name="Apple Inc."), T1)
    session.commit()

    assert version_as_of(session, iid, T0 + timedelta(hours=1)).name == "Apple Computer"
    assert version_as_of(session, iid, T1).name == "Apple Inc."
    assert version_as_of(session, iid, T2).name == "Apple Inc."
    assert version_as_of(session, iid, T0 - timedelta(seconds=1)) is None


def test_ticker_rename_is_matched_by_figi_and_keeps_the_instrument(session):
    fb = resolve(session, reference(ticker="FB", figi="BBG000MM2P62", name="Meta"), T0)
    meta = resolve(session, reference(ticker="META", figi="BBG000MM2P62", name="Meta"), T1)
    session.commit()

    assert meta == fb
    assert [(r.ticker, r.data_version) for r in rows(session)] == [("FB", T0), ("META", T1)]
    assert current_tickers(session) == {"META": fb}
    assert changes(session, fb) == [("ticker", "FB", "META")]


def test_reused_ticker_is_taken_from_its_previous_holder(session):
    old = resolve(session, reference(ticker="XYZ", figi="FIGI-OLD", name="Old Co"), T0)
    new = resolve(session, reference(ticker="XYZ", figi="FIGI-NEW", name="New Co"), T1)
    session.commit()

    assert new != old
    assert current_tickers(session) == {"XYZ": new}
    assert current_version(session, old).ticker is None  # old holder's latest row has no ticker
    assert changes(session, old) == [("ticker", "XYZ", None)]


def test_database_rejects_two_versions_at_the_same_instant(session):
    iid = resolve(session, reference(), T0)
    session.commit()
    session.add(
        InstrumentMetadata(
            instrument_id=iid,
            ticker="AAPL",
            name="dup",
            currency="USD",
            listing_status="ACTIVE",
            data_version=T0,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()


def test_database_rejects_one_figi_on_two_instruments(session):
    """Versions of one stock share a FIGI; a second instrument claiming it (e.g. two loads racing
    to create the same stock) is rejected."""
    iid = resolve(session, reference(), T0)
    apply_metadata(session, iid, reference(name="Apple Inc. (renamed)"), T1)  # same stock: fine
    session.commit()
    session.add(
        InstrumentMetadata(
            instrument_id=uuid.uuid4(),
            ticker="AAPL",
            figi="BBG000B9XRY4",
            name="duplicate",
            currency="USD",
            listing_status="ACTIVE",
            data_version=T2,
        )
    )
    with pytest.raises(IntegrityError):
        session.commit()
