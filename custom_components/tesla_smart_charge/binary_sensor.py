"""Binary sensor entities for Tesla Smart Charge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CONF_CHARGER_CONNECTED_SENSOR,
    CONF_SCHEDULED_CHARGING_SWITCH,
    DOMAIN,
)
from .coordinator import TeslaSmartChargeCoordinator, get_device_info


@dataclass
class TeslaSmartChargeBinarySensorDescription:
    """Description for Tesla Smart Charge binary sensors."""

    key: str
    name: str
    value_fn: Callable[[TeslaSmartChargeCoordinator], bool | None]
    attrs_fn: Callable[[TeslaSmartChargeCoordinator], dict] | None = None
    has_entity_name: bool = True
    entity_registry_enabled_default: bool = True
    entity_registry_visible_default: bool = True

    def __getattr__(self, name: str) -> Any:
        """Compat fallback for optional HA entity description fields."""

        return None


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up binary sensor entities."""

    coordinator: TeslaSmartChargeCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = [
        TeslaSmartChargeBinarySensorDescription(
            key="module_charge_controllable",
            name="Module Charge Controllable",
            value_fn=_module_charge_controllable_value,
            attrs_fn=_module_charge_controllable_attrs,
        )
    ]

    entities = [TeslaSmartChargeBinarySensor(coordinator, description) for description in descriptions]
    async_add_entities(entities)


class TeslaSmartChargeBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor entity for Tesla Smart Charge."""

    entity_description: TeslaSmartChargeBinarySensorDescription

    def __init__(
        self,
        coordinator: TeslaSmartChargeCoordinator,
        description: TeslaSmartChargeBinarySensorDescription,
    ) -> None:
        """Initialize the binary sensor."""

        super().__init__(coordinator)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_device_info = get_device_info(coordinator.entry)

    @property
    def is_on(self) -> bool | None:
        """Return true if the binary sensor is on."""

        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra attributes."""

        if self.entity_description.attrs_fn:
            return self.entity_description.attrs_fn(self.coordinator)
        return None


def _module_charge_controllable_value(coordinator: TeslaSmartChargeCoordinator) -> bool | None:
    """Return whether module can control charging now."""

    controllable, _plug_connected, _scheduled_enabled = _live_control_state(coordinator)
    return controllable


def _module_charge_controllable_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict:
    """Return module controllable debug attributes."""

    _controllable, plug_connected, scheduled_enabled = _live_control_state(coordinator)

    if plug_connected is None or scheduled_enabled is None:
        reason = "unknown"
    elif not plug_connected:
        reason = "plug_not_connected"
    elif scheduled_enabled:
        reason = "tesla_scheduled_charging_enabled"
    else:
        reason = "controllable"

    return {
        "plug_connected": plug_connected,
        "tesla_scheduled_charging_enabled": scheduled_enabled,
        "reason": reason,
        "plug_sensor_entity": coordinator.entry.data.get(CONF_CHARGER_CONNECTED_SENSOR),
        "scheduled_charging_entity": coordinator.entry.data.get(CONF_SCHEDULED_CHARGING_SWITCH),
    }


def _live_control_state(
    coordinator: TeslaSmartChargeCoordinator,
) -> tuple[bool | None, bool | None, bool | None]:
    """Read the two control prerequisites directly from current HA states."""

    plug_state = coordinator.hass.states.get(
        coordinator.entry.data.get(CONF_CHARGER_CONNECTED_SENSOR)
    )
    scheduled_state = coordinator.hass.states.get(
        coordinator.entry.data.get(CONF_SCHEDULED_CHARGING_SWITCH)
    )

    plug_connected = _state_on(plug_state)
    scheduled_enabled = _state_on(scheduled_state)
    if plug_connected is None or scheduled_enabled is None:
        return None, plug_connected, scheduled_enabled
    return (plug_connected and not scheduled_enabled), plug_connected, scheduled_enabled


def _state_on(state: Any) -> bool | None:
    """Return True for on, False for off, None for unknown/unavailable."""

    if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    if state.state == STATE_ON:
        return True
    if state.state == STATE_OFF:
        return False
    return None
