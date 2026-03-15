"""Select entities for Tesla Smart Charge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    INPUT_DISTANCE_UNIT,
)
from .coordinator import TeslaSmartChargeCoordinator, get_device_info


@dataclass
class TeslaSmartChargeSelectDescription:
    """Description of a Tesla Smart Charge select."""

    key: str
    name: str
    options: list[str]
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
    """Set up select entities."""

    coordinator: TeslaSmartChargeCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = [
        TeslaSmartChargeSelectDescription(
            key=INPUT_DISTANCE_UNIT,
            name="Distance Unit",
            options=["km", "miles"],
            entity_registry_enabled_default=False,
        ),
    ]

    entities = [TeslaSmartChargeSelect(coordinator, description) for description in descriptions]
    async_add_entities(entities)


class TeslaSmartChargeSelect(CoordinatorEntity, SelectEntity, RestoreEntity):
    """Select entity for Tesla Smart Charge."""

    def __init__(
        self, coordinator: TeslaSmartChargeCoordinator, description: TeslaSmartChargeSelectDescription
    ) -> None:
        """Initialize the select entity."""

        super().__init__(coordinator)
        self.entity_description = description
        self._key = description.key
        self._attr_name = description.name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_options = description.options
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = get_device_info(coordinator.entry)
        coordinator.register_input_entity(self._key, self)

    @property
    def current_option(self) -> str | None:
        """Return the selected option."""

        return self.coordinator.inputs.get(self._key)

    async def async_select_option(self, option: str) -> None:
        """Handle option changes."""

        await self.coordinator.async_set_user_input(self._key, option)

    async def async_added_to_hass(self) -> None:
        """Restore previous state."""

        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if not last_state:
            return

        value = last_state.state
        if value not in self._attr_options:
            return

        self.coordinator.set_input_value(self._key, value, set_last=False)
        self.async_write_ha_state()
