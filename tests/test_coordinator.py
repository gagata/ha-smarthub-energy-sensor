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

from custom_components.smarthub.sensor import (
    SmartHubDataUpdateCoordinator,
    _fill_empty_usage_from_daily,
)
from custom_components.smarthub.sensor import async_setup_entry as async_setup_sensor
from custom_components.smarthub.utils import assign_unique_meter_fragments
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
from datetime import datetime, timedelta, timezone
from homeassistant.const import UnitOfEnergy
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import EnergyConverter


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


def test_fill_empty_usage_from_daily_keeps_monthly_readings():
    """Only the empty meter is replaced with its own daily points."""
    monthly = [
        {"meter_id": "MAIN-1", "USAGE": [{"consumption": 40}], "legacy_meter": False, "meter_name": "Main"},
        {"meter_id": "OFF-2", "USAGE": [], "legacy_meter": True, "meter_name": "Off Peak"},
    ]
    daily = [
        {"meter_id": "MAIN-1", "USAGE": [{"consumption": 5}, {"consumption": 6}]},
        {"meter_id": "OFF-2", "USAGE": [{"consumption": 10}, {"consumption": 1}], "meter_name": "daily name"},
    ]

    filled = _fill_empty_usage_from_daily(monthly, daily)

    assert filled[0] == (monthly[0], False)
    assert filled[1][1] is True
    assert [point["consumption"] for point in filled[1][0]["USAGE"]] == [10, 1]
    assert filled[1][0]["legacy_meter"] is True
    assert filled[1][0]["meter_name"] == "Off Peak"
    # The monthly object for the populated meter is left as it was.
    assert monthly[0]["USAGE"] == [{"consumption": 40}]


async def test_daily_fallback_for_individual_empty_meter(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smarthub_api: AsyncMock,
) -> None:
    """A meter with monthly readings must not keep an empty sibling at zero."""
    mock_smarthub_api.get_service_locations.return_value = [_location()]
    month_start = datetime(2026, 11, 1, tzinfo=timezone.utc)
    next_day = datetime(2026, 11, 2, tzinfo=timezone.utc)
    monthly = {
        "meters": [
            {
                "meter_id": "MAIN-1",
                "meter_name": "Main",
                "USAGE": [{"reading_time": month_start, "consumption": 40}],
                "legacy_meter": False,
            },
            {
                "meter_id": "OFF-2",
                "meter_name": "Off Peak",
                "USAGE": [],
                "legacy_meter": True,
            },
        ],
        "USAGE": [{"reading_time": month_start, "consumption": 40}],
    }
    daily = {
        "meters": [
            {
                "meter_id": "MAIN-1",
                "meter_name": "Main",
                "USAGE": [
                    {"reading_time": month_start, "consumption": 5},
                    {"reading_time": next_day, "consumption": 6},
                ],
                "legacy_meter": False,
            },
            {
                "meter_id": "OFF-2",
                "meter_name": "Off Peak",
                "USAGE": [
                    {"reading_time": month_start, "consumption": 10},
                    {"reading_time": next_day, "consumption": 1},
                ],
                "legacy_meter": True,
            },
        ],
    }

    async def _get_energy_data(location=None, aggregation=None, start_datetime=None, **kwargs):
        if aggregation == Aggregation.MONTHLY:
            return monthly
        return daily

    mock_smarthub_api.get_energy_data.side_effect = _get_energy_data
    coordinator = SmartHubDataUpdateCoordinator(
        hass, api=mock_smarthub_api, update_interval=timedelta(minutes=720), config_entry=mock_config_entry
    )
    data = await coordinator._async_update_data()

    # MAIN keeps the monthly reading (40), not the daily sum (11).
    assert data["11111_main_1"][ENERGY_SENSOR_KEY] == 40
    # OFF had no monthly points, so its month-to-date is the daily sum.
    assert data["11111"][ENERGY_SENSOR_KEY] == 11


async def test_colliding_meter_ids_do_not_share_statistics(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smarthub_api: AsyncMock,
) -> None:
    """A-B and A B must get distinct statistic ids, entity keys, and unique ids."""
    mock_smarthub_api.get_service_locations.return_value = [_location()]
    first = datetime(2026, 11, 1, tzinfo=timezone.utc)
    second = datetime(2026, 11, 2, tzinfo=timezone.utc)
    mock_smarthub_api.get_energy_data.return_value = {
        "meters": [
            {
                "meter_id": "A-B",
                "meter_name": "Hyphen",
                "USAGE": [
                    {"reading_time": first, "consumption": 2},
                    {"reading_time": second, "consumption": 3},
                ],
                "USAGE_RETURN": [{"reading_time": first, "consumption": 4}],
                "legacy_meter": False,
            },
            {
                "meter_id": "A B",
                "meter_name": "Space",
                "USAGE": [
                    {"reading_time": first, "consumption": 10},
                    {"reading_time": second, "consumption": 1},
                ],
                "USAGE_RETURN": [{"reading_time": first, "consumption": 7}],
                "legacy_meter": True,
            },
        ],
    }
    fragments = assign_unique_meter_fragments(["A-B", "A B"])
    assert fragments["A-B"] != fragments["A B"]
    assert fragments["A-B"] != "a_b"
    assert fragments["A B"] != "a_b"

    coordinator = SmartHubDataUpdateCoordinator(
        hass, api=mock_smarthub_api, update_interval=timedelta(minutes=720), config_entry=mock_config_entry
    )
    data = await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    hyphen = f"smarthub:smarthub_energy_sensor_daily_123456_11111_{fragments['A-B']}"
    space = f"smarthub:smarthub_energy_sensor_daily_123456_11111_{fragments['A B']}"
    hyphen_return = f"smarthub:smarthub_energy_return_sensor_daily_123456_11111_{fragments['A-B']}"
    space_return = f"smarthub:smarthub_energy_return_sensor_daily_123456_11111_{fragments['A B']}"
    legacy = "smarthub:smarthub_energy_sensor_daily_123456_11111"
    legacy_return = "smarthub:smarthub_energy_return_sensor_daily_123456_11111"
    bare = "smarthub:smarthub_energy_sensor_daily_123456_11111_a_b"
    stats = await get_instance(hass).async_add_executor_job(
        statistics_during_period,
        hass,
        dt_util.utc_from_timestamp(0),
        None,
        {hyphen, space, hyphen_return, space_return, legacy, legacy_return, bare},
        "hour",
        None,
        {"state", "sum"},
    )

    assert stats[hyphen][0]["sum"] == 2
    assert stats[hyphen][1]["sum"] == 5
    assert stats[space][0]["sum"] == 10
    assert stats[space][1]["sum"] == 11
    assert stats[legacy][0]["sum"] == 10
    assert stats[legacy][1]["sum"] == 11
    assert stats[hyphen_return][0]["sum"] == 4
    assert stats[space_return][0]["sum"] == 7
    assert stats[legacy_return][0]["sum"] == 7
    assert bare not in stats

    assert data["11111"][ENERGY_SENSOR_KEY] == 1
    assert data[f"11111_{fragments['A-B']}"][ENERGY_SENSOR_KEY] == 3
    assert "11111_a_b" not in data

    added = []
    coordinator.data = data
    coordinator.last_update_success = True
    mock_config_entry.runtime_data = coordinator
    await async_setup_sensor(hass, mock_config_entry, lambda entities, update_before_add=False: added.extend(entities))
    unique_ids = {entity.unique_id for entity in added}
    assert unique_ids == {
        f"{mock_config_entry.unique_id}_11111_energy",
        f"{mock_config_entry.unique_id}_11111_{fragments['A-B']}_energy",
    }


def _statistic_metadata(statistic_id: str) -> StatisticMetaData:
    return StatisticMetaData(
        mean_type=StatisticMeanType.NONE,
        has_sum=True,
        name=statistic_id,
        source=DOMAIN,
        statistic_id=statistic_id,
        unit_class=EnergyConverter.UNIT_CLASS,
        unit_of_measurement=UnitOfEnergy.KILO_WATT_HOUR,
    )


def _is_wide_window(start_datetime) -> bool:
    if start_datetime is None:
        return False
    if start_datetime.tzinfo is None:
        start_datetime = start_datetime.astimezone()
    age = datetime.now(timezone.utc) - start_datetime.astimezone(timezone.utc)
    return age > timedelta(days=45)


async def test_new_meter_imports_full_history_without_rewriting_existing(
    recorder_mock: Recorder,
    hass: HomeAssistant,
    mock_config_entry: MockConfigEntry,
    mock_smarthub_api: AsyncMock,
) -> None:
    """Legacy statistics must not shorten history for a meter that has none of its own.

    The meter that already has statistics stays on the short window, so older
    points from the backfill are not written over it.
    """
    mock_smarthub_api.get_service_locations.return_value = [_location()]
    # Midnight keeps both the hourly and daily statistic periods aligned.
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    legacy_start = now - timedelta(days=5)
    recent_point = now - timedelta(days=1)
    old_point = now - timedelta(days=40)

    async def _seed(statistic_id: str) -> None:
        async_add_external_statistics(
            hass,
            _statistic_metadata(statistic_id),
            [StatisticData(start=legacy_start, state=5, sum=100)],
        )

    for suffix in ("", "_daily"):
        await _seed(f"smarthub:smarthub_energy_sensor{suffix}_123456_11111")
        await _seed(f"smarthub:smarthub_energy_sensor{suffix}_123456_11111_off_2")
    await async_wait_recording_done(hass)

    def _meters(include_old: bool) -> dict:
        # The short window still repeats the latest stored reading. The older
        # point exists only in the full-history response.
        off_usage = [
            {"reading_time": legacy_start, "consumption": 5},
            {"reading_time": recent_point, "consumption": 2},
        ]
        main_usage = [{"reading_time": recent_point, "consumption": 4}]
        if include_old:
            off_usage.insert(0, {"reading_time": old_point, "consumption": 40})
            main_usage.insert(0, {"reading_time": old_point, "consumption": 50})
        return {
            "meters": [
                {"meter_id": "MAIN-1", "meter_name": "Main", "USAGE": main_usage, "legacy_meter": False},
                {"meter_id": "OFF-2", "meter_name": "Off Peak", "USAGE": off_usage, "legacy_meter": True},
            ]
        }

    calls = []

    async def _get_energy_data(location=None, aggregation=None, start_datetime=None, **kwargs):
        wide = _is_wide_window(start_datetime)
        calls.append({"aggregation": aggregation, "wide": wide})
        return _meters(include_old=wide)

    mock_smarthub_api.get_energy_data.side_effect = _get_energy_data
    coordinator = SmartHubDataUpdateCoordinator(
        hass, api=mock_smarthub_api, update_interval=timedelta(minutes=720), config_entry=mock_config_entry
    )
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)

    stat_calls = [call for call in calls if call["aggregation"] in (Aggregation.HOURLY, Aggregation.DAILY)]
    assert len([call for call in stat_calls if call["wide"]]) == 2
    assert len([call for call in stat_calls if not call["wide"]]) == 2

    async def _load(statistic_ids: set[str]):
        return await get_instance(hass).async_add_executor_job(
            statistics_during_period,
            hass,
            dt_util.utc_from_timestamp(0),
            None,
            statistic_ids,
            "hour",
            None,
            {"state", "sum"},
        )

    def _starts(rows) -> list[datetime]:
        starts = []
        for row in rows:
            start = row["start"]
            if isinstance(start, (int, float)):
                start = datetime.fromtimestamp(start, tz=timezone.utc)
            elif start.tzinfo is None:
                start = start.replace(tzinfo=timezone.utc)
            else:
                start = start.astimezone(timezone.utc)
            starts.append(start)
        return starts

    daily_legacy = "smarthub:smarthub_energy_sensor_daily_123456_11111"
    daily_off = "smarthub:smarthub_energy_sensor_daily_123456_11111_off_2"
    daily_main = "smarthub:smarthub_energy_sensor_daily_123456_11111_main_1"
    hourly_off = "smarthub:smarthub_energy_sensor_123456_11111_off_2"
    hourly_main = "smarthub:smarthub_energy_sensor_123456_11111_main_1"
    stats = await _load({daily_legacy, daily_off, daily_main, hourly_off, hourly_main})

    def _close(start: datetime, target: datetime) -> bool:
        return abs((start - target).total_seconds()) < 1

    for existing in (daily_legacy, daily_off, hourly_off):
        assert stats[existing][-1]["sum"] == 102
        assert not any(_close(start, old_point) for start in _starts(stats[existing]))
    for created in (daily_main, hourly_main):
        assert stats[created][0]["sum"] == 50
        assert stats[created][-1]["sum"] == 54
        assert any(_close(start, old_point) for start in _starts(stats[created]))

    calls.clear()
    await coordinator._async_update_data()
    await async_wait_recording_done(hass)
    second_stat_calls = [call for call in calls if call["aggregation"] in (Aggregation.HOURLY, Aggregation.DAILY)]
    assert [call for call in second_stat_calls if call["wide"]] == []

    again = await _load({daily_legacy, daily_off, daily_main, hourly_off, hourly_main})
    assert again[daily_legacy][-1]["sum"] == 102
    assert again[daily_off][-1]["sum"] == 102
    assert again[daily_main][-1]["sum"] == 54
    assert again[hourly_main][-1]["sum"] == 54
    assert not any(_close(start, old_point) for start in _starts(again[daily_off]))


async def async_wait_recording_done(hass) -> None:
    """Async wait until recording is done."""
    await hass.async_block_till_done()
    get_instance(hass)._async_commit(dt_util.utcnow())
    await hass.async_block_till_done()
    await hass.async_add_executor_job(get_instance(hass).block_till_done)
    await hass.async_block_till_done()
