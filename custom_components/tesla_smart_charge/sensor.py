"""Sensor entities for Tesla Smart Charge."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DISTANCE_UNIT_MI, DOMAIN
from .coordinator import TeslaSmartChargeCoordinator, TeslaSmartChargeData, get_device_info

_KM_PER_MI = 1.60934


@dataclass
class TeslaSmartChargeSensorDescription:
    """Description for Tesla Smart Charge sensors."""

    key: str
    name: str
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None
    value_fn: Callable[[TeslaSmartChargeCoordinator], object | None]
    attrs_fn: Callable[[TeslaSmartChargeCoordinator], dict] | None = None
    unit_fn: Callable[[TeslaSmartChargeCoordinator], str | None] | None = None
    suggested_unit_of_measurement: str | None = None
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
    """Set up sensor entities."""

    coordinator: TeslaSmartChargeCoordinator = hass.data[DOMAIN][entry.entry_id]

    descriptions = [
        TeslaSmartChargeSensorDescription(
            key="remaining_energy_needed_kwh",
            name="Remaining Energy Needed",
            device_class=SensorDeviceClass.ENERGY,
            state_class=None,
            value_fn=lambda coord: _round_or_none(_data(coord).remaining_energy_kwh, 2),
            unit_fn=lambda coord: UnitOfEnergy.KILO_WATT_HOUR,
        ),
        TeslaSmartChargeSensorDescription(
            key="estimated_distance_after_charge",
            name="Estimated Distance After Charge",
            device_class=SensorDeviceClass.DISTANCE,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_distance_value,
            unit_fn=_distance_unit,
        ),
        TeslaSmartChargeSensorDescription(
            key="tariff_prices_15min",
            name="Tariff Prices 15min",
            device_class=None,
            state_class=None,
            value_fn=lambda coord: len(_data(coord).tariff_prices or []),
            attrs_fn=_tariff_attrs,
        ),
        TeslaSmartChargeSensorDescription(
            key="cheapest_next_slot",
            name="Cheapest Next Slot",
            device_class=SensorDeviceClass.TIMESTAMP,
            state_class=None,
            value_fn=_cheapest_slot_value,
            attrs_fn=_cheapest_slot_attrs,
        ),
        TeslaSmartChargeSensorDescription(
            key="optimized_start_time",
            name="Optimized Start Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            state_class=None,
            value_fn=lambda coord: _data(coord).optimized_start,
        ),
        TeslaSmartChargeSensorDescription(
            key="optimized_end_time",
            name="Optimized End Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            state_class=None,
            value_fn=lambda coord: _data(coord).optimized_end,
        ),
        TeslaSmartChargeSensorDescription(
            key="optimized_cost",
            name="Optimized Cost",
            device_class=SensorDeviceClass.MONETARY,
            state_class=None,
            value_fn=lambda coord: _round_or_none(_data(coord).optimized_cost, 2),
            unit_fn=_currency_unit,
        ),
        TeslaSmartChargeSensorDescription(
            key="optimized_energy_kwh",
            name="Optimized Energy",
            device_class=SensorDeviceClass.ENERGY,
            state_class=None,
            value_fn=lambda coord: _round_or_none(_data(coord).optimized_energy_kwh, 2),
            unit_fn=lambda coord: UnitOfEnergy.KILO_WATT_HOUR,
        ),
        TeslaSmartChargeSensorDescription(
            key="optimized_schedule",
            name="Optimized Schedule",
            device_class=None,
            state_class=None,
            value_fn=_schedule_enabled_count,
            attrs_fn=_schedule_attrs,
        ),
    ]

    entities = [TeslaSmartChargeSensor(coordinator, description) for description in descriptions]
    async_add_entities(entities)


class TeslaSmartChargeSensor(CoordinatorEntity, SensorEntity):
    """Sensor entity for Tesla Smart Charge."""

    entity_description: TeslaSmartChargeSensorDescription

    def __init__(
        self, coordinator: TeslaSmartChargeCoordinator, description: TeslaSmartChargeSensorDescription
    ) -> None:
        """Initialize the sensor."""

        super().__init__(coordinator)
        self.entity_description = description
        self._attr_name = description.name
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{description.key}"
        self._attr_device_class = description.device_class
        self._attr_state_class = description.state_class
        self._attr_device_info = get_device_info(coordinator.entry)

    @property
    def native_value(self) -> object | None:
        """Return the sensor value."""

        return self.entity_description.value_fn(self.coordinator)

    @property
    def extra_state_attributes(self) -> dict | None:
        """Return extra attributes."""

        if self.entity_description.attrs_fn:
            return self.entity_description.attrs_fn(self.coordinator)
        return None

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return the unit of measurement."""

        if self.entity_description.unit_fn:
            return self.entity_description.unit_fn(self.coordinator)
        return None


def _data(coordinator: TeslaSmartChargeCoordinator) -> TeslaSmartChargeData:
    """Return coordinator data with defaults."""

    return coordinator.data or TeslaSmartChargeData(
        remaining_energy_kwh=None,
        estimated_distance_km=None,
        tariff_prices=[],
        cheapest_slot=None,
        optimized_start=None,
        optimized_end=None,
        optimized_cost=None,
        optimized_energy_kwh=None,
        optimized_schedule=[],
    )


def _round_or_none(value: float | None, digits: int) -> float | None:
    """Round a value if present."""

    if value is None:
        return None
    return round(value, digits)


def _distance_value(coordinator: TeslaSmartChargeCoordinator) -> float | None:
    """Return distance adjusted for unit selection."""

    data = _data(coordinator)
    if data.estimated_distance_km is None:
        return None

    if coordinator.inputs.distance_unit == DISTANCE_UNIT_MI:
        return round(data.estimated_distance_km / _KM_PER_MI, 1)
    return round(data.estimated_distance_km, 1)


def _distance_unit(coordinator: TeslaSmartChargeCoordinator) -> str | None:
    """Return the configured distance unit."""

    if coordinator.inputs.distance_unit == DISTANCE_UNIT_MI:
        return "mi"
    return "km"


def _tariff_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict:
    """Return tariff sensor attributes."""

    data = _data(coordinator)
    return {
        "prices": data.tariff_prices,
        "source": coordinator.tariff_source,
        "currency": _currency_unit(coordinator),
    }


def _cheapest_slot_value(coordinator: TeslaSmartChargeCoordinator) -> object | None:
    """Return the next cheapest slot start time."""

    slot = _data(coordinator).cheapest_slot
    if not slot:
        return None
    return slot.start


def _cheapest_slot_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict | None:
    """Return cheapest slot attributes."""

    slot = _data(coordinator).cheapest_slot
    if not slot:
        return None

    return {
        "start": dt_util.as_local(slot.start).isoformat(),
        "end": dt_util.as_local(slot.end).isoformat(),
        "price": slot.price,
    }


def _schedule_enabled_count(coordinator: TeslaSmartChargeCoordinator) -> int:
    """Return count of enabled schedule slots."""

    schedule = _data(coordinator).optimized_schedule or []
    return sum(1 for item in schedule if item.get("enabled"))


def _schedule_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict:
    """Return schedule attributes."""

    return {"schedule": _data(coordinator).optimized_schedule}


def _currency_unit(coordinator: TeslaSmartChargeCoordinator) -> str | None:
    """Return the configured currency."""

    if coordinator.hass:
        return coordinator.hass.config.currency
    return None
