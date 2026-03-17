"""Switch entities for Tesla Smart Charge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, INPUT_ALLOW_IMMEDIATE_CHARGE, INPUT_SMART_CHARGING_ENABLED
from .coordinator import TeslaSmartChargeCoordinator, get_device_info


@dataclass
class TeslaSmartChargeSwitchDescription:
    """Description of a Tesla Smart Charge switch."""

    key: str
    name: str
    device_class: str | None = None
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
    """Set up switch entities."""

    coordinator: TeslaSmartChargeCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = [
        TeslaSmartChargeSwitchDescription(
            key=INPUT_SMART_CHARGING_ENABLED,
            name="Enable Smart Charging",
        ),
        TeslaSmartChargeSwitchDescription(
            key=INPUT_ALLOW_IMMEDIATE_CHARGE,
            name="Allow Immediate Charge",
            entity_registry_enabled_default=False,
        ),
    ]

    entities = [TeslaSmartChargeSwitch(coordinator, description) for description in descriptions]
    async_add_entities(entities)


class TeslaSmartChargeSwitch(CoordinatorEntity, SwitchEntity, RestoreEntity):
    """Switch entity for Tesla Smart Charge."""

    def __init__(
        self, coordinator: TeslaSmartChargeCoordinator, description: TeslaSmartChargeSwitchDescription
    ) -> None:
        """Initialize the switch entity."""

        super().__init__(coordinator)
        self.entity_description = description
        self._key = description.key
        self._attr_name = description.name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = get_device_info(coordinator.entry)
        coordinator.register_input_entity(self._key, self)

    @property
    def is_on(self) -> bool | None:
        """Return the switch state."""

        return bool(self.coordinator.inputs.get(self._key))

    async def async_turn_on(self, **kwargs) -> None:
        """Handle turning on the switch."""

        await self.coordinator.async_set_user_input(self._key, True)
        await self.coordinator.async_apply_control()

    async def async_turn_off(self, **kwargs) -> None:
        """Handle turning off the switch."""

        await self.coordinator.async_set_user_input(self._key, False)
        await self.coordinator.async_apply_control()

    async def async_added_to_hass(self) -> None:
        """Restore previous state."""

        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if not last_state:
            return

        self.coordinator.set_input_value(self._key, last_state.state == "on", set_last=False)
        self.async_write_ha_state()
