"""The SmartHub integration."""
from __future__ import annotations

import logging
from typing import Dict, Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .api import SmartHubAPI
from .const import DOMAIN, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[str] = ["sensor"]


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
    
    return unload_ok

