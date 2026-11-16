"""Failed updates keep the last good values instead of going unavailable or 0."""
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
from homeassistant.helpers.update_coordinator import UpdateFailed
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthub.api import SmartHubAPIError, SmartHubLocation
from custom_components.smarthub.const import DOMAIN, ELECTRIC_SERVICE, ENERGY_SENSOR_KEY
from custom_components.smarthub.sensor import SmartHubDataUpdateCoordinator


def _coordinator(hass, api):
    entry = MockConfigEntry(domain=DOMAIN, data={"account_id": "123456"})
    return SmartHubDataUpdateCoordinator(hass, api=api, update_interval=timedelta(minutes=60), config_entry=entry)


async def test_api_error_keeps_previous_data(hass):
    api = AsyncMock()
    api.get_service_locations.side_effect = SmartHubAPIError("timeout")
    coordinator = _coordinator(hass, api)
    previous = {"1": {ENERGY_SENSOR_KEY: 123.4}}
    coordinator.data = previous
    assert await coordinator._async_update_data() is previous


async def test_api_error_without_previous_data_raises(hass):
    api = AsyncMock()
    api.get_service_locations.side_effect = SmartHubAPIError("timeout")
    with pytest.raises(UpdateFailed):
        await _coordinator(hass, api)._async_update_data()


async def test_empty_usage_keeps_previous_value_instead_of_zero(hass):
    location = SmartHubLocation(id="1", service=ELECTRIC_SERVICE, description="home", provider="coop")
    api = AsyncMock()
    api.timezone = "UTC"
    api.get_service_locations.return_value = [location]
    api.get_energy_data.return_value = {}
    coordinator = _coordinator(hass, api)
    coordinator._insert_statistics = AsyncMock()
    coordinator.data = {"1": {ENERGY_SENSOR_KEY: 55.5}}
    result = await coordinator._async_update_data()
    assert result["1"][ENERGY_SENSOR_KEY] == 55.5
