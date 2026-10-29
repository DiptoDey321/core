"""Calculate cheapest continuous periods from normalized electricity prices."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from math import fsum, isfinite


@dataclass(frozen=True)
class PriceInterval:
    """A complete price interval, with price in currency/kWh."""

    start: datetime
    end: datetime
    price: float


@dataclass(frozen=True)
class CheapestPeriod:
    """A continuous period with UTC boundaries and average price in currency/kWh."""

    start: datetime
    end: datetime
    average_price: float


class CheapestPeriodError(ValueError):
    """Invalid calculation inputs or no complete, continuous period available."""


def _as_utc(value: datetime) -> datetime:
    """Validate and normalize a timezone-aware timestamp."""
    if not isinstance(value, datetime) or value.utcoffset() is None:
        raise CheapestPeriodError("Timestamps must be timezone-aware datetimes")
    return value.astimezone(UTC)


def find_cheapest_period(
    intervals: Sequence[PriceInterval],
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
) -> CheapestPeriod:
    """Find the cheapest exact-duration run using only complete price intervals.

    Input order is irrelevant. All records, including those outside the window,
    must have aware timestamps, positive lengths, finite prices and no overlaps.
    Gaps are allowed, but a candidate cannot cross one. Equal averages select
    the earliest start. Inputs are not modified and results use UTC.

    Raise CheapestPeriodError for invalid inputs or when no run fits exactly.
    """
    window_start = _as_utc(window_start)
    window_end = _as_utc(window_end)
    if window_end <= window_start:
        raise CheapestPeriodError("Window end must be after window start")
    if (
        not isinstance(duration, timedelta)
        or duration <= timedelta(0)
        or duration > window_end - window_start
    ):
        raise CheapestPeriodError("Duration must be positive and fit within the window")

    normalized: list[PriceInterval] = []
    for interval in intervals:
        if not isinstance(interval, PriceInterval):
            raise CheapestPeriodError("Records must be PriceInterval instances")
        start = _as_utc(interval.start)
        end = _as_utc(interval.end)
        if end <= start:
            raise CheapestPeriodError("Interval end must be after interval start")
        if (
            isinstance(interval.price, bool)
            or not isinstance(interval.price, int | float)
            or not isfinite(interval.price)
        ):
            raise CheapestPeriodError("Interval prices must be finite numbers")
        normalized.append(PriceInterval(start, end, interval.price))

    normalized.sort(key=lambda interval: interval.start)
    for previous, current in pairwise(normalized):
        if current.start < previous.end:
            raise CheapestPeriodError("Price intervals must not overlap")

    eligible = [
        interval
        for interval in normalized
        if window_start <= interval.start and interval.end <= window_end
    ]
    best: CheapestPeriod | None = None
    for index, first in enumerate(eligible):
        end = first.start
        weighted_prices: list[float] = []
        for interval in eligible[index:]:
            if interval.start != end or interval.end - first.start > duration:
                break
            end = interval.end
            weighted_prices.append(
                interval.price * ((interval.end - interval.start) / duration)
            )
            if end - first.start == duration:
                average = fsum(weighted_prices)
                if best is None or average < best.average_price:
                    best = CheapestPeriod(first.start, end, average)
                break

    if best is None:
        raise CheapestPeriodError(
            "No continuous period of complete intervals matches the requested duration"
        )
    return best
