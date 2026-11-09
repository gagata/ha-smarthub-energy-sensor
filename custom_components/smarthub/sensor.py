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


def _raw_meter_id(meter: Dict[str, Any], location_id: str) -> str:
    """Return the meter id string used for keys, matching previous falsy handling."""
    return str(meter.get("meter_id") or location_id)


def _fragments_for_meters(
    meters: list,
    location_id: str,
    saved: dict[str, str] | None = None,
) -> dict[str, str]:
    """Unique statistic fragments for the meters in one response."""
    return assign_unique_meter_fragments(
        (_raw_meter_id(meter, location_id) for meter in meters),
        saved=saved,
    )


def _fill_empty_usage_from_daily(monthly_meters: list, daily_meters: list) -> list[tuple[dict, bool]]:
    """Pair each monthly meter with whether its value is a sum of daily points.

    Meters that already have monthly usage keep those points. A meter whose
    monthly usage is empty takes the daily points of the same meter id when
    that series has readings, so one populated meter does not force the
    others to stay at zero.
    """
    daily_by_id: dict[str, dict] = {}
    for meter in daily_meters:
        daily_by_id.setdefault(str(meter.get("meter_id") or ""), meter)

    paired: list[tuple[dict, bool]] = []
    for meter in monthly_meters:
        if meter.get("USAGE"):
            paired.append((meter, False))
            continue
        daily_usage = (daily_by_id.get(str(meter.get("meter_id") or "")) or {}).get("USAGE") or []
        if not daily_usage:
            paired.append((meter, False))
            continue
        filled = dict(meter)
        filled["USAGE"] = daily_usage
        paired.append((filled, True))
    return paired


def entity_key_for_meter(
    location_id: str,
    meter: Dict[str, Any],
    fragments: dict[str, str] | None = None,
) -> str:
    """Stable coordinator key.

    The legacy meter keeps the pre-per-meter location id so an entity created
    before meter ids were known keeps finding its data. Other meters use a
    normalized id that does not change between updates. Colliding normalized
    ids get the disambiguated fragment so two meters do not share a key.
    """
    if meter.get(LEGACY_METER):
        return str(location_id)
    raw = _raw_meter_id(meter, location_id)
    safe = (fragments or {}).get(raw) or normalize_meter_id(raw)
    return f"{location_id}_{safe}"


def _is_later(left: datetime, right: datetime) -> bool:
    """Return True when ``left`` is strictly after ``right``.

    Naive values are read in the system local zone, the same way
    ``datetime.now()`` is. Aware values compare as absolute instants.
    """
    def _timestamp(value: datetime) -> float:
        if value.tzinfo is None:
            return value.timestamp()
        return value.astimezone(timezone.utc).timestamp()

    return _timestamp(left) > _timestamp(right)


def _statistic_id(
    kind: str,
    account_id: str,
    location_id: str,
    suffix: str,
    fragment: str | None = None,
) -> str:
    """Build an external statistic id, optionally scoped to one meter."""
    statistic_id = f"{DOMAIN}:{kind}{suffix}_{account_id}_{location_id}"
    if fragment:
        statistic_id = f"{statistic_id}_{fragment}"
    return statistic_id


# Re-import this much history before the newest stored point so a utility
# correction inside the fetch overlap replaces the stored row.
_STATISTIC_OVERLAP = timedelta(days=2)

def _accumulate_statistics(readings, running_sum: float, reimport_from):
    """Build statistic points from ``reimport_from`` onward.

    ``running_sum`` is the cumulative sum just before the first point that
    will be written. Passing ``None`` for ``reimport_from`` imports every
    reading, which is a series that has no stored history yet. Points before
    ``reimport_from`` stay as they are, so older totals are not added twice.
    """
    total = running_sum
    statistics = []
    ordered = sorted(
        readings or [],
        key=lambda reading: _as_utc_datetime(reading["reading_time"]) or datetime.min.replace(tzinfo=timezone.utc),
    )
    for reading in ordered:
        start = _as_utc_datetime(reading["reading_time"])
        if start is None:
            continue
        if reimport_from is not None and start < reimport_from:
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
from homeassistant.helpers.storage import Store
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
from .utils import assign_unique_meter_fragments, normalize_meter_id

_LOGGER = logging.getLogger(__name__)
# Coordinator field: disambiguated statistic fragment for this meter's raw id.
_METER_FRAGMENT = "meter_fragment"
# Storage key suffix. The config entry id is appended so accounts do not share a map.
_METER_FRAGMENT_STORE = "meter_fragments"


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
                    meter_fragment=last_consumption.get(_METER_FRAGMENT),
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
        self.config_entry = config_entry
        self.account_id = config_entry.data.get('account_id','unknown')
        self._meter_fragments: dict[str, str] = {}
        self._fragments_loaded = False
        entry_id = getattr(config_entry, "entry_id", None) or "unknown"
        self._fragment_store = Store(
            hass,
            1,
            f"{DOMAIN}_{_METER_FRAGMENT_STORE}_{entry_id}",
        )

    async def _async_load_fragments(self) -> None:
        """Load persisted meter fragments once per coordinator lifetime."""
        if self._fragments_loaded:
            return
        self._fragments_loaded = True
        stored = await self._fragment_store.async_load()
        if not isinstance(stored, dict):
            return
        raw = stored.get("fragments") or {}
        if isinstance(raw, dict):
            self._meter_fragments = {
                str(key): str(fragment)
                for key, fragment in raw.items()
                if fragment
            }

    def _saved_fragments_for_location(self, location_id: str) -> dict[str, str]:
        """Return raw meter id -> fragment already given out at this location."""
        prefix = f"{location_id}:"
        return {
            key[len(prefix):]: fragment
            for key, fragment in self._meter_fragments.items()
            if key.startswith(prefix)
        }

    async def _assign_fragments(self, location_id: str, meters: list) -> dict[str, str]:
        """Assign fragments, keeping any id this location has already published."""
        await self._async_load_fragments()
        saved = self._saved_fragments_for_location(location_id)
        assigned = _fragments_for_meters(meters, location_id, saved)
        changed = False
        for raw, fragment in assigned.items():
            key = f"{location_id}:{raw}"
            if self._meter_fragments.get(key) != fragment:
                self._meter_fragments[key] = fragment
                changed = True
        if changed:
            await self._fragment_store.async_save({"fragments": self._meter_fragments})
        return assigned

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the SmartHub API."""
        try:
            _LOGGER.debug("Fetching data from SmartHub API")
            await self._async_load_fragments()

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
                  paired = [(meter, True) for meter in meter_list]
              elif any(not (meter.get("USAGE") or []) for meter in meter_list):
                  empty_ids = [
                      str(meter.get("meter_id") or location.id)
                      for meter in meter_list
                      if not (meter.get("USAGE") or [])
                  ]
                  _LOGGER.info(
                      "Monthly usage empty for meter(s) %s at %s; falling back to daily totals for those meters",
                      ", ".join(empty_ids),
                      location,
                  )
                  daily = await self.api.get_energy_data(
                      location=location,
                      start_datetime=first_day_of_current_month,
                      aggregation=Aggregation.DAILY,
                  ) or {}
                  paired = _fill_empty_usage_from_daily(
                      meter_list, _meters_from_energy_data(daily, location)
                  )
              else:
                  paired = [(meter, False) for meter in meter_list]

              if _usages_empty([meter for meter, _use_daily in paired]):
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

              fragments = await self._assign_fragments(
                  location.id, [meter for meter, _use_daily in paired]
              )
              for meter, use_daily_sum in paired:
                  usage = meter.get("USAGE") or []
                  meter_id = _raw_meter_id(meter, location.id)
                  meter_name = meter.get(METER_NAME) or meter_id
                  fragment = fragments.get(meter_id) or normalize_meter_id(meter_id)
                  entity_key = entity_key_for_meter(location.id, meter, fragments)
                  legacy = bool(meter.get(LEGACY_METER))
                  if not usage:
                      _LOGGER.warning("No USAGE points for location %s meter %s", location, meter_id)
                      value = 0
                      last_time = first_day_of_current_month.replace(tzinfo=ZoneInfo(self.api.timezone))
                  else:
                      last_reading = usage[-1]
                      if use_daily_sum:
                          value = sum(float(pt.get("consumption") or 0) for pt in usage)
                      else:
                          value = last_reading["consumption"]
                      last_time = last_reading["reading_time"]
                      _LOGGER.debug(
                          "Fetched data for location %s meter %s: value=%s last=%s daily_sum=%s",
                          location, meter_name, value, last_reading, use_daily_sum,
                      )
                  entity_response[entity_key] = {
                    ENERGY_SENSOR_KEY: value,
                    ATTR_LAST_READING_TIME: last_time,
                    LOCATION_KEY: location,
                    METER_NAME: meter_name,
                    METER_ID: meter_id,
                    LEGACY_METER: legacy,
                    _METER_FRAGMENT: fragment,
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
    async def _last_statistic_start(self, statistic_id: str):
        """Return the newest start for ``statistic_id``, or None when it has no points."""
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, set()
        )
        if not last_stat or not last_stat.get(statistic_id):
            return None
        return _as_utc_datetime(last_stat[statistic_id][0].get("start"))

    async def _meters_missing_statistics(
        self,
        location,
        aggregation: Aggregation,
        meters: list,
        fragments: dict[str, str],
        *,
        protect_legacy: bool,
    ) -> set[str]:
        """Return raw ids that still have no per-meter consumption or return series.

        The legacy meter is skipped when legacy statistics already exist. Its
        per-meter series continues that running sum instead of replaying the
        historical window on top of it.
        """
        missing: set[str] = set()
        for meter in meters:
            raw = _raw_meter_id(meter, location.id)
            if protect_legacy and meter.get(LEGACY_METER):
                continue
            fragment = fragments.get(raw) or normalize_meter_id(raw)
            consumption_id = _statistic_id(
                "smarthub_energy_sensor", self.account_id, str(location.id), aggregation.suffix, fragment
            )
            return_id = _statistic_id(
                "smarthub_energy_return_sensor", self.account_id, str(location.id), aggregation.suffix, fragment
            )
            if (
                await self._last_statistic_start(consumption_id) is None
                and await self._last_statistic_start(return_id) is None
            ):
                missing.add(raw)
        return missing

    async def _insert_statistics(self, location, aggregation: Aggregation):
        """Backfill external statistics for each meter under a service location.

        Legacy statistics only choose the short update window. A meter that
        does not yet have its own series still imports ``HISTORICAL_IMPORT_DAYS``
        so older history is not dropped just because another meter was already
        tracked. Meters that already have statistics stay on the short window
        and are not rewritten from that older fetch.
        """
        legacy_consumption_id = _statistic_id(
            "smarthub_energy_sensor", self.account_id, str(location.id), aggregation.suffix
        )
        legacy_start = await self._last_statistic_start(legacy_consumption_id)
        full_start = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=HISTORICAL_IMPORT_DAYS)
        if legacy_start is None:
            window_start = full_start
        else:
            window_start = legacy_start - timedelta(days=2)

        recent = await self.api.get_energy_data(
            location=location, aggregation=aggregation, start_datetime=window_start
        )
        recent_by_id: dict[str, dict] = {}
        for meter in _meters_from_energy_data(recent, location):
            recent_by_id.setdefault(_raw_meter_id(meter, location.id), meter)
        meter_list = list(recent_by_id.values())
        full_by_id: dict[str, dict] = {}
        # A legacy series makes the shared window start two days before its
        # latest point. That is narrower than the first-import window, and it
        # would hide older points for a meter that has no statistics yet.
        narrow = legacy_start is not None and _is_later(window_start, full_start)
        if narrow:
            fragments = await self._assign_fragments(location.id, meter_list)
            needs_full = await self._meters_missing_statistics(
                location, aggregation, meter_list, fragments, protect_legacy=True
            )
            if needs_full:
                full = await self.api.get_energy_data(
                    location=location, aggregation=aggregation, start_datetime=full_start
                )
                for meter in _meters_from_energy_data(full, location):
                    raw = _raw_meter_id(meter, location.id)
                    full_by_id.setdefault(raw, meter)
                    if raw not in recent_by_id:
                        meter_list.append(full_by_id[raw])
                fragments = await self._assign_fragments(location.id, meter_list)
                needs_full = await self._meters_missing_statistics(
                    location, aggregation, meter_list, fragments, protect_legacy=True
                )
                if needs_full:
                    _LOGGER.info(
                        "Importing full %s history for new meter(s) %s at %s",
                        aggregation.label,
                        ", ".join(sorted(needs_full)),
                        location,
                    )
        else:
            fragments = await self._assign_fragments(location.id, meter_list)
            needs_full = set()

        if _usages_empty(meter_list) and not _has_return_points(meter_list):
            _LOGGER.warning("No data received from SmartHub API for location %s to populate historical %s stats", location, aggregation.label)
            return

        seen: set[str] = set()
        for meter in meter_list:
            raw = _raw_meter_id(meter, location.id)
            if raw in seen:
                continue
            seen.add(raw)
            recent_meter = recent_by_id.get(raw)
            if raw in needs_full:
                source = full_by_id.get(raw) or recent_meter or meter
            else:
                # Keep the short window for series that already exist so the
                # long fetch cannot rewrite their points.
                source = recent_meter or meter
            if recent_meter is not None:
                write_legacy = bool(recent_meter.get(LEGACY_METER))
            else:
                # Only present in the backfill. Do not append its history onto
                # the location statistic another meter already owns.
                write_legacy = False
            fragment = fragments.get(raw) or normalize_meter_id(raw)
            await self._insert_meter_statistics(
                location, aggregation, source, fragment, write_legacy=write_legacy
            )

    async def _async_last_record(self, statistic_id: str) -> dict | None:
        """Return the newest stored row for one statistic id, or None."""
        last_stat = await get_instance(self.hass).async_add_executor_job(
            get_last_statistics, self.hass, 1, statistic_id, True, {"sum", "state"}
        )
        if not last_stat or not last_stat.get(statistic_id):
            return None
        return last_stat[statistic_id][0]

    async def _async_statistics_between(self, statistic_id: str, start: datetime, end: datetime) -> list:
        """Return hourly statistic rows in ``[start, end)``."""
        rows = await get_instance(self.hass).async_add_executor_job(
            statistics_during_period,
            self.hass,
            start,
            end,
            {statistic_id},
            "hour",
            None,
            {"sum", "state"},
        )
        return list((rows or {}).get(statistic_id) or [])

    async def _async_reimport_plan(
        self,
        statistic_id: str,
        readings: list,
        seed_id: str | None = None,
    ) -> tuple[float, datetime | None]:
        """Return ``(sum_before_first_rewrite, reimport_from)`` for one series.

        Consumption and return are planned separately. A return reading is
        therefore not dropped just because consumption already has that
        timestamp. Inside the overlap, stored rows are rewritten from the
        sum just before the first rewritten reading, so a corrected value
        replaces the old one instead of being added on top of it.
        """
        source_id = statistic_id
        last = await self._async_last_record(statistic_id)
        if last is None and seed_id:
            seeded = await self._async_last_record(seed_id)
            if seeded is not None:
                source_id = seed_id
                last = seeded
        if last is None:
            return (0.0, None)

        last_start = _as_utc_datetime(last.get("start"))
        if last_start is None:
            return (0.0, None)
        overlap_start = last_start - _STATISTIC_OVERLAP
        candidates = []
        for reading in readings or []:
            start = _as_utc_datetime(reading.get("reading_time"))
            if start is not None and start >= overlap_start:
                candidates.append(start)
        if not candidates:
            # Nothing in the overlap to append or correct.
            return (float(last.get("sum") or 0.0), last_start + timedelta(microseconds=1))

        first = min(candidates)
        earlier = await self._async_statistics_between(
            source_id,
            first - timedelta(days=HISTORICAL_IMPORT_DAYS + _STATISTIC_OVERLAP.days),
            first,
        )
        if earlier:
            return (float(earlier[-1].get("sum") or 0.0), first)

        at_first = await self._async_statistics_between(
            source_id, first, first + timedelta(seconds=1)
        )
        if at_first:
            stored_sum = float(at_first[0].get("sum") or 0.0)
            stored_state = float(at_first[0].get("state") or 0.0)
            # No earlier row. The stored sum still includes history that this
            # point does not repeat, so continue from sum-before-this-point.
            return (stored_sum - stored_state, first)
        return (0.0, first)

    async def _insert_meter_statistics(
        self,
        location,
        aggregation: Aggregation,
        meter: Dict[str, Any],
        fragment: str,
        *,
        write_legacy: bool,
    ):
        """Write hourly/daily statistics for a single meter."""
        meter_id = _raw_meter_id(meter, location.id)
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
        # ``fragment`` is already unique among the meters in this update.
        safe_meter = fragment or normalize_meter_id(meter_id)
        is_legacy = write_legacy

        consumption_statistic_id = _statistic_id(
            "smarthub_energy_sensor", self.account_id, str(location.id), aggregation.suffix, safe_meter
        )
        return_statistic_id = _statistic_id(
            "smarthub_energy_return_sensor", self.account_id, str(location.id), aggregation.suffix, safe_meter
        )
        # Location-only ids are what existing Energy dashboards already track.
        legacy_consumption_id = _statistic_id(
            "smarthub_energy_sensor", self.account_id, str(location.id), aggregation.suffix
        )
        legacy_return_id = _statistic_id(
            "smarthub_energy_return_sensor", self.account_id, str(location.id), aggregation.suffix
        )

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

        # A brand-new per-meter series continues the legacy running sum so the
        # first import does not restart at zero. Each channel keeps its own
        # cursor: a return point is not skipped because consumption is ahead.
        seed_consumption = legacy_consumption_id if is_legacy else None
        seed_return = legacy_return_id if is_legacy else None
        consumption_sum, consumption_from = await self._async_reimport_plan(
            consumption_statistic_id, usage_points, seed_consumption
        )
        return_sum, return_from = await self._async_reimport_plan(
            return_statistic_id, return_points, seed_return
        )
        consumption_statistics = _accumulate_statistics(usage_points, consumption_sum, consumption_from)
        return_statistics = _accumulate_statistics(return_points, return_sum, return_from)

        if consumption_statistics:
            _LOGGER.info("Adding %s statistics for %s", len(consumption_statistics), consumption_statistic_id)
            async_add_external_statistics(self.hass, consumption_metadata, consumption_statistics)
        if return_statistics:
            _LOGGER.info("Adding %s return statistics for %s", len(return_statistics), return_statistic_id)
            async_add_external_statistics(self.hass, return_metadata, return_statistics)

        if not is_legacy:
            return

        legacy_consumption_sum, legacy_consumption_from = await self._async_reimport_plan(
            legacy_consumption_id, usage_points
        )
        legacy_return_sum, legacy_return_from = await self._async_reimport_plan(
            legacy_return_id, legacy_return_points
        )
        legacy_consumption = _accumulate_statistics(
            usage_points, legacy_consumption_sum, legacy_consumption_from
        )
        legacy_return = _accumulate_statistics(
            legacy_return_points, legacy_return_sum, legacy_return_from
        )

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
        meter_fragment: str | None = None,
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)

        self._config_entry = config_entry
        self._config = config
        self.location = location
        self._entity_key = entity_key
        self._meter_id = str(meter_id or location.id)
        self._meter_name = meter_name or self._meter_id
        self._meter_fragment = meter_fragment
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
            safe_meter = self._meter_fragment or normalize_meter_id(self._meter_id)
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
