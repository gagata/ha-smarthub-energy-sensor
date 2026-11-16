"""The month-to-date window starts at local midnight on the 1st in the utility's time zone."""
from datetime import datetime, timedelta
from unittest.mock import AsyncMock
from zoneinfo import ZoneInfo

from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthub.api import Aggregation, SmartHubLocation
from custom_components.smarthub.const import DOMAIN, ELECTRIC_SERVICE
from custom_components.smarthub.sensor import SmartHubDataUpdateCoordinator


async def test_month_start_uses_utility_timezone(hass, freezer):
    # 03:00 UTC on Nov 1 is still Oct 31 in Chicago: the month-to-date window is October.
    freezer.move_to("2026-11-01T03:00:00+00:00")
    location = SmartHubLocation(id="1", service=ELECTRIC_SERVICE, description="home", provider="coop")
    api = AsyncMock()
    api.timezone = "America/Chicago"
    api.get_service_locations.return_value = [location]
    api.get_energy_data.return_value = {}
    entry = MockConfigEntry(domain=DOMAIN, data={"account_id": "123456"})
    coordinator = SmartHubDataUpdateCoordinator(hass, api=api, update_interval=timedelta(minutes=60), config_entry=entry)
    coordinator._insert_statistics = AsyncMock()

    await coordinator._async_update_data()

    monthly = [c for c in api.get_energy_data.call_args_list if c.kwargs["aggregation"] == Aggregation.MONTHLY]
    start = monthly[0].kwargs["start_datetime"]
    assert start == datetime(2026, 10, 1, tzinfo=ZoneInfo("America/Chicago"))
    assert start.utcoffset() == timedelta(hours=-5)
