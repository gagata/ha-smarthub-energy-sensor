import logging
from datetime import timedelta

from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity, DataUpdateCoordinator

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

async def async_setup_entry(hass, config_entry, async_add_entities):
    """Set up the sensor platform."""
    _LOGGER.debug("async_setup_entry called for SmartHub Energy Sensor")

    data = hass.data[DOMAIN][config_entry.entry_id]
    api = data["api"]
    poll_interval = data["poll_interval"]

    # Use the unique_id from the config_entry as the base for the sensor's unique_id.
    # If config_entry.unique_id is None (e.g., for older entries or failed config flow),
    # fall back to config_entry.entry_id which is guaranteed to be unique for the entry.
    base_unique_id = config_entry.unique_id
    if base_unique_id is None:
        _LOGGER.warning(
            "Config entry unique_id is None for %s. Falling back to entry_id. "
            "Consider deleting and re-adding the integration to get a proper unique_id.",
            config_entry.entry_id
        )
        base_unique_id = config_entry.entry_id # Fallback to a guaranteed unique string

    _LOGGER.debug(f"Base Unique ID for sensor: {base_unique_id}")

    # Create a coordinator to manage polling
    coordinator = DataUpdateCoordinator(
        hass,
        _LOGGER,
        name="SmartHub Energy",
        update_method=api.get_energy_data,
        update_interval=timedelta(minutes=poll_interval),
    )

    # Fetch initial data
    await coordinator.async_refresh()

    # Create and add the sensor
    sensors = [SmartHubEnergySensor(coordinator, base_unique_id)]
    async_add_entities(sensors)
    _LOGGER.debug("Sensor entities added.")


class SmartHubEnergySensor(CoordinatorEntity, Entity):
    """Representation of the SmartHub Energy sensor."""

    def __init__(self, coordinator, base_unique_id):
        """Initialize the sensor."""
        super().__init__(coordinator)
        self._base_unique_id = base_unique_id
        _LOGGER.debug(f"SmartHubEnergySensor initialized with base_unique_id: {self._base_unique_id}")

    @property
    def name(self):
        """Return the name of the sensor."""
        # You might want to make the name more dynamic based on parts of the unique ID
        # For instance, if you want to include the account ID in the name:
        # try:
        #     parts = self._base_unique_id.split('_')
        #     if len(parts) >= 3:
        #         return f"SmartHub Energy Sensor (Account: {parts[2]})"
        # except Exception:
        #     pass # Fallback to generic name if split fails
        return "SmartHub Energy Sensor"

    @property
    def unique_id(self):
        """Return a unique ID for this sensor."""
        # Combine the base_unique_id (from config_entry) with a sensor-specific identifier
        # This ensures the sensor itself has a unique ID within the Home Assistant instance.
        if not self._base_unique_id:
            _LOGGER.error("unique_id requested but _base_unique_id is None. This should not happen.")
            return None # Or raise an exception, though None is usually handled gracefully by HA

        return f"{self._base_unique_id}_energy_usage"

    @property
    def state(self):
        """Return the state of the sensor."""
        # Ensure that self.coordinator.data is not None before accessing it
        if self.coordinator.data is not None:
            return self.coordinator.data.get("current_energy_usage")

        _LOGGER.debug("Coordinator data is None or 'current_energy_usage' not found. Returning None for state.")
        return None # Return None if data is not available

    @property
    def extra_state_attributes(self):
        """Return additional attributes."""
        # 'unit_of_measurement' is now a direct property,
        # but you can add other relevant attributes from your API here if desired.
        attrs = {
            "icon": "mdi:power-plug",
            "device_class":"energy",
            "state_class":"total_increasing",
        }
        # Example: if your API provides other useful data, add it here
        # if self.coordinator.data:
        #     attrs["last_bill_date"] = self.coordinator.data.get("last_bill_date")
        #     attrs["total_billed_energy"] = self.coordinator.data.get("total_billed_energy")
        return attrs

    @property
    def unit_of_measurement(self):
        """Return the unit of measurement."""
        return "kWh"

    @property
    def device_info(self):
        """Return information about the device."""
        if not self._base_unique_id:
            _LOGGER.warning("base_unique_id is missing, cannot create device_info for sensor.")
            return None # Cannot create a device without a base identifier

        _LOGGER.debug(f"Attempting to parse device_info from base_unique_id: '{self._base_unique_id}'")

        host_name = "Unknown Host" # Default if host can't be extracted
        account_id_suffix = "Unknown Account" # Default if account ID can't be extracted
        configuration_url = None

        try:
            parts = self._base_unique_id.split('_')
            _LOGGER.debug(f"Parsed unique_id parts: {parts} (length: {len(parts)})")

            # Assuming the format is email_host_account_id (3 parts)
            if len(parts) >= 2:
                host_name = parts[1] # This is the host part
                if host_name: # Ensure it's not an empty string
                    configuration_url = f"https://{host_name}/" # Or just http:// depending on your hub
            if len(parts) >= 3:
                account_id_suffix = parts[2] # This is the account_id part

        except IndexError:
            _LOGGER.debug(f"Base unique ID '{self._base_unique_id}' does not have enough parts for detailed device_info parsing (IndexError).")
        except Exception as e:
            _LOGGER.warning(f"Error parsing base_unique_id '{self._base_unique_id}' for device_info: {e}")
            # Fallback for host_name and account_id_suffix if parsing fails
            host_name = "Parsing Error"
            account_id_suffix = "Parsing Error"

        _LOGGER.debug(f"Device Info - Host: {host_name}, Account Suffix: {account_id_suffix}, Config URL: {configuration_url}")

        return {
            "identifiers": {(DOMAIN, self._base_unique_id)},
            "name": f"{host_name} ({account_id_suffix})", # Naming the device with the account ID for clarity
            "manufacturer": "gagata",
            "model": "Energy Monitor",
            "configuration_url": configuration_url,
        }
