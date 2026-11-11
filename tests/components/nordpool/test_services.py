"""Test services in Nord Pool."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

from pynordpool import (
    API,
    NordPoolAuthenticationError,
    NordPoolEmptyResponseError,
    NordPoolError,
)
import pytest
from syrupy.assertion import SnapshotAssertion

from homeassistant.components.nordpool.const import DOMAIN
from homeassistant.components.nordpool.services import (
    ATTR_AREAS,
    ATTR_CONFIG_ENTRY,
    ATTR_CURRENCY,
    ATTR_DURATION_MINUTES,
    ATTR_RESOLUTION,
    SERVICE_GET_CHEAPEST_PERIOD,
    SERVICE_GET_PRICE_INDICES_FOR_DATE,
    SERVICE_GET_PRICES_FOR_DATE,
)
from homeassistant.const import ATTR_DATE
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from tests.common import MockConfigEntry, async_load_json_object_fixture
from tests.test_util.aiohttp import AiohttpClientMocker

TEST_SERVICE_DATA = {
    ATTR_CONFIG_ENTRY: "to_replace",
    ATTR_DATE: "2025-10-01",
    ATTR_AREAS: "SE3",
    ATTR_CURRENCY: "EUR",
}
TEST_SERVICE_DATA2 = {
    ATTR_CONFIG_ENTRY: "to_replace",
    ATTR_DATE: "2025-10-01",
    ATTR_AREAS: "se3",
    ATTR_CURRENCY: "eur",
}
TEST_SERVICE_DATA3 = {
    ATTR_CONFIG_ENTRY: "to_replace",
    ATTR_DATE: "2025-10-01",
    ATTR_AREAS: ["SE3", "SE4"],
    ATTR_CURRENCY: "EUR",
}
TEST_SERVICE_DATA_USE_DEFAULTS = {
    ATTR_CONFIG_ENTRY: "to_replace",
    ATTR_DATE: "2025-10-01",
}
TEST_SERVICE_INDICES_DATA_60 = {
    ATTR_CONFIG_ENTRY: "to_replace",
    ATTR_DATE: "2025-10-01",
    ATTR_AREAS: "SE3",
    ATTR_CURRENCY: "SEK",
    ATTR_RESOLUTION: 60,
}
TEST_SERVICE_INDICES_DATA_15 = {
    ATTR_CONFIG_ENTRY: "to_replace",
    ATTR_DATE: "2025-10-01",
    ATTR_AREAS: "SE3",
    ATTR_CURRENCY: "SEK",
    ATTR_RESOLUTION: 15,
}
TEST_SERVICE_CHEAPEST_PERIOD = {
    ATTR_CONFIG_ENTRY: "to_replace",
    ATTR_DATE: "2025-10-01",
    ATTR_AREAS: "SE3",
    ATTR_CURRENCY: "SEK",
    ATTR_DURATION_MINUTES: 60,
}


@pytest.mark.parametrize(
    "test_config",
    [
        (TEST_SERVICE_DATA),
        (TEST_SERVICE_DATA2),
        (TEST_SERVICE_DATA3),
    ],
    ids=[
        "single_area_uppercase_currency_uppercase",
        "single_area_lowercase_currency_lowercase",
        "multiple_areas_uppercase_currency_uppercase",
    ],
)
@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_service_call(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
    snapshot: SnapshotAssertion,
    test_config: dict[str, Any],
) -> None:
    """Test get_prices_for_date service call."""

    service_data = test_config.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_PRICES_FOR_DATE,
        service_data,
        blocking=True,
        return_response=True,
    )

    assert response == snapshot


@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_service_call_use_defaults(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test get_prices_for_date service call using default values."""

    service_data = TEST_SERVICE_DATA_USE_DEFAULTS.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_PRICES_FOR_DATE,
        service_data,
        blocking=True,
        return_response=True,
    )

    assert "SE3" in response


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (NordPoolAuthenticationError, "authentication_error"),
        (NordPoolError, "connection_error"),
        (TimeoutError, "connection_error"),
    ],
)
@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_service_call_failures(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
    error: Exception,
    key: str,
) -> None:
    """Test get_prices_for_date service call when it fails."""
    service_data = TEST_SERVICE_DATA.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id

    with (
        patch(
            "homeassistant.components.nordpool.coordinator.NordPoolClient.async_get_delivery_period",
            side_effect=error,
        ),
        pytest.raises(ServiceValidationError) as err,
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_PRICES_FOR_DATE,
            service_data,
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == key


@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_empty_response_returns_empty_list(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
    snapshot: SnapshotAssertion,
) -> None:
    """Test get_prices_for_date service call return empty list for empty response."""
    service_data = TEST_SERVICE_DATA.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id

    with (
        patch(
            "homeassistant.components.nordpool.coordinator.NordPoolClient.async_get_delivery_period",
            side_effect=NordPoolEmptyResponseError,
        ),
    ):
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_PRICES_FOR_DATE,
            service_data,
            blocking=True,
            return_response=True,
        )

    assert response == snapshot


@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_service_call_config_entry_bad_state(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
) -> None:
    """Test get_prices_for_date service call when config entry bad state."""

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_PRICES_FOR_DATE,
            TEST_SERVICE_DATA,
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "service_config_entry_not_found"

    service_data = TEST_SERVICE_DATA.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id
    await hass.config_entries.async_unload(load_int.entry_id)
    await hass.async_block_till_done()

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_PRICES_FOR_DATE,
            service_data,
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "service_config_entry_not_loaded"


@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_service_call_for_price_indices(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
    snapshot: SnapshotAssertion,
    aioclient_mock: AiohttpClientMocker,
) -> None:
    """Test get_price_indices_for_date service call."""

    fixture_60 = await async_load_json_object_fixture(hass, "indices_60.json", DOMAIN)
    fixture_15 = await async_load_json_object_fixture(hass, "indices_15.json", DOMAIN)

    aioclient_mock.request(
        "GET",
        url=API + "/DayAheadPriceIndices",
        params={
            "date": "2025-10-01",
            "market": "DayAhead",
            "indexNames": "SE3",
            "currency": "SEK",
            "resolutionInMinutes": "60",
        },
        json=fixture_60,
    )

    aioclient_mock.request(
        "GET",
        url=API + "/DayAheadPriceIndices",
        params={
            "date": "2025-10-01",
            "market": "DayAhead",
            "indexNames": "SE3",
            "currency": "SEK",
            "resolutionInMinutes": "15",
        },
        json=fixture_15,
    )

    service_data = TEST_SERVICE_INDICES_DATA_60.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_PRICE_INDICES_FOR_DATE,
        service_data,
        blocking=True,
        return_response=True,
    )

    assert response == snapshot(name="get_price_indices_for_date_60")

    service_data = TEST_SERVICE_INDICES_DATA_15.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id
    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_PRICE_INDICES_FOR_DATE,
        service_data,
        blocking=True,
        return_response=True,
    )

    assert response == snapshot(name="get_price_indices_for_date_15")


@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_get_cheapest_period_ac1(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
) -> None:
    """Test AC1: hourly prices 3, 1, 1, 4 SEK/kWh and a 2 hour duration."""
    prices_per_mwh = [3000, 1000, 1000, 4000]
    entries = [
        SimpleNamespace(
            start=datetime(2025, 10, 1, 17 + index, tzinfo=UTC),
            end=datetime(2025, 10, 1, 18 + index, tzinfo=UTC),
            entry={"SE3": price},
        )
        for index, price in enumerate(prices_per_mwh)
    ]

    service_data = TEST_SERVICE_CHEAPEST_PERIOD.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id
    service_data[ATTR_DURATION_MINUTES] = 120

    with patch(
        "homeassistant.components.nordpool.coordinator.NordPoolClient.async_get_delivery_period",
        return_value=SimpleNamespace(entries=entries),
    ):
        response = await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_CHEAPEST_PERIOD,
            service_data,
            blocking=True,
            return_response=True,
        )

    assert response["area"] == "SE3"
    assert response["start"] == "2025-10-01T18:00:00+00:00"
    assert response["end"] == "2025-10-01T20:00:00+00:00"
    assert response["average_price"] == pytest.approx(1.0)
    assert response["unit"] == "SEK/kWh"


@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_get_cheapest_period_service(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    load_json: list[dict[str, Any]],
) -> None:
    """Test cheapest period service returns the expected period."""

    aioclient_mock.request(
        "GET",
        url=API + "/DayAheadPrices",
        params={
            "date": "2025-10-01",
            "market": "DayAhead",
            "deliveryArea": "SE3",
            "currency": "SEK",
        },
        json=load_json[0],
    )

    service_data = TEST_SERVICE_CHEAPEST_PERIOD.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id

    response = await hass.services.async_call(
        DOMAIN,
        SERVICE_GET_CHEAPEST_PERIOD,
        service_data,
        blocking=True,
        return_response=True,
    )

    assert response["area"] == "SE3"
    assert response["unit"] == "SEK/kWh"
    assert response["start"] == "2025-10-01T01:15:00+00:00"
    assert response["end"] == "2025-10-01T02:15:00+00:00"
    assert response["average_price"] == pytest.approx(0.442015)


@pytest.mark.parametrize(
    ("error", "key"),
    [
        (NordPoolAuthenticationError, "authentication_error"),
        (NordPoolError, "connection_error"),
        (TimeoutError, "connection_error"),
        (NordPoolEmptyResponseError, "no_cheapest_period"),
    ],
)
@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_get_cheapest_period_failures(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
    error: type[Exception],
    key: str,
) -> None:
    """Test cheapest period service maps API failures to service errors."""
    service_data = TEST_SERVICE_CHEAPEST_PERIOD.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id

    with (
        patch(
            "homeassistant.components.nordpool.coordinator.NordPoolClient.async_get_delivery_period",
            side_effect=error,
        ),
        pytest.raises(ServiceValidationError) as err,
    ):
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_CHEAPEST_PERIOD,
            service_data,
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == key


@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_get_cheapest_period_duration_too_long(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
    aioclient_mock: AiohttpClientMocker,
    load_json: list[dict[str, Any]],
) -> None:
    """Test a duration longer than the available prices is rejected."""
    aioclient_mock.request(
        "GET",
        url=API + "/DayAheadPrices",
        params={
            "date": "2025-10-01",
            "market": "DayAhead",
            "deliveryArea": "SE3",
            "currency": "SEK",
        },
        json=load_json[0],
    )

    service_data = TEST_SERVICE_CHEAPEST_PERIOD.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id
    service_data[ATTR_DURATION_MINUTES] = 2000

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_CHEAPEST_PERIOD,
            service_data,
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "no_cheapest_period"


@pytest.mark.freeze_time("2025-10-01T18:00:00+00:00")
async def test_get_cheapest_period_requires_single_area(
    hass: HomeAssistant,
    load_int: MockConfigEntry,
) -> None:
    """Test that more than one area is rejected."""
    service_data = TEST_SERVICE_CHEAPEST_PERIOD.copy()
    service_data[ATTR_CONFIG_ENTRY] = load_int.entry_id
    service_data[ATTR_AREAS] = ["SE3", "SE4"]

    with pytest.raises(ServiceValidationError) as err:
        await hass.services.async_call(
            DOMAIN,
            SERVICE_GET_CHEAPEST_PERIOD,
            service_data,
            blocking=True,
            return_response=True,
        )
    assert err.value.translation_key == "single_area_required"
