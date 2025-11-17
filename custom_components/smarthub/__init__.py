"""
Custom integration to integrate SmartHub Coop energy sensors with Home Assistant.

For more details about this integration, please refer to
https://github.com/gagata/ha-smarthub-energy-sensor
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryError

from .api import SmartHubAPI
from .sensor import  SmartHubDataUpdateCoordinator
from .const import DOMAIN

from datetime import timedelta

# Remove explicit config flow import
# from . import config_flow  # noqa: F401

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up SmartHub from a config entry."""
    config = entry.data

    # Validate required configuration
    required_fields = ["email", "password", "account_id", "host"]
    missing_fields = [field for field in required_fields if not config.get(field)]

    if missing_fields:
        _LOGGER.error("Missing required configuration fields: %s", missing_fields)
        raise ConfigEntryError(f"Missing configuration fields: {missing_fields}")

    # Initialize the API object
    api = SmartHubAPI(
        email=config["email"],
        password=config["password"],
        account_id=config["account_id"],
        timezone=config.get("timezone", "GMT"), # timezone was not previously required - default it to be GMT
        mfa_totp=config.get("mfa_totp", ""), # mfa_totp is optional
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

    # Create update coordinator, and store in the config entry
    coordinator = SmartHubDataUpdateCoordinator(
        hass=hass,
        api=api,
        update_interval=timedelta(minutes=config.get("poll_interval", 720)),
        config_entry=entry,
    )
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    # Set up platforms
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    # Unload platforms
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)

    if unload_ok:
        # Clean up API connection
        data = hass.data.get(DOMAIN,{}).get(entry.entry_id)

        if hasattr(entry, "runtime_data") and hasattr(entry.runtime_data, "api"):
            api= entry.runtime_data.api

        if data:
            if isinstance(data, dict) and "api" in data:
                api = data["api"]
            else:
                api = data  # Direct API reference

        if api:
            await api.close()

        # Remove data
        hass.data.get(DOMAIN,{}).pop(entry.entry_id, None)

        # Remove domain data if no entries left
        if DOMAIN in hass.data:
            hass.data.pop(DOMAIN, None)

    return unload_ok

