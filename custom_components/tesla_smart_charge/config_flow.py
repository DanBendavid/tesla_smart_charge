"""Config flow for Tesla Smart Charge."""

from __future__ import annotations

import json
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_FILENAME
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

try:
    from homeassistant.components.lovelace.const import LOVELACE_DATA
except ImportError:  # pragma: no cover - compatibility fallback
    LOVELACE_DATA = "lovelace"

from .const import (
    CONF_ADD_TO_EXISTING_DASHBOARD,
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_SENSOR,
    CONF_CHARGE_LIMIT_NUMBER,
    CONF_CHARGER_CONNECTED_SENSOR,
    CONF_CHARGER_POWER_SENSOR,
    CONF_CHARGER_SWITCH,
    CONF_CHARGING_AMPS_NUMBER,
    CONF_CHARGING_SENSOR,
    CONF_EXISTING_DASHBOARD_FILENAME,
    CONF_INSTALL_DASHBOARD_ON_SETUP,
    CONF_MAX_CHARGING_POWER,
    CONF_RANGE_SENSOR,
    CONF_SCHEDULED_CHARGING_SENSOR,
    CONF_TARIFF_ATTRIBUTE,
    CONF_TARIFF_REST_HEADERS,
    CONF_TARIFF_REST_JSON_PATH,
    CONF_TARIFF_REST_URL,
    CONF_TARIFF_SENSOR,
    CONF_TARIFF_SOURCE,
    CONF_TIME_CHARGE_COMPLETE_SENSOR,
    CONF_VEHICLE_EFFICIENCY,
    DOMAIN,
    TARIFF_SOURCE_REST,
    TARIFF_SOURCE_SENSOR,
    TARIFF_SOURCE_SPOT,
    TARIFF_SOURCE_SPOT_TOMORROW,
)

_ENTITY_HINTS: dict[str, tuple[str, tuple[str, ...]]] = {
    CONF_BATTERY_SENSOR: (
        "sensor",
        ("battery", "usable_battery_level", "battery_level"),
    ),
    CONF_CHARGING_SENSOR: ("binary_sensor", ("charging", "charger")),
    CONF_CHARGER_SWITCH: ("switch", ("charger", "charge")),
    CONF_CHARGER_POWER_SENSOR: ("sensor", ("charger_power", "charging_power")),
    CONF_CHARGE_LIMIT_NUMBER: ("number", ("charge_limit", "charge_limit_soc")),
    CONF_CHARGING_AMPS_NUMBER: ("number", ("charging_amps", "charge_current_request")),
    CONF_RANGE_SENSOR: ("sensor", ("range", "battery_range", "est_battery_range")),
    CONF_TIME_CHARGE_COMPLETE_SENSOR: (
        "sensor",
        ("time_charge_complete", "time_to_full_charge", "charge_complete"),
    ),
    CONF_CHARGER_CONNECTED_SENSOR: (
        "binary_sensor",
        ("plugged", "charger_connected", "charge_port", "charger"),
    ),
    CONF_SCHEDULED_CHARGING_SENSOR: (
        "binary_sensor",
        ("scheduled_charging", "charge_schedule"),
    ),
}


class TeslaSmartChargeConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Tesla Smart Charge."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""

        self._data: dict = {}

    async def async_step_user(self, user_input: dict | None = None):
        """Collect Tesla entity mappings."""

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_tariff()

        detected = self._auto_detect_tesla_entities()
        all_entity_keys = list(_ENTITY_HINTS)
        defaults = {
            **detected,
            **{key: self._data[key] for key in all_entity_keys if key in self._data},
        }

        schema_fields: dict[Any, Any] = {}
        for key, (entity_domain, _) in _ENTITY_HINTS.items():
            selector_config = selector.EntitySelectorConfig(domain=entity_domain)
            default = defaults.get(key)
            if default:
                schema_fields[vol.Required(key, default=default)] = (
                    selector.EntitySelector(selector_config)
                )
            else:
                schema_fields[vol.Required(key)] = selector.EntitySelector(
                    selector_config
                )

        schema = vol.Schema(schema_fields)

        return self.async_show_form(step_id="user", data_schema=schema)

    def _auto_detect_tesla_entities(self) -> dict[str, str]:
        """Try to detect Tesla entities and return suggested defaults."""

        registry = er.async_get(self.hass)
        tesla_entry_ids = {
            entry.entry_id
            for entry in self.hass.config_entries.async_entries()
            if "tesla" in entry.domain
        }

        detected: dict[str, str] = {}
        for key, (expected_domain, keywords) in _ENTITY_HINTS.items():
            best_score = -1
            best_entity_id: str | None = None

            for entity in registry.entities.values():
                entity_id = entity.entity_id
                if not entity_id or not entity_id.startswith(f"{expected_domain}."):
                    continue
                if entity.disabled_by is not None:
                    continue

                is_tesla_entity = entity.config_entry_id in tesla_entry_ids
                if tesla_entry_ids and not is_tesla_entity:
                    continue

                object_id = entity_id.split(".", 1)[1]
                score = 1
                if is_tesla_entity:
                    score += 1000

                for index, keyword in enumerate(keywords):
                    bonus = max(0, 100 - index)
                    if object_id == keyword:
                        score += 500 + bonus
                    elif object_id.startswith(keyword) or object_id.endswith(keyword):
                        score += 300 + bonus
                    elif keyword in object_id:
                        score += 150 + bonus

                if score > best_score:
                    best_score = score
                    best_entity_id = entity_id

            if best_entity_id:
                detected[key] = best_entity_id

        return detected

    async def async_step_tariff(self, user_input: dict | None = None):
        """Select tariff source."""

        if user_input is not None:
            self._data.update(user_input)
            source = user_input[CONF_TARIFF_SOURCE]
            if source == TARIFF_SOURCE_SENSOR:
                return await self.async_step_tariff_sensor()
            if source == TARIFF_SOURCE_REST:
                return await self.async_step_tariff_rest()
            return await self.async_step_constants()

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_TARIFF_SOURCE, default=TARIFF_SOURCE_SENSOR
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {
                                "value": TARIFF_SOURCE_SENSOR,
                                "label": "Sensor Attribute",
                            },
                            {
                                "value": TARIFF_SOURCE_REST,
                                "label": "REST Endpoint",
                            },
                            {
                                "value": TARIFF_SOURCE_SPOT,
                                "label": "Spot Raw (CU4 Particulier TTC, 24h Sliding)",
                            },
                            {
                                "value": TARIFF_SOURCE_SPOT_TOMORROW,
                                "label": "Spot Tomorrow (alias Spot Raw CU4 TTC)",
                            },
                        ]
                    )
                )
            }
        )

        return self.async_show_form(step_id="tariff", data_schema=schema)

    async def async_step_tariff_sensor(self, user_input: dict | None = None):
        """Collect tariff sensor details."""

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_constants()

        schema = vol.Schema(
            {
                vol.Required(CONF_TARIFF_SENSOR): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Required(
                    CONF_TARIFF_ATTRIBUTE, default="prices"
                ): selector.TextSelector(),
            }
        )

        return self.async_show_form(step_id="tariff_sensor", data_schema=schema)

    async def async_step_tariff_rest(self, user_input: dict | None = None):
        """Collect tariff REST endpoint details."""

        errors: dict[str, str] = {}

        if user_input is not None:
            headers = user_input.get(CONF_TARIFF_REST_HEADERS)
            headers_dict = None
            if headers:
                try:
                    headers_dict = json.loads(headers)
                    if not isinstance(headers_dict, dict):
                        raise ValueError("Headers must be a JSON object")
                except ValueError:
                    errors[CONF_TARIFF_REST_HEADERS] = "invalid_headers"

            if not errors:
                self._data.update(user_input)
                if headers_dict is not None:
                    self._data[CONF_TARIFF_REST_HEADERS] = headers_dict
                else:
                    self._data.pop(CONF_TARIFF_REST_HEADERS, None)
                return await self.async_step_constants()

        schema = vol.Schema(
            {
                vol.Required(CONF_TARIFF_REST_URL): selector.TextSelector(),
                vol.Optional(CONF_TARIFF_REST_HEADERS): selector.TextSelector(),
                vol.Optional(CONF_TARIFF_REST_JSON_PATH): selector.TextSelector(),
            }
        )

        return self.async_show_form(
            step_id="tariff_rest", data_schema=schema, errors=errors
        )

    async def async_step_constants(self, user_input: dict | None = None):
        """Collect vehicle constants."""

        if user_input is not None:
            self._data.update(user_input)
            install_dashboard = bool(user_input.get(CONF_INSTALL_DASHBOARD_ON_SETUP))
            add_to_existing = bool(user_input.get(CONF_ADD_TO_EXISTING_DASHBOARD))
            if not install_dashboard:
                self._data[CONF_ADD_TO_EXISTING_DASHBOARD] = False
                self._data.pop(CONF_EXISTING_DASHBOARD_FILENAME, None)
                return self.async_create_entry(title="Tesla Smart Charge", data=self._data)
            if install_dashboard and add_to_existing:
                return await self.async_step_existing_dashboard()
            self._data.pop(CONF_EXISTING_DASHBOARD_FILENAME, None)
            return self.async_create_entry(title="Tesla Smart Charge", data=self._data)

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_BATTERY_CAPACITY, default=75.0
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=200,
                        step=1,
                        unit_of_measurement="kWh",
                        mode="box",
                    )
                ),
                vol.Required(
                    CONF_VEHICLE_EFFICIENCY, default=180.0
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50,
                        max=400,
                        step=1,
                        unit_of_measurement="Wh/km",
                        mode="box",
                    )
                ),
                vol.Required(
                    CONF_MAX_CHARGING_POWER, default=3.0
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1,
                        max=50,
                        step=0.5,
                        unit_of_measurement="kW",
                        mode="box",
                    )
                ),
                vol.Required(
                    CONF_INSTALL_DASHBOARD_ON_SETUP,
                    default=True,
                ): selector.BooleanSelector(),
                vol.Required(
                    CONF_ADD_TO_EXISTING_DASHBOARD,
                    default=False,
                ): selector.BooleanSelector(),
            }
        )

        return self.async_show_form(step_id="constants", data_schema=schema)

    async def async_step_existing_dashboard(self, user_input: dict | None = None):
        """Collect existing dashboard file path for view injection."""

        errors: dict[str, str] = {}

        if user_input is not None:
            filename = str(
                user_input[CONF_EXISTING_DASHBOARD_FILENAME]
            ).strip()
            if not filename:
                errors[CONF_EXISTING_DASHBOARD_FILENAME] = "empty_dashboard_filename"
            else:
                self._data[CONF_EXISTING_DASHBOARD_FILENAME] = filename
                return self.async_create_entry(title="Tesla Smart Charge", data=self._data)

        default_filename = str(
            self._data.get(CONF_EXISTING_DASHBOARD_FILENAME, "ui-lovelace.yaml")
        ).strip()
        options = self._yaml_dashboard_filename_options()

        if options:
            option_values = [str(option["value"]) for option in options]
            if default_filename not in option_values:
                default_filename = option_values[0]
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_EXISTING_DASHBOARD_FILENAME,
                        default=default_filename,
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(options=options)
                    ),
                }
            )
        else:
            schema = vol.Schema(
                {
                    vol.Required(
                        CONF_EXISTING_DASHBOARD_FILENAME,
                        default=default_filename,
                    ): selector.TextSelector(),
                }
            )

        return self.async_show_form(
            step_id="existing_dashboard", data_schema=schema, errors=errors
        )

    def _yaml_dashboard_filename_options(self) -> list[dict[str, str]]:
        """Return YAML dashboard filenames currently known by Lovelace."""

        lovelace_data = self.hass.data.get(LOVELACE_DATA)
        dashboards = getattr(lovelace_data, "dashboards", None)
        if not isinstance(dashboards, dict):
            return []

        options_by_filename: dict[str, str] = {}
        for url_path, lovelace_config in dashboards.items():
            config = getattr(lovelace_config, "config", None)
            if not isinstance(config, dict):
                continue

            filename = config.get(CONF_FILENAME)
            if not isinstance(filename, str) or not filename.strip():
                continue
            filename = filename.strip()

            raw_title = config.get("title")
            if isinstance(raw_title, str) and raw_title.strip():
                title = raw_title.strip()
            elif isinstance(url_path, str) and url_path.strip():
                title = url_path.strip()
            else:
                title = "Overview"

            options_by_filename.setdefault(filename, f"{title} ({filename})")

        if not options_by_filename:
            return []

        return [
            {"value": filename, "label": label}
            for filename, label in sorted(
                options_by_filename.items(), key=lambda item: item[1].lower()
            )
        ]
