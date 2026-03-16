"""Constants for the Tesla Smart Charge integration."""

DOMAIN = "tesla_smart_charge"

PLATFORMS = ["binary_sensor", "sensor", "number", "select", "switch"]

# Config keys for Tesla entity mapping.
CONF_BATTERY_SENSOR = "battery_sensor"
CONF_CHARGING_SENSOR = "charging_sensor"
CONF_CHARGER_SWITCH = "charger_switch"
CONF_CHARGER_POWER_SENSOR = "charger_power_sensor"
CONF_CHARGE_LIMIT_NUMBER = "charge_limit_number"
CONF_CHARGING_AMPS_NUMBER = "charging_amps_number"
CONF_RANGE_SENSOR = "range_sensor"
CONF_TIME_CHARGE_COMPLETE_SENSOR = "time_charge_complete_sensor"
CONF_CHARGER_CONNECTED_SENSOR = "charger_connected_sensor"
CONF_SCHEDULED_CHARGING_SENSOR = "scheduled_charging_sensor"
CONF_INSTALL_DASHBOARD_ON_SETUP = "install_dashboard_on_setup"

# Tariff configuration.
CONF_TARIFF_SOURCE = "tariff_source"
CONF_TARIFF_SENSOR = "tariff_sensor"
CONF_TARIFF_ATTRIBUTE = "tariff_attribute"
CONF_TARIFF_REST_URL = "tariff_rest_url"
CONF_TARIFF_REST_HEADERS = "tariff_rest_headers"
CONF_TARIFF_REST_JSON_PATH = "tariff_rest_json_path"

TARIFF_SOURCE_SENSOR = "sensor"
TARIFF_SOURCE_REST = "rest"
TARIFF_SOURCE_SPOT = "spot"
TARIFF_SOURCE_SPOT_TOMORROW = "spot_tomorrow"

# Vehicle constants.
CONF_BATTERY_CAPACITY = "battery_capacity_kwh"
CONF_VEHICLE_EFFICIENCY = "vehicle_efficiency_wh_per_km"
CONF_MAX_CHARGING_POWER = "max_charging_power_kw"

# Input keys.
INPUT_TARGET_SOC = "target_soc"
INPUT_TARGET_ENERGY = "target_energy_kwh"
INPUT_TARGET_DISTANCE = "target_distance"
INPUT_MAX_COST = "max_cost"
INPUT_MAX_WEEKLY_ENERGY = "max_weekly_energy_kwh"
INPUT_READY_BY_HOUR = "ready_by_hour"
INPUT_OPPORTUNISTIC_SOC = "opportunistic_target_soc"
INPUT_CHEAP_PRICE_THRESHOLD = "cheap_price_threshold"
INPUT_DISTANCE_UNIT = "distance_unit"
INPUT_PLANNING_HORIZON = "planning_horizon"
INPUT_SMART_CHARGING_ENABLED = "smart_charging_enabled"
INPUT_ALLOW_IMMEDIATE_CHARGE = "allow_immediate_charge"

DISTANCE_UNIT_KM = "km"
DISTANCE_UNIT_MI = "miles"

PLANNING_HORIZON_TONIGHT = "tonight"
PLANNING_HORIZON_TOMORROW = "tomorrow"
PLANNING_HORIZON_WEEK = "week"

DEFAULT_TARGET_SOC = 50
DEFAULT_TARGET_ENERGY_KWH = 10.0
DEFAULT_TARGET_DISTANCE = 50.0
DEFAULT_MAX_COST = 0.0
DEFAULT_MAX_WEEKLY_ENERGY_KWH = 0.0
DEFAULT_READY_BY_HOUR = 8
DEFAULT_OPPORTUNISTIC_SOC = 80
DEFAULT_CHEAP_PRICE_THRESHOLD = 0.0
DEFAULT_DISTANCE_UNIT = DISTANCE_UNIT_KM
DEFAULT_PLANNING_HORIZON = PLANNING_HORIZON_TONIGHT
DEFAULT_SMART_CHARGING_ENABLED = False
DEFAULT_ALLOW_IMMEDIATE_CHARGE = False

SERVICE_REOPTIMIZE = "reoptimize"
SERVICE_APPLY_CONTROL = "apply_control"
SERVICE_INSTALL_DASHBOARD_TEMPLATE = "install_dashboard_template"

ATTR_ENTRY_ID = "entry_id"
ATTR_FILENAME = "filename"
