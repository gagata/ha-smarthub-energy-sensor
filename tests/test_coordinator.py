"""Test file for SmartHub sensor (statistics)"""
import pytest
from unittest.mock import Mock, patch, AsyncMock
from collections.abc import Generator
from homeassistant.core import HomeAssistant
from homeassistant.config_entries import ConfigEntry
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.smarthub import async_setup_entry
from custom_components.smarthub.api import Aggregation, SmartHubAPI, SmartHubAPIError, SmartHubLocation
from custom_components.smarthub.const import DOMAIN, ELECTRIC_SERVICE, ENERGY_SENSOR_KEY

from custom_components.smarthub.sensor import SmartHubDataUpdateCoordinator
from custom_components.smarthub.sensor import async_setup_entry as async_setup_sensor
from homeassistant.components.recorder import Recorder
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from datetime import timedelta
from homeassistant.util import dt as dt_util


from homeassistant.components.recorder import get_instance

@pytest.fixture(autouse=True)
def mock_smarthub_api(hass) -> Generator[AsyncMock]:
    """Mock the config entry ..."""

    api = SmartHubAPI(
        email="test@example.com",
        password="testpass",
        account_id="123456",
        timezone="UTC",
        mfa_totp="",
        host="test.smarthub.coop"
    )

    with patch(
        "custom_components.smarthub.api.SmartHubAPI", autospec=True
    ) as mock_api:

        mock_api.timezone="UTC"
        mock_api.parse_usage = api.parse_usage
        mock_api.get_service_locations.return_value = []
        mock_api.get_energy_data.return_value = {}
        yield mock_api


@pytest.fixture()
def mock_config_entry(hass) -> MockConfigEntry:
    """Create a mock config entry."""
    return MockConfigEntry(
        version=1,
        domain=DOMAIN,
        title="SmartHub Test",
        data={
            "email": "test@example.com",
            "password": "testpass",
            "account_id": "123456",
            "location_id": "789012",
            "host": "test.smarthub.coop",
            "poll_interval": 60,
            "timezone": "UTC",
            "mfa_totp": "",
        },
        unique_id="test@example.com_test.smarthub.coop_123456",
    )

async def test_coordinator_first_run_forward_meter(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smarthub_api: AsyncMock,
) -> None:
    """Test the coordinator on its first run with no existing statistics."""
    mock_smarthub_api.get_service_locations.return_value = [
      SmartHubLocation(
        id="11111",
        service=ELECTRIC_SERVICE,
        description="test location",
        provider="test provider",
      )
    ]

    test_data = {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "meters": [
                     {'meterNumber': '1ND91111111', 'seriesId': '1ND91111111', 'flowDirection': 'FORWARD', 'isNetMeter': False}, # Forward meter is full consumption.
                    ],
                    "series": [
                        {
                            "meterNumber": "1ND91111111", "name": "1ND91111111",
                            "data": [
                                {"x": 1762215300000, "y":   1},
                                {"x": 1762216200000, "y":  10},
                                {"x": 1762217100000, "y": 100},
                                {"x": 1762218900000, "y": 1},
                            ]
                        },
                    ]
                }
            ]
        }
    }

    mock_smarthub_api.get_energy_data.return_value = mock_smarthub_api.parse_usage(test_data)

    coordinator = SmartHubDataUpdateCoordinator(hass, api=mock_smarthub_api, update_interval=timedelta(minutes=720), config_entry=mock_config_entry)

    data = await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    legacy_id = "smarthub:smarthub_energy_sensor_daily_123456_11111"
    # Uppercase meter numbers are lowercased so the external statistic id is valid.
    per_meter_id = "smarthub:smarthub_energy_sensor_daily_123456_11111_1nd91111111"
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {legacy_id, per_meter_id},
        "hour",
        None,
        {"state", "sum"},
    )

    # The first hour's statistics summary is...
    assert stats[legacy_id][0]["sum"] == 111.0
    assert stats[per_meter_id][0]["sum"] == 111.0
    # Single meter keeps the historical location-id lookup key.
    assert set(data) == {"11111"}
    assert data["11111"]["meter_id"] == "1ND91111111"


async def test_coordinator_first_run_net_meter(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smarthub_api: AsyncMock,
) -> None:
    """Test the coordinator on its first run with no existing statistics."""
    mock_smarthub_api.get_service_locations.return_value = [
      SmartHubLocation(
        id="11111",
        service=ELECTRIC_SERVICE,
        description="test location",
        provider="test provider",
      )
    ]

    test_data = {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "meters": [
                     {'meterNumber': '1ND81111111', 'seriesId': '1ND81111111', 'flowDirection': 'NET', 'isNetMeter': True}, # Includes in and out bound flows (posirive/negative)
                     {'meterNumber': '1ND91111111', 'seriesId': '1ND91111111', 'flowDirection': 'FORWARD', 'isNetMeter': False}, # Forward meter is full consumption.
                    ],
                    "series": [
                        {
                            "meterNumber": "1ND91111111", "name": "1ND91111111",
                            "data": [
                                {"x": 1762215300000, "y":   1},
                                {"x": 1762216200000, "y":  10},
                                {"x": 1762217100000, "y": 100},
                                {"x": 1762218900000, "y": 1},
                                {"x": 1762219800000, "y": 1},
                            ]
                        },
                        {
                            "meterNumber": "1ND81111111", "name": "1ND81111111",
                            "data": [
                                {"x": 1762215300000, "y":   1},
                                {"x": 1762216200000, "y":  -5}, # generated 15 KW of power this hour - returned 5 to the grid
                                {"x": 1762217100000, "y": 100},
                                {"x": 1762218900000, "y": 1},
                                {"x": 1762219800000, "y":  -1}, # generated 2 KW of power this hour - returned 1 to the grid
                            ]
                        },
                    ]
                }
            ]
        }
    }

    mock_smarthub_api.get_energy_data.return_value = mock_smarthub_api.parse_usage(test_data)
    assert mock_smarthub_api.get_energy_data.return_value["USAGE_RETURN"][0]['consumption'] == 5
    assert mock_smarthub_api.get_energy_data.return_value["USAGE_RETURN"][1]['consumption'] == 1

    coordinator = SmartHubDataUpdateCoordinator(hass, api=mock_smarthub_api, update_interval=timedelta(minutes=720), config_entry=mock_config_entry)

    await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    # Check stats for electric account '111111'
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {
            "smarthub:smarthub_energy_sensor_daily_123456_11111",
            "smarthub:smarthub_energy_return_sensor_daily_123456_11111",
        },
        "hour",
        None,
        {"state", "sum"},
    )

    # The first hour's statistics summary is...
    assert stats["smarthub:smarthub_energy_sensor_daily_123456_11111"][0]["sum"] == 101.0
    assert stats["smarthub:smarthub_energy_sensor_daily_123456_11111"][1]["sum"] == 102.0
    assert stats["smarthub:smarthub_energy_return_sensor_daily_123456_11111"][0]["sum"] == 5
    assert stats["smarthub:smarthub_energy_return_sensor_daily_123456_11111"][1]["sum"] == 6

async def test_coordinator_first_run_return_meter(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smarthub_api: AsyncMock,
) -> None:
    """Test the coordinator on its first run with no existing statistics."""
    mock_smarthub_api.get_service_locations.return_value = [
      SmartHubLocation(
        id="11111",
        service=ELECTRIC_SERVICE,
        description="test location",
        provider="test provider",
      )
    ]

    test_data = {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "meters": [
                     {'meterNumber': '1ND91111111', 'seriesId': '1ND87334444', 'flowDirection': 'RETURN', 'isNetMeter': False}, # Includes in and out bound flows (posirive/negative)
                     {'meterNumber': '1ND91111111', 'seriesId': '1ND86200137', 'flowDirection': 'FORWARD', 'isNetMeter': False}, # Forward meter is full consumption.
                    ],
                    "series": [
                        {
                            "meterNumber": "1ND86200137", "name": "1ND86200137",
                            "data": [
                                {"x": 1762215300000, "y":   1},
                                {"x": 1762216200000, "y":  10},
                                {"x": 1762217100000, "y": 100},
                                {"x": 1762218900000, "y": 1},
                                {"x": 1762219800000, "y": 1},
                            ]
                        },
                        {
                            "meterNumber": "1ND87334444", "name": "1ND87334444",
                            "data": [
                                {"x": 1762215300000, "y":   0},
                                {"x": 1762216200000, "y":  5}, # generated 15 KW of power this hour - returned 5 to the grid
                                {"x": 1762217100000, "y": 0},
                                {"x": 1762218900000, "y": 0},
                                {"x": 1762219800000, "y":  1}, # generated 2 KW of power this hour - returned 1 to the grid
                            ]
                        },
                    ]
                }
            ]
        }
    }

    mock_smarthub_api.get_energy_data.return_value = mock_smarthub_api.parse_usage(test_data)
    assert mock_smarthub_api.get_energy_data.return_value["USAGE_RETURN"][0]['consumption'] == 5
    assert mock_smarthub_api.get_energy_data.return_value["USAGE_RETURN"][1]['consumption'] == 1

    coordinator = SmartHubDataUpdateCoordinator(hass, api=mock_smarthub_api, update_interval=timedelta(minutes=720), config_entry=mock_config_entry)

    await coordinator._async_update_data()

    await async_wait_recording_done(hass)

    # Check stats for electric account '111111'
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {
            "smarthub:smarthub_energy_sensor_daily_123456_11111",
            "smarthub:smarthub_energy_return_sensor_daily_123456_11111",
        },
        "hour",
        None,
        {"state", "sum"},
    )

    # The first hour's statistics summary is...
    assert stats["smarthub:smarthub_energy_sensor_daily_123456_11111"][0]["sum"] == 111.0
    assert stats["smarthub:smarthub_energy_sensor_daily_123456_11111"][1]["sum"] == 113.0
    assert stats["smarthub:smarthub_energy_return_sensor_daily_123456_11111"][0]["sum"] == 5
    assert stats["smarthub:smarthub_energy_return_sensor_daily_123456_11111"][1]["sum"] == 6



def _location():
    return SmartHubLocation(
        id="11111",
        service=ELECTRIC_SERVICE,
        description="test location",
        provider="test provider",
    )


def _two_forward_payload():
    """Main then off-peak. The legacy stream must follow the last FORWARD meter."""
    return {
        "data": {
            "ELECTRIC": [
                {
                    "type": "USAGE",
                    "meters": [
                        {"meterNumber": "MAIN-1", "seriesId": "series-main", "flowDirection": "FORWARD"},
                        {"meterNumber": "OFF-2", "seriesId": "series-off", "flowDirection": "FORWARD"},
                        {"meterNumber": "MAIN-1", "seriesId": "series-ret", "flowDirection": "RETURN"},
                    ],
                    "series": [
                        {
                            "name": "series-main",
                            "data": [
                                {"x": 1762218000000, "y": 2},
                                {"x": 1762221600000, "y": 3},
                            ],
                        },
                        {
                            "name": "series-off",
                            "data": [
                                {"x": 1762218000000, "y": 10},
                                {"x": 1762221600000, "y": 1},
                            ],
                        },
                        {
                            "name": "series-ret",
                            "data": [
                                {"x": 1762218000000, "y": 4},
                            ],
                        },
                    ],
                }
            ]
        }
    }


async def test_coordinator_legacy_statistic_follows_last_forward_meter(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smarthub_api: AsyncMock,
) -> None:
    """Legacy statistic ids keep updating from the last FORWARD meter, not the first."""
    mock_smarthub_api.get_service_locations.return_value = [_location()]
    mock_smarthub_api.get_energy_data.return_value = mock_smarthub_api.parse_usage(_two_forward_payload())

    coordinator = SmartHubDataUpdateCoordinator(
        hass, api=mock_smarthub_api, update_interval=timedelta(minutes=720), config_entry=mock_config_entry
    )
    data = await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    legacy_usage = "smarthub:smarthub_energy_sensor_daily_123456_11111"
    legacy_return = "smarthub:smarthub_energy_return_sensor_daily_123456_11111"
    main_usage = "smarthub:smarthub_energy_sensor_daily_123456_11111_main_1"
    main_return = "smarthub:smarthub_energy_return_sensor_daily_123456_11111_main_1"
    off_usage = "smarthub:smarthub_energy_sensor_daily_123456_11111_off_2"
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {legacy_usage, legacy_return, main_usage, main_return, off_usage},
        "hour",
        None,
        {"state", "sum"},
    )

    assert stats[legacy_usage][0]["sum"] == 10.0
    assert stats[legacy_usage][1]["sum"] == 11.0
    assert stats[off_usage][0]["sum"] == 10.0
    assert stats[main_usage][0]["sum"] == 2.0
    assert stats[main_usage][1]["sum"] == 5.0
    assert stats[legacy_return][0]["sum"] == 4.0
    assert stats[main_return][0]["sum"] == 4.0
    assert data["11111"][ENERGY_SENSOR_KEY] == 1
    assert data["11111_main_1"][ENERGY_SENSOR_KEY] == 3
    assert "11111_MAIN-1" not in data
    assert "11111_OFF-2" not in data


async def test_daily_fallback_when_monthly_usage_lists_are_empty(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smarthub_api: AsyncMock,
) -> None:
    """Empty USAGE lists (not just a missing meters list) still sum DAILY points."""
    mock_smarthub_api.get_service_locations.return_value = [_location()]
    parsed_daily = mock_smarthub_api.parse_usage(_two_forward_payload())

    async def _get_energy_data(location=None, aggregation=None, start_datetime=None, **kwargs):
        if aggregation == Aggregation.MONTHLY:
            return {
                "meters": [
                    {"meter_id": "MAIN-1", "meter_name": "Main", "USAGE": [], "legacy_meter": False},
                    {"meter_id": "OFF-2", "meter_name": "Off Peak", "USAGE": [], "legacy_meter": True},
                ],
                "USAGE": [],
            }
        return parsed_daily

    mock_smarthub_api.get_energy_data.side_effect = _get_energy_data

    coordinator = SmartHubDataUpdateCoordinator(
        hass, api=mock_smarthub_api, update_interval=timedelta(minutes=720), config_entry=mock_config_entry
    )
    data = await coordinator._async_update_data()

    # Last FORWARD meter is the legacy entity; its month-to-date is the daily sum (10+1).
    assert data["11111"][ENERGY_SENSOR_KEY] == 11
    assert data["11111_main_1"][ENERGY_SENSOR_KEY] == 5


async def test_empty_startup_keeps_lookup_key_and_adds_later_meters(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smarthub_api: AsyncMock,
) -> None:
    """A location-id sensor created with no data recovers, and new meters are added."""
    mock_smarthub_api.get_service_locations.return_value = [_location()]
    phase = {"have_data": False}
    parsed = mock_smarthub_api.parse_usage(_two_forward_payload())

    async def _get_energy_data(location=None, aggregation=None, start_datetime=None, **kwargs):
        if not phase["have_data"]:
            return {}
        return parsed

    mock_smarthub_api.get_energy_data.side_effect = _get_energy_data

    coordinator = SmartHubDataUpdateCoordinator(
        hass, api=mock_smarthub_api, update_interval=timedelta(minutes=720), config_entry=mock_config_entry
    )
    empty = await coordinator._async_update_data()
    assert set(empty) == {"11111"}
    assert empty["11111"][ENERGY_SENSOR_KEY] == 0

    added = []

    def _add_entities(entities, update_before_add=False):
        added.extend(entities)

    coordinator.data = empty
    coordinator.last_update_success = True
    mock_config_entry.runtime_data = coordinator
    await async_setup_sensor(hass, mock_config_entry, _add_entities)

    assert len(added) == 1
    assert added[0].unique_id == f"{mock_config_entry.unique_id}_11111_energy"
    assert added[0]._entity_key == "11111"

    phase["have_data"] = True
    populated = await coordinator._async_update_data()
    coordinator.async_set_updated_data(populated)
    await hass.async_block_till_done()

    assert len(added) == 2
    assert added[0].native_value == 1
    assert added[0].unique_id == f"{mock_config_entry.unique_id}_11111_energy"
    extra_ids = {entity.unique_id for entity in added[1:]}
    assert extra_ids == {f"{mock_config_entry.unique_id}_11111_main_1_energy"}
    assert added[1]._entity_key == "11111_main_1"
    assert added[1].native_value == 3


async def async_wait_recording_done(hass) -> None:
    """Async wait until recording is done."""
    await hass.async_block_till_done()
    get_instance(hass)._async_commit(dt_util.utcnow())
    await hass.async_block_till_done()
    await hass.async_add_executor_job(get_instance(hass).block_till_done)
    await hass.async_block_till_done()
