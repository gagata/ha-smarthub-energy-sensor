"""The SmartHub integration."""
from __future__ import annotations

import logging
from typing import Dict, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryError
from homeassistant.helpers import entity_registry
import voluptuous as vol

from .api import SmartHubAPI
from .const import DOMAIN, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

# Service schemas
SERVICE_REFRESH_DATA = "refresh_data"
SERVICE_REFRESH_AUTH = "refresh_authentication"

SERVICE_REFRESH_DATA_SCHEMA = vol.Schema({
    vol.Required("entity_id"): str,
})

SERVICE_REFRESH_AUTH_SCHEMA = vol.Schema({
    vol.Required("entity_id"): str,
})


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartHub from a config entry."""
    config = entry.data

    # Validate required configuration
    required_fields = ["email", "password", "account_id", "location_id", "host"]
    missing_fields = [field for field in required_fields if not config.get(field)]
    
    if missing_fields:
        _LOGGER.error("Missing required configuration fields: %s", missing_fields)
        raise ConfigEntryError(f"Missing configuration fields: {missing_fields}")

    # Initialize the API object
    api = SmartHubAPI(
        email=config["email"],
        password=config["password"],
        account_id=config["account_id"],
        location_id=config["location_id"],
        host=config["host"],
    )

    # Test the connection
    try:
        await api.get_token()
        _LOGGER.info("Successfully connected to SmartHub API")
    except Exception as e:
        _LOGGER.error("Failed to connect to SmartHub API: %s", e)
        await api.close()
        raise ConfigEntryError(f"Cannot connect to SmartHub: {e}") from e

    # Store the API instance and configuration in hass.data
    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "api": api,
        "poll_interval": config.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL),
        "config": config,
    }

    _LOGGER.debug("Stored SmartHub API instance for entry %s", entry.entry_id)

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    
    # Register services with unique names per entry to avoid conflicts
    service_refresh_data = f"{SERVICE_REFRESH_DATA}_{entry.entry_id}"
    service_refresh_auth = f"{SERVICE_REFRESH_AUTH}_{entry.entry_id}"
    
    async def handle_refresh_data(call: ServiceCall):
        """Handle the refresh_data service call."""
        entity_id = call.data["entity_id"]
        _LOGGER.info("Manual refresh requested for entity: %s", entity_id)
        
        # Find the coordinator for this entity
        ent_reg = entity_registry.async_get(hass)
        entity_entry = ent_reg.async_get(entity_id)
        
        if entity_entry and entity_entry.config_entry_id == entry.entry_id:
            # Trigger refresh for the coordinator
            coordinator = hass.data[DOMAIN][entry.entry_id].get("coordinator")
            if coordinator:
                await coordinator.async_request_refresh()
                _LOGGER.info("Refresh completed for entity: %s", entity_id)
            else:
                _LOGGER.error("No coordinator found for entity: %s", entity_id)
        else:
            _LOGGER.error("Entity not found or not part of SmartHub integration: %s", entity_id)

    async def handle_refresh_auth(call: ServiceCall):
        """Handle the refresh_authentication service call."""
        entity_id = call.data["entity_id"]
        _LOGGER.info("Authentication refresh requested for entity: %s", entity_id)
        
        # Force authentication refresh
        api = hass.data[DOMAIN][entry.entry_id]["api"]
        try:
            await api._refresh_authentication()
            _LOGGER.info("Authentication refresh completed for entity: %s", entity_id)
        except Exception as e:
            _LOGGER.error("Failed to refresh authentication for entity %s: %s", entity_id, e)

    # Register services only if this is the first SmartHub entry
    existing_entries = [e for e in hass.config_entries.async_entries(DOMAIN) if e.state.recoverable]
    if len(existing_entries) == 1:  # This is the first entry
        try:
            hass.services.async_register(
                DOMAIN, SERVICE_REFRESH_DATA, handle_refresh_data, schema=SERVICE_REFRESH_DATA_SCHEMA
            )
            _LOGGER.debug("Registered refresh_data service")
            
            hass.services.async_register(
                DOMAIN, SERVICE_REFRESH_AUTH, handle_refresh_auth, schema=SERVICE_REFRESH_AUTH_SCHEMA
            )
            _LOGGER.debug("Registered refresh_authentication service")
        except Exception as e:
            _LOGGER.warning("Failed to register services, continuing without them: %s", e)
    
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    
    if unload_ok:
        # Clean up API connection
        data = hass.data[DOMAIN].get(entry.entry_id)
        if data and "api" in data:
            api = data["api"]
            await api.close()
            _LOGGER.debug("Closed SmartHub API connection for entry %s", entry.entry_id)
        
        # Remove data
        hass.data[DOMAIN].pop(entry.entry_id, None)
        
        # Remove domain data if no entries left
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN, None)
            
            # Remove services only when the last entry is removed
            try:
                if hass.services.has_service(DOMAIN, SERVICE_REFRESH_DATA):
                    hass.services.async_remove(DOMAIN, SERVICE_REFRESH_DATA)
                    _LOGGER.debug("Removed refresh_data service")
                
                if hass.services.has_service(DOMAIN, SERVICE_REFRESH_AUTH):
                    hass.services.async_remove(DOMAIN, SERVICE_REFRESH_AUTH)
                    _LOGGER.debug("Removed refresh_authentication service")
            except Exception as e:
                _LOGGER.warning("Failed to remove services during unload: %s", e)
    
    return unload_ok