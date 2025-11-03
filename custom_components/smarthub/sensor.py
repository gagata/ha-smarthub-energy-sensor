"""SmartHub energy sensor platform."""
from __future__ import annotations

import traceback

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import (
    CoordinatorEntity,
    DataUpdateCoordinator,
    UpdateFailed,
)
from homeassistant.util.unit_conversion import EnergyConverter
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMeanType,
    StatisticMetaData,
)

from .api import SmartHubAPI, SmartHubAPIError, SmartHubAuthError, SmartHubLocation
from .const import (
    DOMAIN,
    ENERGY_SENSOR_KEY,
    ATTR_LAST_READING_TIME,
    ATTR_ACCOUNT_ID,
    ATTR_LOCATION_ID,
    LOCATION_KEY,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SmartHub sensor platform."""
    _LOGGER.debug("Setting up SmartHub sensor platform")

    config: Dict[str, Any] = config_entry.data

    coordinator = config_entry.runtime_data
    last_locations_consumption = coordinator.data.values()

    # Create sensor entities for each location
    entities = []
    for last_consumption in last_locations_consumption:
      entities.append(
          SmartHubEnergySensor(
              coordinator=coordinator,
              config_entry=config_entry,
              config=config,
              location=last_consumption.get(LOCATION_KEY),
          )
      )

    async_add_entities(entities, update_before_add=True)
    _LOGGER.debug("SmartHub sensor entities added successfully")


class SmartHubDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SmartHub data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: SmartHubAPI,
        update_interval: timedelta,
        config_entry: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{config_entry.entry_id}",
            update_interval=update_interval,
        )
        self.api = api
        self.account_id = config_entry.data.get('account_id','unknown')

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the SmartHub API."""
        try:
            _LOGGER.debug("Fetching data from SmartHub API")

            # force a logout of the session
            self.api.token = None

            locations = await self.api.get_service_locations()

            entity_response = {}

            for location in locations:
              # Because SmartHub provides historical usage/cost with delay of a
              # number of hours we need to insert data into statistics.
              await self._insert_statistics(location)

              # Fetch monthly information for entity value
              first_day_of_current_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

              data = await self.api.get_energy_data(location=location, start_datetime=first_day_of_current_month)

              if data.get("USAGE", None) is None:
                  _LOGGER.warning("No data received from SmartHub API for location %s", location)
                  # Return previous data if available, otherwise empty dict
                  entity_response[location.id] = self.data or {}
                  continue

              last_reading = data.get("USAGE")[-1]
              _LOGGER.debug("Successfully fetched data: %s for location: %s", last_reading, location)

              entity_response[location.id] = {
                ENERGY_SENSOR_KEY: last_reading['consumption'],
                ATTR_LAST_READING_TIME: last_reading['reading_time'],
                LOCATION_KEY: location,
              }

            return entity_response

        except SmartHubAuthError as e:
            _LOGGER.error("Authentication error fetching SmartHub data: %s", e)
            # For auth errors, we want to raise UpdateFailed to trigger retry
            # but also ensure the API will refresh authentication on next attempt
            raise UpdateFailed(f"Authentication failed: {e}") from e
        except SmartHubAPIError as e:
            _LOGGER.error("Error fetching data from SmartHub API: %s", e)
            raise UpdateFailed(f"Error communicating with SmartHub API: {e}") from e
        except Exception as e:
            _LOGGER.exception("Unexpected error fetching SmartHub data: %s", e)
            raise UpdateFailed(f"Unexpected error: {e}") from e


    # https://github.com/tronikos/opower/ was used as a model for how to populate
    # hourly metrics when access to realtime information is not possible via
    # utility dashboards.
    async def _insert_statistics(self, location):
        """Retrieve energy usage data asynchronously with retry logic. Always backfills the data overwriting the history based on the collection window."""
        consumption_statistic_id = f"{DOMAIN}:smarthub_energy_sensor_{self.account_id}_{location.id}"

        consumption_unit_class = (
            EnergyConverter.UNIT_CLASS
        )
        consumption_unit = (
            UnitOfEnergy.KILO_WATT_HOUR
        )
        consumption_metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"SmartHub Energy Hourly Usage - {self.account_id} - {location.description}",
            source=DOMAIN,
            statistic_id=consumption_statistic_id,
#             unit_class=consumption_unit_class, # required in 2025.11
            unit_of_measurement=consumption_unit,
        )

        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, consumption_statistic_id, True, set()
        )
        _LOGGER.debug("last_stat: %s", last_stat)

        smarthub_data = {}
        if not last_stat:
            _LOGGER.debug("Updating statistic for the first time")
            consumption_sum = 0.0
            last_stats_time = None

            # Initialize with last 90 days of data
            start_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=90)

            # Load read data for use in populating statistics
            smarthub_data = await self.api.get_energy_data(location=location, aggregation="HOURLY", start_datetime=start_datetime)
        else:
            _LOGGER.debug("Checking if data migration is needed...")
            migrated = False
            # SmartHub doesn't hvae any current migrations - this sample code was left
            # from the opower version
            #migrated = await self._async_maybe_migrate_statistics(
            #    account.utility_account_id,
            #    {
            #        cost_statistic_id: compensation_statistic_id,
            #        consumption_statistic_id: return_statistic_id,
            #    },
            #    {
            #        cost_statistic_id: cost_metadata,
            #        compensation_statistic_id: compensation_metadata,
            #        consumption_statistic_id: consumption_metadata,
            #        return_statistic_id: return_metadata,
            #    },
            #)
            if migrated:
                # Skip update to avoid working on old data since the migration is done
                # asynchronously. Update the statistics in the next refresh in 12h.
                _LOGGER.debug(
                    "Statistics migration completed. Skipping update for now"
                )
                return

            # Update reads...
            # Load read data for use in populating statistics
            start_datetime = datetime.fromtimestamp(last_stat[consumption_statistic_id][0]["start"], tz=timezone.utc)
            _LOGGER.debug("Fetching statistics from %s", start_datetime)
            smarthub_data = await self.api.get_energy_data(location=location, start_datetime=start_datetime, aggregation="HOURLY")

            start = smarthub_data.get("USAGE")[0].get("reading_time")
            _LOGGER.debug("Getting statistics at: %s", start)
            # In the common case there should be a previous statistic at start time
            # so we only need to fetch one statistic. If there isn't any, fetch all.
            # Counterintutitively - but consistent with opower - this aligns the
            # last Stats collection with the data collected form the server - then imports
            # and overrights all the data after that point. The opower logic is that the
            # data might be refreshed, or have collection gaps that are fixed.
            # Its duplicated for SmartHub as it seems reasonable.
            for end in (start + timedelta(seconds=1), None):
                stats = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass,
                    start,
                    end,
                    {
                        consumption_statistic_id,
                    },
                    "hour",
                    None,
                    {"sum"},
                )
                if stats:
                    break
                if end:
                    _LOGGER.debug(
                        "Not found. Trying to find the oldest statistic after %s",
                        start,
                    )
            # We are in this code path only if get_last_statistics found a stat
            # so statistics_during_period should also have found at least one.
            assert stats

            def _safe_get_sum(records: list[Any]) -> float:
                if records and "sum" in records[0]:
                    return float(records[0]["sum"])
                return 0.0

            consumption_sum = _safe_get_sum(stats.get(consumption_statistic_id, []))
            last_stats_time = stats[consumption_statistic_id][0]["start"]

            _LOGGER.info(f"Updating statistics since %s", last_stats_time)

        consumption_statistics = []

        for cost_read in smarthub_data.get("USAGE"):
            start = cost_read.get("reading_time")
            if last_stats_time is not None and start.timestamp() <= last_stats_time:
                continue

            consumption_state = max(0, cost_read.get("consumption"))
            consumption_sum += consumption_state

            consumption_statistics.append(
                StatisticData(
                    start=start, state=consumption_state, sum=consumption_sum
                )
            )

        _LOGGER.info(
            "Adding %s statistics for %s",
            len(consumption_statistics),
            consumption_statistic_id,
        )
        async_add_external_statistics(
            self.hass, consumption_metadata, consumption_statistics
        )




class SmartHubEnergySensor(CoordinatorEntity, SensorEntity):
    """Representation of a SmartHub energy sensor."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR
    _attr_icon = "mdi:lightning-bolt"

    def __init__(
        self,
        coordinator: SmartHubDataUpdateCoordinator,
        config_entry: ConfigEntry,
        config: Dict[str, Any],
        location: SmartHubLocation,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self._config_entry = config_entry
        self._config = config
        self._attr_unique_id = f"{config_entry.unique_id}_{location.id}_energy"
        self.location = location

        # Extract account info for naming
        account_id = config.get("account_id", "Unknown")

        self._attr_name = f"SmartHub Energy Monthly Usage {account_id} {self.location.description}"

        _LOGGER.debug("Initialized SmartHub energy sensor with unique_id: %s", self._attr_unique_id)

    @property
    def available(self) -> bool:
        """Return True if entity is available."""
        return self.coordinator.last_update_success and self.native_value is not None

    @property
    def native_value(self) -> Optional[float]:
        """Return the state of the sensor."""
        if not self.coordinator.data:
            return None

        value = self.coordinator.data.get(self.location.id, {}).get(ENERGY_SENSOR_KEY, None)
        if value is None:
            _LOGGER.debug("No energy usage value found in coordinator data")
            return None

        try:
            return float(value)
        except (ValueError, TypeError) as e:
            _LOGGER.warning("Could not convert energy value '%s' to float: %s", value, e)
            return None

    @property
    def extra_state_attributes(self) -> Dict[str, Any]:
        """Return additional state attributes."""
        attributes = {
            ATTR_ACCOUNT_ID: self._config.get("account_id"),
            ATTR_LOCATION_ID: self.location.id,
        }

        # Add last reading time if available
        if self.coordinator.data:
            last_reading = self.coordinator.data.get(self.location.id).get(ATTR_LAST_READING_TIME)
            if last_reading:
                attributes[ATTR_LAST_READING_TIME] = last_reading

        return attributes

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        account_id = self._config.get("account_id", "Unknown")
        host = self._config.get("host", "Unknown")

        return {
            "identifiers": {(DOMAIN, self._config_entry.unique_id or self._config_entry.entry_id)},
            "name": f"SmartHub Energy Monthly Usage ({account_id} - {self.location.description})",
            "manufacturer": "SmartHub Coop",
            "model": "Energy Monitor",
            "configuration_url": f"https://{host}",
        }
