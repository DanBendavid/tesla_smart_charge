"""Number entities for Tesla Smart Charge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.number import NumberEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import PERCENTAGE
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import EntityCategory
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    DOMAIN,
    INPUT_CHEAP_PRICE_THRESHOLD,
    DISTANCE_UNIT_MI,
    INPUT_OPPORTUNISTIC_SOC,
    INPUT_READY_BY_HOUR,
    INPUT_TARGET_DISTANCE,
    INPUT_TARGET_ENERGY,
    INPUT_TARGET_SOC,
)
from .coordinator import TeslaSmartChargeCoordinator, get_device_info

_KM_PER_MI = 1.60934


@dataclass
class TeslaSmartChargeNumberDescription:
    """Description of a Tesla Smart Charge number."""

    key: str
    input_key: str
    name: str
    min_value: float
    max_value_fn: Callable[[TeslaSmartChargeCoordinator], float]
    step: float
    unit_fn: Callable[[TeslaSmartChargeCoordinator], str | None]
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
    """Set up number entities."""

    coordinator: TeslaSmartChargeCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = [
        TeslaSmartChargeNumberDescription(
            key="min_soc_at_ready_time",
            input_key=INPUT_TARGET_SOC,
            name="Min. SOC at Ready Time",
            min_value=0.0,
            max_value_fn=lambda coord: 100.0,
            step=1.0,
            unit_fn=lambda coord: PERCENTAGE,
        ),
        TeslaSmartChargeNumberDescription(
            key="departure_time",
            input_key=INPUT_READY_BY_HOUR,
            name="Departure Time",
            min_value=0.0,
            max_value_fn=lambda coord: 23.0,
            step=1.0,
            unit_fn=lambda coord: "h",
        ),
        TeslaSmartChargeNumberDescription(
            key="target_soc_low_rate",
            input_key=INPUT_OPPORTUNISTIC_SOC,
            name="Target SOC (Low Rate)",
            min_value=0.0,
            max_value_fn=lambda coord: 100.0,
            step=1.0,
            unit_fn=lambda coord: PERCENTAGE,
        ),
        TeslaSmartChargeNumberDescription(
            key="price_limit_threshold",
            input_key=INPUT_CHEAP_PRICE_THRESHOLD,
            name="Price Limit Threshold",
            min_value=0.0,
            max_value_fn=lambda coord: 0.2,
            step=0.001,
            unit_fn=_currency_per_kwh_unit,
        ),
        TeslaSmartChargeNumberDescription(
            key="target_energy",
            input_key=INPUT_TARGET_ENERGY,
            name="Target Energy",
            min_value=0.0,
            max_value_fn=_energy_max,
            step=0.1,
            unit_fn=lambda coord: "kWh",
            entity_registry_enabled_default=False,
        ),
        TeslaSmartChargeNumberDescription(
            key="target_distance",
            input_key=INPUT_TARGET_DISTANCE,
            name="Target Distance",
            min_value=0.0,
            max_value_fn=_distance_max,
            step=1.0,
            unit_fn=_distance_unit,
            entity_registry_enabled_default=False,
        ),
    ]

    entities = [
        TeslaSmartChargeNumber(coordinator, description) for description in descriptions
    ]
    async_add_entities(entities)


class TeslaSmartChargeNumber(CoordinatorEntity, NumberEntity, RestoreEntity):
    """Number entity for Tesla Smart Charge inputs."""

    entity_description: TeslaSmartChargeNumberDescription

    def __init__(
        self, coordinator: TeslaSmartChargeCoordinator, description: TeslaSmartChargeNumberDescription
    ) -> None:
        """Initialize the number entity."""

        super().__init__(coordinator)
        self.entity_description = description
        self._input_key = description.input_key
        self._attr_name = description.name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_native_min_value = description.min_value
        self._attr_native_step = description.step
        self._attr_entity_category = EntityCategory.CONFIG
        self._attr_device_info = get_device_info(coordinator.entry)
        coordinator.register_input_entity(self._input_key, self)

    @property
    def native_max_value(self) -> float:
        """Return the max allowed value."""

        return self.entity_description.max_value_fn(self.coordinator)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""

        return self.entity_description.unit_fn(self.coordinator)

    @property
    def native_value(self) -> float | None:
        """Return the current value."""

        return self.coordinator.inputs.get(self._input_key)

    async def async_set_native_value(self, value: float) -> None:
        """Handle a user update."""

        await self.coordinator.async_set_user_input(self._input_key, float(value))

    async def async_added_to_hass(self) -> None:
        """Restore previous state."""

        await super().async_added_to_hass()
        last_state = await self.async_get_last_state()
        if not last_state:
            return

        value = _safe_float(last_state.state)
        if value is None:
            return

        self.coordinator.set_input_value(self._input_key, value, set_last=False)
        self.async_write_ha_state()


def _energy_max(coordinator: TeslaSmartChargeCoordinator) -> float:
    """Compute max energy based on capacity."""

    return coordinator.battery_capacity_kwh or 100.0


def _distance_max(coordinator: TeslaSmartChargeCoordinator) -> float:
    """Compute max distance based on capacity and efficiency."""

    capacity = coordinator.battery_capacity_kwh
    efficiency = coordinator.vehicle_efficiency_wh_per_km
    if capacity <= 0 or efficiency <= 0:
        return 1000.0

    distance_km = (capacity * 1000.0) / efficiency
    if coordinator.inputs.distance_unit == DISTANCE_UNIT_MI:
        return distance_km / _KM_PER_MI
    return distance_km


def _distance_unit(coordinator: TeslaSmartChargeCoordinator) -> str | None:
    """Return distance unit based on current selection."""

    if coordinator.inputs.distance_unit == DISTANCE_UNIT_MI:
        return "mi"
    return "km"


def _currency_per_kwh_unit(coordinator: TeslaSmartChargeCoordinator) -> str | None:
    """Return unit label for a price threshold per kWh."""

    if coordinator.hass:
        currency = coordinator.hass.config.currency
    else:
        currency = "EUR"
    return f"{currency}/kWh"


def _safe_float(value: str | None) -> float | None:
    """Convert a string to float."""

    if value is None:
        return None

    try:
        return float(value)
    except ValueError:
        return None
