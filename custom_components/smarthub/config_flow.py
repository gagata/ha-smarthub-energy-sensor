"""Config flow for SmartHub integration."""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import HomeAssistant

from .api import SmartHubAPI, SmartHubAPIError, SmartHubAuthError, SmartHubConnectionError
from .const import (
    DOMAIN,
    CONF_EMAIL,
    CONF_PASSWORD,
    CONF_ACCOUNT_ID,
    CONF_LOCATION_ID,
    CONF_HOST,
    CONF_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    MIN_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


def validate_email(email: str) -> bool:
    """Validate email format."""
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_host(host: str) -> bool:
    """Validate host format."""
    # Remove protocol if present
    if host.startswith(('http://', 'https://')):
        parsed = urlparse(host)
        host = parsed.netloc
    
    # Basic hostname validation
    pattern = r'^[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, host)) and len(host) <= 253


async def validate_input(hass: HomeAssistant, data: Dict[str, Any]) -> Dict[str, str]:
    """
    Validate the user input allows us to connect.
    
    Returns:
        Dict containing validation result information.
        
    Raises:
        vol.Invalid: If validation fails.
    """
    # Input validation
    email = data[CONF_EMAIL].strip().lower()
    if not validate_email(email):
        raise vol.Invalid("Invalid email format")
    
    password = data[CONF_PASSWORD]
    if len(password) < 1:
        raise vol.Invalid("Password cannot be empty")
    
    account_id = data[CONF_ACCOUNT_ID].strip()
    if not account_id:
        raise vol.Invalid("Account ID cannot be empty")
    
    location_id = data[CONF_LOCATION_ID].strip()
    if not location_id:
        raise vol.Invalid("Location ID cannot be empty")
    
    host = data[CONF_HOST].strip().lower()
    # Remove protocol if present for storage
    if host.startswith(('http://', 'https://')):
        parsed = urlparse(host)
        host = parsed.netloc
    
    if not validate_host(host):
        raise vol.Invalid("Invalid host format")
    
    poll_interval = data.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
    if not isinstance(poll_interval, int) or not (MIN_POLL_INTERVAL <= poll_interval <= MAX_POLL_INTERVAL):
        raise vol.Invalid(f"Poll interval must be between {MIN_POLL_INTERVAL} and {MAX_POLL_INTERVAL} minutes")

    # Test API connection
    api = SmartHubAPI(
        email=email,
        password=password,
        account_id=account_id,
        location_id=location_id,
        host=host,
    )
    
    try:
        await api.get_token()
        # Test data retrieval
        await api.get_energy_data()
        return {
            "title": f"SmartHub ({account_id})",
            "email": email,
            "host": host,
        }
    finally:
        await api.close()


class SmartHubConfigFlow(config_entries.ConfigFlow):
    """Handle a config flow for SmartHub."""

    DOMAIN = DOMAIN
    VERSION = 1

    async def async_step_user(
        self, user_input: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Handle the initial step."""
        errors: Dict[str, str] = {}

        if user_input is not None:
            try:
                info = await validate_input(self.hass, user_input)
                
                # Generate a unique ID from validated input
                unique_id = f"{info['email']}_{info['host']}_{user_input[CONF_ACCOUNT_ID]}"
                
                # Set the unique ID and check for duplicates
                await self.async_set_unique_id(unique_id)
                self._abort_if_unique_id_configured()

                _LOGGER.debug("Successfully validated SmartHub configuration")
                
                return self.async_create_entry(
                    title=info["title"],
                    data=user_input,
                )

            except SmartHubAuthError:
                _LOGGER.error("Authentication failed during config flow")
                errors["base"] = "invalid_auth"
            except SmartHubConnectionError:
                _LOGGER.error("Connection failed during config flow")
                errors["base"] = "cannot_connect"
            except vol.Invalid as e:
                _LOGGER.error("Validation error: %s", e)
                errors["base"] = "invalid_input"
            except SmartHubAPIError as e:
                _LOGGER.error("API error during config flow: %s", e)
                errors["base"] = "unknown"
            except Exception as e:
                _LOGGER.exception("Unexpected error during config flow: %s", e)
                errors["base"] = "unknown"

        # Build the schema with current values if available
        schema_dict = {
            vol.Required(CONF_EMAIL, default=user_input.get(CONF_EMAIL, "") if user_input else ""): str,
            vol.Required(CONF_PASSWORD): str,
            vol.Required(CONF_ACCOUNT_ID, default=user_input.get(CONF_ACCOUNT_ID, "") if user_input else ""): str,
            vol.Required(CONF_LOCATION_ID, default=user_input.get(CONF_LOCATION_ID, "") if user_input else ""): str,
            vol.Required(CONF_HOST, default=user_input.get(CONF_HOST, "") if user_input else ""): str,
            vol.Optional(
                CONF_POLL_INTERVAL, 
                default=user_input.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL) if user_input else DEFAULT_POLL_INTERVAL
            ): vol.All(vol.Coerce(int), vol.Range(min=MIN_POLL_INTERVAL, max=MAX_POLL_INTERVAL)),
        }

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(schema_dict),
            errors=errors,
            description_placeholders={
                "min_poll": str(MIN_POLL_INTERVAL),
                "max_poll": str(MAX_POLL_INTERVAL),
            },
        )
