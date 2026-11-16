"""Constants for Laadplanner."""

from __future__ import annotations

DOMAIN = "laadplanner"
STORAGE_VERSION = 1
UPDATE_SECONDS = 60
MIN_SWITCH_INTERVAL_S = 120  # never toggle the charger faster than this
START_CONFIRM_S = 300        # the Enphase cloud may take this long to show a start
STOP_RESEND_S = 120          # repeat "off" this often while charging still shows
STOP_MAX_RESENDS = 5         # ... but not more often than this per stop
# FordPass fallback: pause the car itself when the charger ignores "off"
CAR_PAUSE_AFTER_S = 150      # after the first "off", wait this long for proof
CAR_PAUSE_REPEAT_S = 300     # press pause again after this, if still charging
CAR_PAUSE_MAX_PRESSES = 2
CAR_START_RETRY_S = 180      # press start again until the car charges
CAR_START_WARN_AFTER = 5     # warn once after this many unconfirmed starts
CAR_START_SLOW_RETRY_S = 600 # after that, keep trying but less often
CAR_FINAL_RESTART_S = 5400   # always un-pause this long before the deadline
VOLTAGE = 230.0              # grid voltage per phase
CURRENT_SETTLE_S = 120       # ignore current changes shorter than this
LEARN_SETTLE_S = 300         # learn the car's share only at a steady current
DEFAULT_CHARGE_FACTOR = 0.9  # share of the set power the car takes, until learned
VIN_PLACEHOLDER = "jouw_vin"

# Car charge status values meaning "the car stopped: its own limit is reached"
CAR_DONE_STATES = {"completed", "complete", "charge_complete", "charging_complete",
                   "charge_target_reached", "full", "fully_charged", "voltooid"}

# Car charge status values meaning "the car is charging right now"
CAR_CHARGING_STATES = {"in_progress", "charging", "charging_in_progress", "laden"}

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
CONF_CHARGER_CURRENT = "charger_current_entity"
CONF_CHARGER_PHASES = "charger_phases_entity"
CONF_CHARGER_SAFE = "charger_safe_limit_entity"
CONF_CAR_PAUSE = "car_pause_entity"
CONF_CAR_START = "car_start_entity"
CONF_BATTERY_POWER = "battery_power_entity"
CONF_CAPACITY = "capacity_kwh"
CONF_GREEN_OPTION = "green_option"
CONF_MANUAL_OPTION = "manual_option"

# Entity fields that may be left empty
OPTIONAL_ENTITIES = (
    "charger_power_entity",
    "car_charge_status_entity",
    "car_last_refresh_entity",
    "charger_current_entity",
    "charger_phases_entity",
    "charger_safe_limit_entity",
    "car_pause_entity",
    "car_start_entity",
    "battery_power_entity",
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
    CONF_CHARGER_CURRENT: "number.auto_iq_ev_charger_1219_standaard_laadniveau",
    CONF_CHARGER_PHASES: "sensor.iq_ev_charger_1219_elektrische_fase",
    CONF_CHARGER_SAFE: "sensor.iq_ev_charger_1219_ampere_instellen",
    CONF_CAR_PAUSE: "button.fordpass_jouw_vin_evpause",
    CONF_CAR_START: "button.fordpass_jouw_vin_evstart",
    CONF_BATTERY_POWER: "sensor.energy_battery_batterij_ontladen_batterij_laden_net_power",
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
