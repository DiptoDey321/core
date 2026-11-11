"""Services for Nord Pool integration."""

from collections.abc import Callable
from datetime import date, datetime, timedelta
from functools import partial
import logging
from typing import TYPE_CHECKING

import probatio
from pynordpool import (
    AREAS,
    Currency,
    DeliveryPeriodData,
    NordPoolAuthenticationError,
    NordPoolClient,
    NordPoolEmptyResponseError,
    NordPoolError,
    PriceIndicesData,
)

from homeassistant.const import ATTR_DATE
from homeassistant.core import (
    HomeAssistant,
    ServiceCall,
    ServiceResponse,
    SupportsResponse,
    callback,
)
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv, service
from homeassistant.helpers.selector import ConfigEntrySelector
from homeassistant.util import dt as dt_util
from homeassistant.util.json import JsonValueType

if TYPE_CHECKING:
    from . import NordPoolConfigEntry

from .cheapest_period import CheapestPeriodError, PriceInterval, find_cheapest_period
from .const import ATTR_RESOLUTION, DOMAIN

SERVICE_GET_PRICES_FOR_DATE = "get_prices_for_date"
SERVICE_GET_PRICE_INDICES_FOR_DATE = "get_price_indices_for_date"
SERVICE_GET_CHEAPEST_PERIOD = "get_cheapest_period"

ATTR_DURATION_MINUTES = "duration_minutes"


def _validate_areas(areas: list[str]) -> list[str]:
    """Validate the areas."""
    validated_areas: list[str] = []

    for area in areas:
        validated_area = cv.string(area)
        validated_area = validated_area.upper()

        if validated_area not in AREAS:
            raise probatio.Invalid(f"Area {area} is not valid")

        validated_areas.append(validated_area)

    return validated_areas


_LOGGER = logging.getLogger(__name__)

ATTR_CONFIG_ENTRY = "config_entry"
ATTR_AREAS = "areas"
ATTR_CURRENCY = "currency"

SERVICE_GET_PRICES_SCHEMA = probatio.Schema(
    {
        probatio.Required(ATTR_CONFIG_ENTRY): ConfigEntrySelector(
            {"integration": DOMAIN}
        ),
        probatio.Required(ATTR_DATE): cv.date,
        probatio.Optional(ATTR_AREAS, default=[]): probatio.All(
            cv.ensure_list, _validate_areas
        ),
        probatio.Optional(ATTR_CURRENCY): probatio.All(
            cv.string,
            probatio.Upper,
            probatio.In([currency.value for currency in Currency]),
        ),
    }
)

SERVICE_GET_PRICE_INDICES_SCHEMA = SERVICE_GET_PRICES_SCHEMA.extend(
    {
        probatio.Optional(ATTR_RESOLUTION, default=60): probatio.All(
            cv.positive_int,
            probatio.All(probatio.Coerce(int), probatio.In((15, 30, 60))),
        ),
    }
)

SERVICE_GET_CHEAPEST_PERIOD_SCHEMA = SERVICE_GET_PRICES_SCHEMA.extend(
    {
        probatio.Required(ATTR_DURATION_MINUTES): cv.positive_int,
    }
)


@callback
def async_setup_services(hass: HomeAssistant) -> None:
    """Set up services for Nord Pool integration."""

    def get_service_params(
        call: ServiceCall,
    ) -> tuple[NordPoolClient, date, str, list[str], int]:
        """Return the parameters for the service."""

        entry: NordPoolConfigEntry = service.async_get_config_entry(
            hass, DOMAIN, call.data[ATTR_CONFIG_ENTRY]
        )

        client = entry.runtime_data.client
        asked_date: date = call.data[ATTR_DATE]

        areas = call.data.get(ATTR_AREAS)
        areas = areas or entry.data[ATTR_AREAS]

        currency = call.data.get(ATTR_CURRENCY)
        currency = currency or entry.data[ATTR_CURRENCY]

        resolution = call.data.get(ATTR_RESOLUTION)
        resolution = resolution or 60

        return (client, asked_date, currency, areas, resolution)

    async def get_prices_for_date(
        client: NordPoolClient,
        asked_date: date,
        currency: str,
        areas: list[str],
        resolution: int,
    ) -> DeliveryPeriodData:
        """Get prices."""
        return await client.async_get_delivery_period(
            datetime.combine(asked_date, dt_util.utcnow().time()),
            Currency(currency),
            areas,
        )

    async def get_price_indices_for_date(
        client: NordPoolClient,
        asked_date: date,
        currency: str,
        areas: list[str],
        resolution: int,
    ) -> PriceIndicesData:
        """Get price indices."""
        return await client.async_get_price_indices(
            datetime.combine(asked_date, dt_util.utcnow().time()),
            Currency(currency),
            areas,
            resolution=resolution,
        )

    async def get_cheapest_period(
        call: ServiceCall,
    ) -> ServiceResponse:
        """Find the cheapest continuous period for the requested duration."""

        client, asked_date, currency, areas, _ = get_service_params(call)

        duration_minutes = call.data[ATTR_DURATION_MINUTES]

        if len(areas) != 1:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="single_area_required",
            )
        area = areas[0]

        try:
            price_data = await client.async_get_delivery_period(
                datetime.combine(
                    asked_date,
                    dt_util.utcnow().time(),
                ),
                Currency(currency),
                [area],
            )

        except NordPoolAuthenticationError as error:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="authentication_error",
            ) from error

        except NordPoolEmptyResponseError as error:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_cheapest_period",
                translation_placeholders={
                    "error": "no prices are available for the selected date"
                },
            ) from error

        except (NordPoolError, TimeoutError) as error:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="connection_error",
            ) from error
        intervals = [
            PriceInterval(
                start=entry.start,
                end=entry.end,
                price=entry.entry[area] / 1000,
            )
            for entry in price_data.entries
            if entry.entry.get(area) is not None
        ]

        if not intervals:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_cheapest_period",
                translation_placeholders={
                    "error": "no prices are available for the selected area"
                },
            )

        try:
            result = find_cheapest_period(
                intervals,
                min(interval.start for interval in intervals),
                max(interval.end for interval in intervals),
                timedelta(minutes=duration_minutes),
            )

        except CheapestPeriodError as error:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="no_cheapest_period",
                translation_placeholders={"error": str(error)},
            ) from error

        return {
            "area": area,
            "start": result.start.isoformat(),
            "end": result.end.isoformat(),
            "average_price": result.average_price,
            "unit": f"{currency}/kWh",
        }

    async def get_prices(
        func: Callable,
        call: ServiceCall,
    ) -> ServiceResponse:
        """Get price service."""

        client, asked_date, currency, areas, resolution = get_service_params(call)

        try:
            price_data = await func(
                client,
                asked_date,
                currency,
                areas,
                resolution,
            )

        except NordPoolAuthenticationError as error:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="authentication_error",
            ) from error

        except NordPoolEmptyResponseError:
            return {area: [] for area in areas}

        except (NordPoolError, TimeoutError) as error:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="connection_error",
            ) from error

        result: dict[str, JsonValueType] = {}

        for area in areas:
            result[area] = [
                {
                    "start": price_entry.start.isoformat(),
                    "end": price_entry.end.isoformat(),
                    "price": price_entry.entry[area],
                }
                for price_entry in price_data.entries
            ]

        return result

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PRICES_FOR_DATE,
        partial(get_prices, get_prices_for_date),
        schema=SERVICE_GET_PRICES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_PRICE_INDICES_FOR_DATE,
        partial(get_prices, get_price_indices_for_date),
        schema=SERVICE_GET_PRICE_INDICES_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )

    hass.services.async_register(
        DOMAIN,
        SERVICE_GET_CHEAPEST_PERIOD,
        get_cheapest_period,
        schema=SERVICE_GET_CHEAPEST_PERIOD_SCHEMA,
        supports_response=SupportsResponse.ONLY,
    )
