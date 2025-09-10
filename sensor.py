"""SmartHub energy sensor platform."""
from __future__ import annotations

import logging
from datetime import timedelta
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

from .api import SmartHubAPI, SmartHubAPIError, SmartHubAuthError
from .const import (
    DOMAIN,
    ENERGY_SENSOR_KEY,
    ATTR_LAST_READING_TIME,
    ATTR_ACCOUNT_ID,
    ATTR_LOCATION_ID,
)

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up the SmartHub sensor platform."""
    _LOGGER.debug("Setting up SmartHub sensor platform")

    data = hass.data[DOMAIN][config_entry.entry_id]
    api: SmartHubAPI = data["api"]
    poll_interval: int = data["poll_interval"]
    config: Dict[str, Any] = data["config"]

    # Create update coordinator
    coordinator = SmartHubDataUpdateCoordinator(
        hass=hass,
        api=api,
        update_interval=timedelta(minutes=poll_interval),
        entry_id=config_entry.entry_id,
    )

    # Fetch initial data
    await coordinator.async_config_entry_first_refresh()

    # Store coordinator reference for services
    hass.data[DOMAIN][config_entry.entry_id]["coordinator"] = coordinator

    # Create sensor entities
    entities = [
        SmartHubEnergySensor(
            coordinator=coordinator,
            config_entry=config_entry,
            config=config,
        )
    ]

    async_add_entities(entities, update_before_add=True)
    _LOGGER.debug("SmartHub sensor entities added successfully")


class SmartHubDataUpdateCoordinator(DataUpdateCoordinator):
    """Class to manage fetching SmartHub data."""

    def __init__(
        self,
        hass: HomeAssistant,
        api: SmartHubAPI,
        update_interval: timedelta,
        entry_id: str,
    ) -> None:
        """Initialize the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry_id}",
            update_interval=update_interval,
        )
        self.api = api

    async def _async_update_data(self) -> Dict[str, Any]:
        """Fetch data from the SmartHub API."""
        try:
            _LOGGER.debug("Fetching data from SmartHub API")
            data = await self.api.get_energy_data()
            
            if data is None:
                _LOGGER.warning("No data received from SmartHub API")
                # Return previous data if available, otherwise empty dict
                return self.data or {}
            
            _LOGGER.debug("Successfully fetched data: %s", data)
            return data
            
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
    ) -> None:
        """Initialize the sensor."""
        super().__init__(coordinator)
        
        self._config_entry = config_entry
        self._config = config
        self._attr_unique_id = f"{config_entry.unique_id}_energy"
        
        # Extract account info for naming
        account_id = config.get("account_id", "Unknown")
        host = config.get("host", "SmartHub")
        
        self._attr_name = f"SmartHub Energy {account_id}"
        
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
            
        value = self.coordinator.data.get(ENERGY_SENSOR_KEY)
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
            ATTR_LOCATION_ID: self._config.get("location_id"),
        }
        
        # Add last reading time if available
        if self.coordinator.data:
            last_reading = self.coordinator.data.get(ATTR_LAST_READING_TIME)
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
            "name": f"SmartHub Energy Monitor ({account_id})",
            "manufacturer": "SmartHub Coop",
            "model": "Energy Monitor",
            "configuration_url": f"https://{host}",
        }
