"""SmartHub energy sensor platform."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
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


def _as_utc_datetime(value):
    """Normalize HA statistic start (float epoch or datetime) to aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:  # milliseconds
            ts /= 1000.0
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    return value

from homeassistant.util.unit_conversion import EnergyConverter
from homeassistant.components.recorder.statistics import (
    async_add_external_statistics,
    get_last_statistics,
    statistics_during_period,
)
from homeassistant.components.recorder import get_instance
from homeassistant.components.recorder.models import (
    StatisticData,
    StatisticMetaData,
)

try:
    from homeassistant.components.recorder.models import StatisticMeanType
except ImportError:
    from enum import Enum
    class StatisticMeanType(str, Enum):
        NONE = "none"
        MEAN = "mean"
        MAX = "max"
        MIN = "min"


from .api import Aggregation, SmartHubAPI, SmartHubLocation
from .exceptions import (
    SmartHubAuthenticationError,
    SmartHubError as SmartHubAPIError,
)
from .const import (
    DOMAIN,
    ENERGY_SENSOR_KEY,
    ATTR_LAST_READING_TIME,
    ATTR_ACCOUNT_ID,
    ATTR_LOCATION_ID,
    LOCATION_KEY,
    HISTORICAL_IMPORT_DAYS,
    METER_NAME,
    METER_ID,
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

    # Ensure that it is the smartHub coordinator
    assert type(coordinator) is SmartHubDataUpdateCoordinator

    last_locations_consumption = coordinator.data.items()

    # Create sensor entities for each location+meter
    entities = []
    for entity_key, last_consumption in last_locations_consumption:
      entities.append(
          SmartHubEnergySensor(
              coordinator=coordinator,
              config_entry=config_entry,
              config=config,
              location=last_consumption.get(LOCATION_KEY),
              entity_key=entity_key,
              meter_id=last_consumption.get(METER_ID),
              meter_name=last_consumption.get(METER_NAME),
          )
      )

    async_add_entities(entities)
    _LOGGER.debug(f"{len(entities)} SmartHub sensor entities added successfully")


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
              await self._insert_statistics(location, Aggregation.HOURLY)
              await self._insert_statistics(location, Aggregation.DAILY)

              # Entity value = month-to-date kWh per meter.
              # Some coops (incl. SWCE) return empty MONTHLY series mid-cycle;
              # fall back to summing DAILY points for the current month.
              first_day_of_current_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

              data = await self.api.get_energy_data(
                  location=location,
                  start_datetime=first_day_of_current_month,
                  aggregation=Aggregation.MONTHLY,
              ) or {}
              meter_list = data.get("meters") or []
              if not meter_list and data.get("USAGE"):
                  meter_list = [{
                      "meter_id": str(location.id),
                      METER_NAME: data.get(METER_NAME) or location.description or str(location.id),
                      "USAGE": data.get("USAGE"),
                      "USAGE_RETURN": data.get("USAGE_RETURN"),
                  }]

              use_daily_sum = False
              if not meter_list:
                  _LOGGER.info(
                      "Monthly usage empty for %s; falling back to daily month-to-date totals",
                      location,
                  )
                  data = await self.api.get_energy_data(
                      location=location,
                      start_datetime=first_day_of_current_month,
                      aggregation=Aggregation.DAILY,
                  ) or {}
                  meter_list = data.get("meters") or []
                  if not meter_list and data.get("USAGE"):
                      meter_list = [{
                          "meter_id": str(location.id),
                          METER_NAME: data.get(METER_NAME) or location.description or str(location.id),
                          "USAGE": data.get("USAGE"),
                          "USAGE_RETURN": data.get("USAGE_RETURN"),
                      }]
                  use_daily_sum = True

              if not meter_list:
                  _LOGGER.warning("No data received from SmartHub API for location %s", location)
                  entity_key = f"{location.id}"
                  entity_response[entity_key] = {
                    ENERGY_SENSOR_KEY: 0,
                    ATTR_LAST_READING_TIME: first_day_of_current_month.replace(tzinfo=ZoneInfo(self.api.timezone)),
                    LOCATION_KEY: location,
                    METER_NAME: None,
                    METER_ID: str(location.id),
                  }
                  continue

              for meter in meter_list:
                  usage = meter.get("USAGE") or []
                  meter_id = str(meter.get("meter_id") or location.id)
                  meter_name = meter.get(METER_NAME) or meter_id
                  entity_key = f"{location.id}_{meter_id}"
                  if not usage:
                      _LOGGER.warning("No USAGE points for location %s meter %s", location, meter_id)
                      entity_response[entity_key] = {
                        ENERGY_SENSOR_KEY: 0,
                        ATTR_LAST_READING_TIME: first_day_of_current_month.replace(tzinfo=ZoneInfo(self.api.timezone)),
                        LOCATION_KEY: location,
                        METER_NAME: meter_name,
                        METER_ID: meter_id,
                      }
                      continue
                  last_reading = usage[-1]
                  if use_daily_sum:
                      month_total = sum(float(pt.get("consumption") or 0) for pt in usage)
                      value = month_total
                  else:
                      value = last_reading["consumption"]
                  _LOGGER.debug(
                      "Fetched data for location %s meter %s: value=%s last=%s daily_sum=%s",
                      location, meter_name, value, last_reading, use_daily_sum,
                  )
                  entity_response[entity_key] = {
                    ENERGY_SENSOR_KEY: value,
                    ATTR_LAST_READING_TIME: last_reading['reading_time'],
                    LOCATION_KEY: location,
                    METER_NAME: meter_name,
                    METER_ID: meter_id,
                  }

            return entity_response

        except SmartHubAuthenticationError as e:
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
    async def _insert_statistics(self, location, aggregation: Aggregation):
        """Backfill external statistics for each meter under a service location."""
        # Determine fetch window using legacy location statistic id when present,
        # otherwise a per-meter probe after we know meter ids.
        legacy_consumption_id = f"{DOMAIN}:smarthub_energy_sensor{aggregation.suffix}_{self.account_id}_{location.id}"
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, legacy_consumption_id, True, set()
        )

        if not last_stat:
            start_datetime = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=HISTORICAL_IMPORT_DAYS)
        else:
            start_datetime = datetime.fromtimestamp(last_stat[legacy_consumption_id][0]["start"], tz=timezone.utc) - timedelta(days=2)

        smarthub_data = await self.api.get_energy_data(location=location, aggregation=aggregation, start_datetime=start_datetime)
        meter_list = (smarthub_data or {}).get("meters") or []
        if not meter_list and smarthub_data and smarthub_data.get("USAGE"):
            meter_list = [{
                "meter_id": str(location.id),
                METER_NAME: smarthub_data.get(METER_NAME) or location.description or str(location.id),
                "USAGE": smarthub_data.get("USAGE"),
                "USAGE_RETURN": smarthub_data.get("USAGE_RETURN"),
            }]
        if not meter_list:
            _LOGGER.warning("No data received from SmartHub API for location %s to populate historical %s stats", location, aggregation.label)
            return

        for meter in meter_list:
            await self._insert_meter_statistics(location, aggregation, meter, start_datetime if last_stat else None)

    async def _insert_meter_statistics(self, location, aggregation: Aggregation, meter: Dict[str, Any], continue_from):
        """Write hourly/daily statistics for a single meter."""
        meter_id = str(meter.get("meter_id") or location.id)
        meter_name = meter.get(METER_NAME) or meter_id
        usage_points = meter.get("USAGE") or []
        if not usage_points:
            _LOGGER.warning("No USAGE history for location %s meter %s", location, meter_id)
            return

        # Sanitize meter id for statistic ids (keep digits/letters/_-)
        safe_meter = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in meter_id)

        consumption_statistic_id = f"{DOMAIN}:smarthub_energy_sensor{aggregation.suffix}_{self.account_id}_{location.id}_{safe_meter}"
        return_statistic_id = f"{DOMAIN}:smarthub_energy_return_sensor{aggregation.suffix}_{self.account_id}_{location.id}_{safe_meter}"
        # Also keep writing legacy location-only id for the first meter so existing Energy dashboard entries keep working
        legacy_consumption_id = f"{DOMAIN}:smarthub_energy_sensor{aggregation.suffix}_{self.account_id}_{location.id}"
        legacy_return_id = f"{DOMAIN}:smarthub_energy_return_sensor{aggregation.suffix}_{self.account_id}_{location.id}"

        consumption_unit_class = EnergyConverter.UNIT_CLASS
        consumption_unit = UnitOfEnergy.KILO_WATT_HOUR
        name_suffix = f"{self.account_id} - {meter_name}"
        consumption_metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{location.provider} SmartHub Energy {aggregation.label} Usage - {name_suffix}",
            source=DOMAIN,
            statistic_id=consumption_statistic_id,
            unit_class=consumption_unit_class,
            unit_of_measurement=consumption_unit,
        )
        return_metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{location.provider} SmartHub Energy {aggregation.label} Return - {name_suffix}",
            source=DOMAIN,
            statistic_id=return_statistic_id,
            unit_class=consumption_unit_class,
            unit_of_measurement=consumption_unit,
        )

        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, consumption_statistic_id, True, set()
        )
        if not last_stat:
            # Fall back to legacy location statistic for continuity on first meter
            last_stat = await get_instance(self.hass).async_add_executor_job(
                get_last_statistics, self.hass, 1, legacy_consumption_id, True, set()
            )
            if last_stat and legacy_consumption_id in last_stat:
                last_stat = {consumption_statistic_id: last_stat[legacy_consumption_id]}

        if not last_stat:
            consumption_sum = 0.0
            return_sum = 0.0
            last_stats_time = None
        else:
            start = usage_points[0].get("reading_time")
            stats = {}
            for end in (start + timedelta(seconds=1), None):
                stats = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass,
                    start,
                    end,
                    {consumption_statistic_id, return_statistic_id, legacy_consumption_id, legacy_return_id},
                    aggregation.period,
                    None,
                    {"sum"},
                )
                if stats:
                    break
            def _safe_get_sum(records: list) -> float:
                if records and "sum" in records[0]:
                    return float(records[0]["sum"])
                return 0.0
            # Prefer per-meter stats; else legacy
            if consumption_statistic_id in stats and stats[consumption_statistic_id]:
                consumption_sum = _safe_get_sum(stats.get(consumption_statistic_id, []))
                last_stats_time = _as_utc_datetime(stats[consumption_statistic_id][0]["start"])
            elif legacy_consumption_id in stats and stats[legacy_consumption_id]:
                consumption_sum = _safe_get_sum(stats.get(legacy_consumption_id, []))
                last_stats_time = _as_utc_datetime(stats[legacy_consumption_id][0]["start"])
            else:
                consumption_sum = 0.0
                last_stats_time = None
            return_sum = _safe_get_sum(stats.get(return_statistic_id, []) or stats.get(legacy_return_id, []))

        consumption_statistics = []
        return_statistics = []
        for reading in usage_points:
            start = _as_utc_datetime(reading["reading_time"])
            if last_stats_time is not None and start <= last_stats_time:
                continue
            consumption_sum += float(reading.get("consumption") or 0)
            consumption_statistics.append(
                StatisticData(start=start, state=float(reading.get("consumption") or 0), sum=consumption_sum)
            )
            if meter.get("USAGE_RETURN"):
                # paired by index when present on same meter dict as NET
                pass

        # Handle return series if present on this meter
        for reading in (meter.get("USAGE_RETURN") or []):
            start = _as_utc_datetime(reading["reading_time"])
            if last_stats_time is not None and start <= last_stats_time:
                continue
            return_state = float(reading.get("consumption") or 0)
            return_sum += return_state
            return_statistics.append(
                StatisticData(start=start, state=return_state, sum=return_sum)
            )

        _LOGGER.info("Adding %s statistics for %s", len(consumption_statistics), consumption_statistic_id)
        async_add_external_statistics(self.hass, consumption_metadata, consumption_statistics)
        if return_statistics:
            async_add_external_statistics(self.hass, return_metadata, return_statistics)


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
        entity_key: str,
        meter_id: str | None = None,
        meter_name: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self._config_entry = config_entry
        self._config = config
        self.location = location
        self._entity_key = entity_key
        self._meter_id = str(meter_id or location.id)
        self._meter_name = meter_name or self._meter_id
        # Include meter id so Main vs off-peak are distinct entities
        self._attr_unique_id = f"{config_entry.unique_id}_{location.id}_{self._meter_id}_energy"

        account_id = config.get("account_id", "Unknown")
        loc_label = self.location.description or "Electric"
        self._attr_name = (
            f"{self.location.provider} SmartHub Energy Monthly Usage - "
            f"{account_id} {loc_label} - {self._meter_name}"
        )

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

        value = self.coordinator.data.get(self._entity_key, {}).get(ENERGY_SENSOR_KEY, None)
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

        attributes[METER_ID] = self._meter_id
        attributes[METER_NAME] = self._meter_name

        # Add last reading time if available
        if self.coordinator.data and self._entity_key in self.coordinator.data:
            last_reading = self.coordinator.data.get(self._entity_key, {}).get(ATTR_LAST_READING_TIME)
            if last_reading:
                attributes[ATTR_LAST_READING_TIME] = last_reading

        return attributes

    @property
    def device_info(self) -> Dict[str, Any]:
        """Return device information."""
        account_id = self._config.get("account_id", "Unknown")
        host = self._config.get("host", "Unknown")

        return {
            "identifiers": {(DOMAIN, f"{self._config_entry.unique_id or self._config_entry.entry_id}_{self._meter_id}")},
            "name": f"{self.location.provider} SmartHub ({account_id} - {self._meter_name})",
            "manufacturer": "SmartHub Coop",
            "model": "Energy Monitor",
            "configuration_url": f"https://{host}",
        }
