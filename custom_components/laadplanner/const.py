"""Constants for Laadplanner."""

from __future__ import annotations

DOMAIN = "laadplanner"
STORAGE_VERSION = 1
UPDATE_SECONDS = 60
MIN_SWITCH_INTERVAL_S = 120  # never toggle the charger faster than this

# Car charge status values meaning "the car stopped: its own limit is reached"
CAR_DONE_STATES = {"completed", "complete", "charge_complete", "charging_complete",
                   "charge_target_reached", "full", "fully_charged", "voltooid"}

# Config entry keys (entities read from Home Assistant)
CONF_SOC = "soc_entity"
CONF_PLUG = "plug_entity"
CONF_PRICE = "price_entity"
CONF_SOLAR_TODAY = "solar_remaining_today_entity"
CONF_SOLAR_TOMORROW = "solar_tomorrow_entity"
CONF_IMPORT = "import_energy_entity"
CONF_EXPORT = "export_energy_entity"
CONF_CHARGER_MODE = "charger_mode_entity"
CONF_CHARGER_SWITCH = "charger_switch_entity"
CONF_CHARGER_POWER = "charger_power_entity"
CONF_CAR_STATUS = "car_charge_status_entity"
CONF_CAR_REFRESH = "car_last_refresh_entity"
CONF_CAPACITY = "capacity_kwh"
CONF_GREEN_OPTION = "green_option"
CONF_MANUAL_OPTION = "manual_option"

# Entity fields that may be left empty
OPTIONAL_ENTITIES = (
    "charger_power_entity",
    "car_charge_status_entity",
    "car_last_refresh_entity",
)

DEFAULTS = {
    CONF_SOC: "sensor.fordpass_jouw_vin_soc",
    CONF_PLUG: "binary_sensor.iq_ev_charger_1219_ingeplugd",
    CONF_PRICE: "sensor.nordpool_kwh_nl_eur_3_10_021",
    CONF_SOLAR_TODAY: "sensor.energy_production_today_remaining_2",
    CONF_SOLAR_TOMORROW: "sensor.energy_production_tomorrow_2",
    CONF_IMPORT: "sensor.meterkast_p1_meter_hw_energie_import",
    CONF_EXPORT: "sensor.meterkast_p1_meter_hw_energie_export",
    CONF_CHARGER_MODE: "select.iq_ev_charger_1219_laadmodus",
    CONF_CHARGER_SWITCH: "switch.iq_ev_charger_1219",
    CONF_CHARGER_POWER: "sensor.iq_ev_charger_1219_vermogen",
    CONF_CAR_STATUS: "sensor.fordpass_jouw_vin_elvehcharging",
    CONF_CAR_REFRESH: "sensor.fordpass_jouw_vin_lastrefresh",
    CONF_CAPACITY: 77.0,
    CONF_GREEN_OPTION: "Groen",
    CONF_MANUAL_OPTION: "Handmatig",
}

# Runtime settings (changed through the integration's own entities)
SET_STRATEGY = "strategy"
SET_CONTRACT = "contract"
SET_TARGET = "target_pct"
SET_DEADLINE = "deadline"
SET_ACTIVE = "active"
SET_FIXED_IMPORT = "fixed_import"
SET_FIXED_EXPORT = "fixed_export"
SET_DYN_IMPORT = "dyn_import_markup"
SET_DYN_EXPORT = "dyn_export_markup"
SET_SURPLUS = "surplus_factor"
SET_POWER = "charge_power_kw"
SET_EFFICIENCY = "efficiency"
SET_FALLBACK = "fallback_kwh"
SET_NIGHT_START = "night_start"

SETTING_DEFAULTS = {
    SET_STRATEGY: "automatisch",
    SET_CONTRACT: "vast",
    SET_TARGET: 80.0,
    SET_DEADLINE: "07:00",
    SET_ACTIVE: False,          # shadow mode: never steer until switched on
    SET_FIXED_IMPORT: 0.0,      # EUR/kWh incl. VAT, set from your contract
    SET_FIXED_EXPORT: 0.0,
    SET_DYN_IMPORT: 0.0,        # added to the price sensor (tax, markup)
    SET_DYN_EXPORT: 0.0,
    SET_SURPLUS: 0.5,
    SET_POWER: 11.0,
    SET_EFFICIENCY: 0.9,
    SET_FALLBACK: 10.0,
    SET_NIGHT_START: "00:00",   # charge from here (everyone asleep)
}
