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
from homeassistant.core import HomeAssistant, callback
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


def _meters_from_energy_data(data: Dict[str, Any] | None, location) -> list:
    """Return per-meter rows, synthesizing one legacy row from top-level USAGE."""
    meter_list = list((data or {}).get("meters") or [])
    if not meter_list and data and data.get("USAGE"):
        usage_return = data.get("USAGE_RETURN")
        meter_list = [{
            "meter_id": str(location.id),
            METER_NAME: data.get(METER_NAME) or location.description or str(location.id),
            "USAGE": data.get("USAGE"),
            "USAGE_RETURN": usage_return,
            LEGACY_USAGE_RETURN: usage_return,
            LEGACY_METER: True,
        }]
    if meter_list and not any(meter.get(LEGACY_METER) for meter in meter_list):
        meter_list[-1][LEGACY_METER] = True
    return meter_list


def _usages_empty(meter_list: list) -> bool:
    """True when every meter is missing consumption points (or there are no meters)."""
    if not meter_list:
        return True
    return all(not (meter.get("USAGE") or []) for meter in meter_list)


def _has_return_points(meter_list: list) -> bool:
    return any(
        (meter.get("USAGE_RETURN") or meter.get(LEGACY_USAGE_RETURN) or [])
        for meter in meter_list
    )


def entity_key_for_meter(location_id: str, meter: Dict[str, Any]) -> str:
    """Stable coordinator key.

    The legacy meter keeps the pre-per-meter location id so an entity created
    before meter ids were known keeps finding its data. Other meters use a
    normalized id that does not change between updates.
    """
    if meter.get(LEGACY_METER):
        return str(location_id)
    safe = normalize_meter_id(str(meter.get("meter_id") or location_id))
    return f"{location_id}_{safe}"


def _accumulate_statistics(readings, running_sum: float, last_time):
    """Build external statistic points strictly after ``last_time``."""
    total = running_sum
    statistics = []
    for reading in readings or []:
        start = _as_utc_datetime(reading["reading_time"])
        if last_time is not None and start <= last_time:
            continue
        value = float(reading.get("consumption") or 0)
        if value < 0:
            value = 0.0
        total += value
        statistics.append(StatisticData(start=start, state=value, sum=total))
    return statistics

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
    LEGACY_METER,
    LEGACY_USAGE_RETURN,
)
from .utils import normalize_meter_id

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

    known_keys: set[str] = set()

    def _new_entities() -> list[SmartHubEnergySensor]:
        """Create sensors for coordinator keys that do not have an entity yet."""
        entities: list[SmartHubEnergySensor] = []
        for entity_key, last_consumption in (coordinator.data or {}).items():
            if entity_key in known_keys or not isinstance(last_consumption, dict):
                continue
            location = last_consumption.get(LOCATION_KEY)
            if location is None:
                continue
            known_keys.add(entity_key)
            entities.append(
                SmartHubEnergySensor(
                    coordinator=coordinator,
                    config_entry=config_entry,
                    config=config,
                    location=location,
                    entity_key=str(entity_key),
                    meter_id=last_consumption.get(METER_ID),
                    meter_name=last_consumption.get(METER_NAME),
                    legacy=bool(last_consumption.get(LEGACY_METER)),
                )
            )
        return entities

    @callback
    def _async_add_new_meters() -> None:
        """Add meters that showed up after the platform was set up."""
        new_entities = _new_entities()
        if new_entities:
            async_add_entities(new_entities)

    config_entry.async_on_unload(coordinator.async_add_listener(_async_add_new_meters))
    _async_add_new_meters()
    _LOGGER.debug("SmartHub sensor platform ready (%s entities)", len(known_keys))


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
              # Some coops (incl. SWCE) return empty MONTHLY series mid-cycle,
              # including meters whose USAGE lists are empty. Fall back to
              # summing DAILY points for the current month.
              first_day_of_current_month = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)

              data = await self.api.get_energy_data(
                  location=location,
                  start_datetime=first_day_of_current_month,
                  aggregation=Aggregation.MONTHLY,
              ) or {}
              meter_list = _meters_from_energy_data(data, location)

              use_daily_sum = False
              if _usages_empty(meter_list):
                  _LOGGER.info(
                      "Monthly usage empty for %s; falling back to daily month-to-date totals",
                      location,
                  )
                  data = await self.api.get_energy_data(
                      location=location,
                      start_datetime=first_day_of_current_month,
                      aggregation=Aggregation.DAILY,
                  ) or {}
                  meter_list = _meters_from_energy_data(data, location)
                  use_daily_sum = True

              if _usages_empty(meter_list):
                  _LOGGER.warning("No data received from SmartHub API for location %s", location)
                  # Keep the location-id key used before per-meter sensors existed.
                  entity_response[str(location.id)] = {
                    ENERGY_SENSOR_KEY: 0,
                    ATTR_LAST_READING_TIME: first_day_of_current_month.replace(tzinfo=ZoneInfo(self.api.timezone)),
                    LOCATION_KEY: location,
                    METER_NAME: None,
                    METER_ID: str(location.id),
                    LEGACY_METER: True,
                  }
                  continue

              for meter in meter_list:
                  usage = meter.get("USAGE") or []
                  meter_id = str(meter.get("meter_id") or location.id)
                  meter_name = meter.get(METER_NAME) or meter_id
                  entity_key = entity_key_for_meter(location.id, meter)
                  if not usage:
                      _LOGGER.warning("No USAGE points for location %s meter %s", location, meter_id)
                      entity_response[entity_key] = {
                        ENERGY_SENSOR_KEY: 0,
                        ATTR_LAST_READING_TIME: first_day_of_current_month.replace(tzinfo=ZoneInfo(self.api.timezone)),
                        LOCATION_KEY: location,
                        METER_NAME: meter_name,
                        METER_ID: meter_id,
                        LEGACY_METER: bool(meter.get(LEGACY_METER)),
                      }
                      continue
                  last_reading = usage[-1]
                  if use_daily_sum:
                      value = sum(float(pt.get("consumption") or 0) for pt in usage)
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
                    LEGACY_METER: bool(meter.get(LEGACY_METER)),
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
        meter_list = _meters_from_energy_data(smarthub_data, location)
        if _usages_empty(meter_list) and not _has_return_points(meter_list):
            _LOGGER.warning("No data received from SmartHub API for location %s to populate historical %s stats", location, aggregation.label)
            return

        for meter in meter_list:
            await self._insert_meter_statistics(location, aggregation, meter)

    async def _async_sum_baseline(self, consumption_id: str, return_id: str, readings: list, aggregation: Aggregation):
        """Return ``(consumption_sum, return_sum, last_start)`` or None if the series is new."""
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, consumption_id, True, set()
        )
        if not last_stat or consumption_id not in last_stat:
            return None

        start = readings[0].get("reading_time") if readings else None
        if start is not None and not isinstance(start, datetime):
            start = _as_utc_datetime(start)

        stats = {}
        if start is not None:
            for end in (start + timedelta(seconds=1), None):
                stats = await get_instance(self.hass).async_add_executor_job(
                    statistics_during_period,
                    self.hass,
                    start,
                    end,
                    {consumption_id, return_id},
                    aggregation.period,
                    None,
                    {"sum"},
                )
                if stats and stats.get(consumption_id):
                    break

        def _safe_get_sum(records: list) -> float:
            if records and "sum" in records[0]:
                return float(records[0]["sum"])
            return 0.0

        if stats and stats.get(consumption_id):
            return (
                _safe_get_sum(stats.get(consumption_id, [])),
                _safe_get_sum(stats.get(return_id, [])),
                _as_utc_datetime(stats[consumption_id][0]["start"]),
            )

        record = last_stat[consumption_id][0]
        return (float(record.get("sum") or 0.0), 0.0, _as_utc_datetime(record.get("start")))

    async def _insert_meter_statistics(self, location, aggregation: Aggregation, meter: Dict[str, Any]):
        """Write hourly/daily statistics for a single meter."""
        meter_id = str(meter.get("meter_id") or location.id)
        meter_name = meter.get(METER_NAME) or meter_id
        usage_points = meter.get("USAGE") or []
        return_points = meter.get("USAGE_RETURN") or []
        if LEGACY_USAGE_RETURN in meter:
            legacy_return_points = meter.get(LEGACY_USAGE_RETURN) or []
        else:
            legacy_return_points = return_points
        if not usage_points and not return_points and not legacy_return_points:
            _LOGGER.warning("No USAGE history for location %s meter %s", location, meter_id)
            return

        # Lowercase and strip characters Home Assistant rejects in statistic ids.
        safe_meter = normalize_meter_id(meter_id)
        is_legacy = bool(meter.get(LEGACY_METER))

        consumption_statistic_id = f"{DOMAIN}:smarthub_energy_sensor{aggregation.suffix}_{self.account_id}_{location.id}_{safe_meter}"
        return_statistic_id = f"{DOMAIN}:smarthub_energy_return_sensor{aggregation.suffix}_{self.account_id}_{location.id}_{safe_meter}"
        # Location-only ids are what existing Energy dashboards already track.
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

        readings_for_baseline = usage_points or return_points or legacy_return_points
        per_meter_baseline = await self._async_sum_baseline(
            consumption_statistic_id, return_statistic_id, readings_for_baseline, aggregation
        )
        legacy_baseline = None
        if is_legacy:
            legacy_baseline = await self._async_sum_baseline(
                legacy_consumption_id, legacy_return_id, readings_for_baseline, aggregation
            )

        # Seed a brand-new per-meter series from the legacy sum so the first
        # import does not restart the running total at zero.
        used = per_meter_baseline or legacy_baseline or (0.0, 0.0, None)
        consumption_statistics = _accumulate_statistics(usage_points, used[0], used[2])
        return_statistics = _accumulate_statistics(return_points, used[1], used[2])

        if consumption_statistics:
            _LOGGER.info("Adding %s statistics for %s", len(consumption_statistics), consumption_statistic_id)
            async_add_external_statistics(self.hass, consumption_metadata, consumption_statistics)
        if return_statistics:
            _LOGGER.info("Adding %s return statistics for %s", len(return_statistics), return_statistic_id)
            async_add_external_statistics(self.hass, return_metadata, return_statistics)

        if not is_legacy:
            return

        if legacy_baseline and legacy_baseline != used:
            legacy_consumption = _accumulate_statistics(usage_points, legacy_baseline[0], legacy_baseline[2])
            legacy_return = _accumulate_statistics(legacy_return_points, legacy_baseline[1], legacy_baseline[2])
        else:
            legacy_consumption = consumption_statistics
            # Same baseline: rebuild return points when the legacy series is a
            # different RETURN channel than this meter's own export series.
            if legacy_return_points is return_points:
                legacy_return = return_statistics
            else:
                legacy_return = _accumulate_statistics(legacy_return_points, used[1], used[2])

        description = location.description if location.description != "" else meter_name
        legacy_name = f"{self.account_id} - {description}"
        legacy_consumption_metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{location.provider} SmartHub Energy {aggregation.label} Usage - {legacy_name}",
            source=DOMAIN,
            statistic_id=legacy_consumption_id,
            unit_class=consumption_unit_class,
            unit_of_measurement=consumption_unit,
        )
        legacy_return_metadata = StatisticMetaData(
            mean_type=StatisticMeanType.NONE,
            has_sum=True,
            name=f"{location.provider} SmartHub Energy {aggregation.label} Return - {legacy_name}",
            source=DOMAIN,
            statistic_id=legacy_return_id,
            unit_class=consumption_unit_class,
            unit_of_measurement=consumption_unit,
        )
        if legacy_consumption:
            _LOGGER.info("Adding %s statistics for %s", len(legacy_consumption), legacy_consumption_id)
            async_add_external_statistics(self.hass, legacy_consumption_metadata, legacy_consumption)
        if legacy_return:
            _LOGGER.info("Adding %s return statistics for %s", len(legacy_return), legacy_return_id)
            async_add_external_statistics(self.hass, legacy_return_metadata, legacy_return)


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
        legacy: bool = False,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self._config_entry = config_entry
        self._config = config
        self.location = location
        self._entity_key = entity_key
        self._meter_id = str(meter_id or location.id)
        self._meter_name = meter_name or self._meter_id
        # The pre-per-meter entity is keyed only by location. Keep that unique
        # id so existing registry entries, dashboards, and automations stay put.
        # A key equal to the location id is that same entity even if it was
        # created while the first update had no meter list yet.
        self._legacy = legacy or entity_key == str(location.id)
        account_id = config.get("account_id", "Unknown")
        if self._legacy:
            self._attr_unique_id = f"{config_entry.unique_id}_{location.id}_energy"
            self._attr_name = (
                f"{self.location.provider} SmartHub Energy Monthly Usage - "
                f"{account_id} {self.location.description}"
            )
        else:
            safe_meter = normalize_meter_id(self._meter_id)
            self._attr_unique_id = f"{config_entry.unique_id}_{location.id}_{safe_meter}_energy"
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

        reading = {}
        if self.coordinator.data:
            reading = self.coordinator.data.get(self._entity_key) or {}

        # Prefer the latest coordinator payload so a sensor created before the
        # meter id was known picks up the real meter once data arrives.
        meter_id = reading.get(METER_ID) or self._meter_id
        meter_name = reading.get(METER_NAME) or self._meter_name
        if meter_id:
            attributes[METER_ID] = meter_id
        if meter_name:
            attributes[METER_NAME] = meter_name

        last_reading = reading.get(ATTR_LAST_READING_TIME)
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
            "name": f"{self.location.provider} SmartHub Energy Monthly Usage ({account_id} - {self.location.description})",
            "manufacturer": "SmartHub Coop",
            "model": "Energy Monitor",
            "configuration_url": f"https://{host}",
        }
