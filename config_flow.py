from homeassistant import config_entries
import voluptuous as vol
from .api import SmartHubAPI
from .const import DOMAIN, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL

import logging
_LOGGER = logging.getLogger(__name__)

class SmartHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartHub."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        errors = {}

        if user_input is not None:
            # Generate a unique ID from input that should uniquely identify this account/host
            # This is crucial for Home Assistant to manage the integration instance.
            unique_id = f"{user_input['email']}_{user_input['host']}_{user_input['account_id']}"
            
            # Set the unique ID for this config entry.
            # If an entry with this unique ID already exists, abort the flow.
            await self.async_set_unique_id(unique_id)
            self._abort_if_unique_id_configured() # Check if already configured

            try:
                # Validate credentials by attempting to get a token
                api = SmartHubAPI(
                    email=user_input["email"],
                    password=user_input["password"],
                    account_id=user_input["account_id"],
                    location_id=user_input["location_id"],
                    host=user_input["host"],
                )
                
                # Note: If SmartHubAPI.get_token is not truly async (e.g., uses blocking requests),
                # hass.async_add_executor_job is correct. If it's pure aiohttp/httpx async,
                # you can just await it directly: `await api.get_token()`.
                # Given api.py uses aiohttp, you can likely do:
                await api.get_token()

                # Debug log for successful connection
                _LOGGER.debug("Successfully validated credentials in config_flow and set unique_id: %s", unique_id)

                # Create an entry with the user-provided data
                # The unique_id is now automatically associated with this entry
                return self.async_create_entry(title="SmartHub", data=user_input)

            except Exception as e: # Catch specific exceptions for better error handling
                _LOGGER.error("Error validating credentials in config_flow: %s", e)
                errors["base"] = "cannot_connect"

        # Show the form again if validation failed or it's the first time
        schema = vol.Schema(
            {
                vol.Required("email"): str,
                vol.Required("password"): str,
                vol.Required("account_id"): str,
                vol.Required("location_id"): str,
                vol.Required("host"): str,
                vol.Optional(CONF_POLL_INTERVAL, default=DEFAULT_POLL_INTERVAL): int,  # Poll interval in minutes
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)
