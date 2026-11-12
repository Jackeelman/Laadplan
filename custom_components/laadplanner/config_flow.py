"""Config and options flow for Laadplanner."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_CAPACITY,
    CONF_CHARGER_MODE,
    CONF_CHARGER_POWER,
    CONF_CHARGER_SWITCH,
    CONF_EXPORT,
    CONF_GREEN_OPTION,
    CONF_IMPORT,
    CONF_MANUAL_OPTION,
    CONF_PLUG,
    CONF_PRICE,
    CONF_SOC,
    CONF_SOLAR_TODAY,
    CONF_SOLAR_TOMORROW,
    DEFAULTS,
    DOMAIN,
)

_ENTITY_FIELDS = {
    CONF_SOC: ["sensor"],
    CONF_PLUG: ["binary_sensor", "sensor"],
    CONF_PRICE: ["sensor"],
    CONF_SOLAR_TODAY: ["sensor"],
    CONF_SOLAR_TOMORROW: ["sensor"],
    CONF_IMPORT: ["sensor"],
    CONF_EXPORT: ["sensor"],
    CONF_CHARGER_MODE: ["select"],
    CONF_CHARGER_SWITCH: ["switch"],
    CONF_CHARGER_POWER: ["sensor"],
}


def _schema(values: dict[str, Any]) -> vol.Schema:
    fields: dict[Any, Any] = {}
    for key, domains in _ENTITY_FIELDS.items():
        marker = vol.Optional if key == CONF_CHARGER_POWER else vol.Required
        default = values.get(key, DEFAULTS[key])
        fields[marker(key, description={"suggested_value": default})] = (
            selector.EntitySelector(selector.EntitySelectorConfig(domain=domains))
        )
    fields[vol.Required(CONF_CAPACITY, default=values.get(CONF_CAPACITY, DEFAULTS[CONF_CAPACITY]))] = (
        selector.NumberSelector(
            selector.NumberSelectorConfig(min=10, max=200, step=0.5, unit_of_measurement="kWh",
                                          mode=selector.NumberSelectorMode.BOX)
        )
    )
    for key in (CONF_GREEN_OPTION, CONF_MANUAL_OPTION):
        fields[vol.Required(key, default=values.get(key, DEFAULTS[key]))] = selector.TextSelector()
    return vol.Schema(fields)


class LaadplannerConfigFlow(ConfigFlow, domain=DOMAIN):
    """Set up Laadplanner."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            return self.async_create_entry(title="Laadplanner", data=user_input)
        return self.async_show_form(step_id="user", data_schema=_schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return LaadplannerOptionsFlow()


class LaadplannerOptionsFlow(OptionsFlow):
    """Change which entities are used."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data=user_input)
        current = {**self.config_entry.data, **self.config_entry.options}
        return self.async_show_form(step_id="init", data_schema=_schema(current))
