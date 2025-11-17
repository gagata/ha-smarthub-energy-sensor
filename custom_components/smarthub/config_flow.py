"""Simple config flow for SmartHub integration."""
import voluptuous as vol
from homeassistant import config_entries
from .const import DOMAIN

from typing import Any
import zoneinfo
import logging
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,

    TextSelector,
    TextSelectorConfig,
    TextSelectorType
)

_LOGGER = logging.getLogger(__name__)

class SmartHubConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for SmartHub."""

    VERSION = 1
    MINOR_VERSION = 1 # Updated to handle addition of TOTP, and TimeZone

    async def async_step_user(self, user_input=None) -> config_entries.ConfigFlowResult:
        """Handle the initial step."""
        if user_input is not None:
            if self.source == config_entries.SOURCE_RECONFIGURE:
                return self.async_update_reload_and_abort(
                    self._get_reconfigure_entry(), data_updates=user_input
                )
            # else - create a new entry
            return self.async_create_entry(
                title="SmartHub",
                data=user_input,
            )

        schema_values: dict[str, Any] | MappingProxyType[str, Any] = {}
        if self.source == config_entries.SOURCE_RECONFIGURE:
            schema_values = self._get_reconfigure_entry().data

        timezones = await self.hass.async_add_executor_job(
                zoneinfo.available_timezones
            )
        schema = vol.Schema(
            {
               vol.Required("email"): str,
               vol.Required("password"): str,
               vol.Required("account_id"): str,
               vol.Required("host"): str,
               vol.Required("timezone", default="GMT"): SelectSelector(
                SelectSelectorConfig(
                  options=list(timezones), mode=SelectSelectorMode.DROPDOWN, sort=True
                )
               ),
               vol.Optional("mfa_totp"): TextSelector(
                 TextSelectorConfig(
                   type=TextSelectorType.PASSWORD
                 )
               ),
            }
        )

        errors = {}

        # Show basic form
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                schema,
                schema_values,
            ),
            errors=errors
        )

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        """Handle a reconfiguration config flow initialized by the user."""
        return await self.async_step_user(user_input)
