"""Test the standalone cheapest-period calculator with synthetic prices."""

from datetime import UTC, datetime, timedelta
from math import inf, nan
from zoneinfo import ZoneInfo

import pytest

from homeassistant.components.nordpool.cheapest_period import (
    CheapestPeriod,
    CheapestPeriodError,
    PriceInterval,
    find_cheapest_period,
)

START = datetime(2026, 1, 1, 17, tzinfo=UTC)


def _time(minutes: int) -> datetime:
    """Return a synthetic timestamp relative to the example's start."""
    return START + timedelta(minutes=minutes)


def _interval(start: int, end: int, price: float) -> PriceInterval:
    """Build a synthetic price interval from minute offsets."""
    return PriceInterval(_time(start), _time(end), price)


@pytest.mark.parametrize(
    ("records", "window", "minutes", "expected"),
    [
        pytest.param(
            [(0, 60, 3), (60, 120, 1), (120, 180, 1), (180, 240, 4)],
            (0, 240),
            120,
            (60, 180, 1),
            id="hourly-example",
        ),
        pytest.param(
            [(0, 60, 1), (60, 120, 1), (120, 180, 1)],
            (0, 180),
            120,
            (0, 120, 1),
            id="earliest-tie",
        ),
        pytest.param(
            [(0, 15, 4), (15, 60, 0), (60, 120, 2)],
            (0, 120),
            60,
            (0, 60, 1),
            id="duration-weighted-mixed-lengths",
        ),
        pytest.param(
            [(0, 15, 4), (15, 30, 1), (30, 45, 1), (45, 60, 3)],
            (0, 60),
            30,
            (15, 45, 1),
            id="quarter-hour",
        ),
        pytest.param(
            [(0, 60, -2), (60, 120, -4), (120, 180, 1)],
            (0, 180),
            120,
            (0, 120, -3),
            id="negative-prices",
        ),
        pytest.param(
            [(0, 60, -100), (60, 120, 2), (120, 180, -100)],
            (30, 150),
            60,
            (60, 120, 2),
            id="exclude-partially-contained",
        ),
        pytest.param(
            [(-60, 0, -100), (0, 60, 2), (60, 120, -100)],
            (0, 60),
            60,
            (0, 60, 2),
            id="exclude-outside-window",
        ),
        pytest.param(
            [(0, 60, -10), (120, 180, 2), (180, 240, 4)],
            (0, 240),
            120,
            (120, 240, 3),
            id="valid-run-after-gap",
        ),
        pytest.param(
            [(120, 180, 1), (60, 120, 1), (0, 60, 1)],
            (0, 180),
            120,
            (0, 120, 1),
            id="unsorted-earliest-tie",
        ),
        pytest.param(
            [(0, 60, 1), (60, 120, 0), (120, 180, 3)],
            (0, 180),
            120,
            (0, 120, 0.5),
            id="overlapping-candidates",
        ),
    ],
)
def test_cheapest_period(
    records: list[tuple[int, int, float]],
    window: tuple[int, int],
    minutes: int,
    expected: tuple[int, int, float],
) -> None:
    """Find the cheapest complete continuous run without changing the inputs."""
    intervals = tuple(_interval(*record) for record in records)
    original = tuple(intervals)
    result = find_cheapest_period(
        intervals, _time(window[0]), _time(window[1]), timedelta(minutes=minutes)
    )
    assert result.start == _time(expected[0])
    assert result.end == _time(expected[1])
    assert result.average_price == pytest.approx(expected[2])
    assert intervals == original


@pytest.mark.parametrize(
    ("intervals", "window_start", "window_end", "duration", "message"),
    [
        pytest.param(
            [], START, _time(120), timedelta(hours=1), "No continuous", id="empty"
        ),
        pytest.param(
            [_interval(0, 60, 1), _interval(120, 180, 1)],
            START,
            _time(180),
            timedelta(hours=2),
            "No continuous",
            id="gap",
        ),
        pytest.param(
            [_interval(0, 60, 1)],
            START,
            _time(120),
            timedelta(minutes=30),
            "No continuous",
            id="cannot-split",
        ),
        pytest.param(
            [_interval(0, 60, 1), _interval(60, 120, 1)],
            START,
            _time(120),
            timedelta(minutes=90),
            "No continuous",
            id="cannot-round",
        ),
        pytest.param(
            [_interval(0, 60, 1)],
            _time(15),
            _time(60),
            timedelta(minutes=45),
            "No continuous",
            id="no-clipping",
        ),
        pytest.param(
            [_interval(0, 60, 1), _interval(30, 90, 2)],
            START,
            _time(120),
            timedelta(hours=1),
            "overlap",
            id="overlap",
        ),
        pytest.param(
            [_interval(0, 60, 1), _interval(0, 60, 1)],
            START,
            _time(120),
            timedelta(hours=1),
            "overlap",
            id="duplicate",
        ),
        pytest.param(
            [_interval(-120, -30, 1), _interval(-60, 0, 2), _interval(0, 60, 1)],
            START,
            _time(120),
            timedelta(hours=1),
            "overlap",
            id="invalid-outside-window",
        ),
        pytest.param(
            [_interval(60, 0, 1)],
            START,
            _time(120),
            timedelta(hours=1),
            "Interval end",
            id="reversed-record",
        ),
        pytest.param(
            [_interval(0, 0, 1)],
            START,
            _time(120),
            timedelta(hours=1),
            "Interval end",
            id="empty-record",
        ),
        pytest.param(
            [_interval(0, 60, nan)],
            START,
            _time(120),
            timedelta(hours=1),
            "finite numbers",
            id="nan",
        ),
        pytest.param(
            [_interval(0, 60, inf)],
            START,
            _time(120),
            timedelta(hours=1),
            "finite numbers",
            id="infinity",
        ),
        pytest.param(
            [_interval(0, 60, -inf)],
            START,
            _time(120),
            timedelta(hours=1),
            "finite numbers",
            id="negative-infinity",
        ),
        pytest.param(
            [_interval(0, 60, True)],
            START,
            _time(120),
            timedelta(hours=1),
            "finite numbers",
            id="boolean-price",
        ),
        pytest.param(
            [], START, _time(120), timedelta(0), "Duration", id="zero-duration"
        ),
        pytest.param(
            [],
            START,
            _time(120),
            timedelta(minutes=-1),
            "Duration",
            id="negative-duration",
        ),
        pytest.param(
            [],
            START,
            _time(120),
            timedelta(hours=3),
            "Duration",
            id="duration-exceeds-window",
        ),
        pytest.param(
            [], START, START, timedelta(hours=1), "Window end", id="empty-window"
        ),
        pytest.param(
            [],
            _time(120),
            START,
            timedelta(hours=1),
            "Window end",
            id="reversed-window",
        ),
        pytest.param(
            [],
            START.replace(tzinfo=None),
            _time(120),
            timedelta(hours=1),
            "timezone-aware",
            id="naive-window-start",
        ),
        pytest.param(
            [],
            START,
            _time(120).replace(tzinfo=None),
            timedelta(hours=1),
            "timezone-aware",
            id="naive-window-end",
        ),
        pytest.param(
            [PriceInterval(START.replace(tzinfo=None), _time(60), 1)],
            START,
            _time(120),
            timedelta(hours=1),
            "timezone-aware",
            id="naive-record-start",
        ),
        pytest.param(
            [PriceInterval(START, _time(60).replace(tzinfo=None), 1)],
            START,
            _time(120),
            timedelta(hours=1),
            "timezone-aware",
            id="naive-record-end",
        ),
    ],
)
def test_invalid_or_unavailable_period(
    intervals: list[PriceInterval],
    window_start: datetime,
    window_end: datetime,
    duration: timedelta,
    message: str,
) -> None:
    """Reject malformed requests and unavailable exact-duration runs."""
    with pytest.raises(CheapestPeriodError, match=message):
        find_cheapest_period(intervals, window_start, window_end, duration)


def test_aware_timestamp_arithmetic() -> None:
    """Use elapsed time across a repeated local hour and return UTC boundaries."""
    zone = ZoneInfo("Europe/Stockholm")
    start = datetime(2026, 10, 25, 2, tzinfo=zone, fold=0)
    middle = datetime(2026, 10, 25, 2, tzinfo=zone, fold=1)
    end = datetime(2026, 10, 25, 3, tzinfo=zone)

    result = find_cheapest_period(
        [PriceInterval(start, middle, 1), PriceInterval(middle, end, 3)],
        start,
        end,
        timedelta(hours=2),
    )

    assert result == CheapestPeriod(
        datetime(2026, 10, 25, 0, tzinfo=UTC),
        datetime(2026, 10, 25, 2, tzinfo=UTC),
        2,
    )
    assert result.start.tzinfo is UTC
    assert result.end.tzinfo is UTC
