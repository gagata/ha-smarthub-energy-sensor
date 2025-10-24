"""Simple config flow for SmartHub integration."""
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN


class SmartHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartHub."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle the initial step."""
        if user_input is not None:
            # For now, just create the entry with minimal validation
            return self.async_create_entry(
                title="SmartHub",
                data=user_input,
            )

        # Show basic form
        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                vol.Required("email"): str,
                vol.Required("password"): str,
                vol.Required("account_id"): str,
                vol.Required("location_id"): str,
                vol.Required("host"): str,
            }),
        )