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
from .coordinator import (
    TariffMarketInsights,
    TeslaSmartChargeCoordinator,
    TeslaSmartChargeData,
    get_device_info,
)

_KM_PER_MI = 1.60934


@dataclass
class TeslaSmartChargeSensorDescription:
    """Description for Tesla Smart Charge sensors."""

    key: str
    name: str
    device_class: SensorDeviceClass | None
    state_class: SensorStateClass | None
    value_fn: Callable[[TeslaSmartChargeCoordinator], object | None]
    attrs_fn: Callable[[TeslaSmartChargeCoordinator], dict | None] | None = None
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
            key="energy_deficit",
            name="Energy Deficit",
            device_class=SensorDeviceClass.ENERGY,
            state_class=None,
            value_fn=lambda coord: _round_or_none(_data(coord).remaining_energy_kwh, 2),
            unit_fn=lambda coord: UnitOfEnergy.KILO_WATT_HOUR,
        ),
        TeslaSmartChargeSensorDescription(
            key="est_range_at_target_soc",
            name="Est. Range at Target SOC",
            device_class=SensorDeviceClass.DISTANCE,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=_distance_value,
            unit_fn=_distance_unit,
        ),
        TeslaSmartChargeSensorDescription(
            key="current_tariff_15m",
            name="Current Tariff (15m)",
            device_class=None,
            state_class=None,
            value_fn=lambda coord: len(_data(coord).tariff_prices or []),
            attrs_fn=_tariff_attrs,
        ),
        TeslaSmartChargeSensorDescription(
            key="spot_current_price",
            name="Current Spot Price",
            device_class=None,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda coord: _round_or_none(_insights(coord).current_price, 4),
            attrs_fn=_spot_current_price_attrs,
            unit_fn=_price_unit,
        ),
        TeslaSmartChargeSensorDescription(
            key="spot_price_delta",
            name="Price Change vs Previous Slot",
            device_class=None,
            state_class=SensorStateClass.MEASUREMENT,
            value_fn=lambda coord: _round_or_none(_insights(coord).delta_from_previous, 4),
            attrs_fn=_spot_price_delta_attrs,
            unit_fn=_price_unit,
        ),
        TeslaSmartChargeSensorDescription(
            key="spot_price_trend",
            name="Short-Term Price Trend",
            device_class=None,
            state_class=None,
            value_fn=lambda coord: _insights(coord).short_term_trend,
            attrs_fn=_spot_price_trend_attrs,
        ),
        TeslaSmartChargeSensorDescription(
            key="next_significant_low",
            name="Next Significant Low",
            device_class=SensorDeviceClass.TIMESTAMP,
            state_class=None,
            value_fn=_next_significant_low_value,
            attrs_fn=_next_significant_low_attrs,
        ),
        TeslaSmartChargeSensorDescription(
            key="spot_price_level",
            name="Current Price Level",
            device_class=None,
            state_class=None,
            value_fn=lambda coord: _insights(coord).relative_level,
            attrs_fn=_spot_price_level_attrs,
        ),
        TeslaSmartChargeSensorDescription(
            key="next_best_rate",
            name="Next Best Rate",
            device_class=SensorDeviceClass.TIMESTAMP,
            state_class=None,
            value_fn=_cheapest_slot_value,
            attrs_fn=_cheapest_slot_attrs,
        ),
        TeslaSmartChargeSensorDescription(
            key="next_start_time",
            name="Next Start Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            state_class=None,
            value_fn=lambda coord: _data(coord).optimized_start,
        ),
        TeslaSmartChargeSensorDescription(
            key="finish_time",
            name="Finish Time",
            device_class=SensorDeviceClass.TIMESTAMP,
            state_class=None,
            value_fn=lambda coord: _data(coord).optimized_end,
        ),
        TeslaSmartChargeSensorDescription(
            key="total_estimated_cost",
            name="Total Estimated Cost",
            device_class=SensorDeviceClass.MONETARY,
            state_class=None,
            value_fn=lambda coord: _round_or_none(_data(coord).optimized_cost, 2),
            unit_fn=_currency_unit,
        ),
        TeslaSmartChargeSensorDescription(
            key="energy_to_add",
            name="Energy to Add",
            device_class=SensorDeviceClass.ENERGY,
            state_class=None,
            value_fn=lambda coord: _round_or_none(_data(coord).optimized_energy_kwh, 2),
            unit_fn=lambda coord: UnitOfEnergy.KILO_WATT_HOUR,
        ),
        TeslaSmartChargeSensorDescription(
            key="active_charge_slots",
            name="Active Charge Slots",
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
        module_charge_controllable=None,
        plug_connected=None,
        tesla_scheduled_charging_enabled=None,
        remaining_energy_kwh=None,
        estimated_distance_km=None,
        tariff_prices=[],
        cheapest_slot=None,
        optimized_start=None,
        optimized_end=None,
        optimized_cost=None,
        optimized_energy_kwh=None,
        optimized_schedule=[],
        market_insights=TariffMarketInsights(),
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


def _insights(coordinator: TeslaSmartChargeCoordinator) -> TariffMarketInsights:
    """Return market insights with safe defaults."""

    return _data(coordinator).market_insights


def _tariff_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict:
    """Return tariff sensor attributes."""

    data = _data(coordinator)
    return {
        "prices": data.tariff_prices,
        "source": coordinator.tariff_source,
        "currency": _currency_unit(coordinator),
    }


def _spot_current_price_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict | None:
    """Return current spot price context."""

    insights = _insights(coordinator)
    slot = insights.current_slot
    if not slot:
        return None

    return {
        "start": dt_util.as_local(slot.start).isoformat(),
        "end": dt_util.as_local(slot.end).isoformat(),
        "source": coordinator.tariff_source,
    }


def _spot_price_delta_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict | None:
    """Return delta vs previous slot, including percentage change."""

    insights = _insights(coordinator)
    if insights.delta_from_previous is None:
        return None

    direction = "flat"
    if insights.delta_from_previous > 0:
        direction = "up"
    elif insights.delta_from_previous < 0:
        direction = "down"

    return {
        "current_price": _round_or_none(insights.current_price, 4),
        "previous_price": _round_or_none(insights.previous_price, 4),
        "delta_percent": _round_or_none(insights.delta_percent_from_previous, 1),
        "direction": direction,
    }


def _spot_price_trend_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict | None:
    """Return context for the short-term trend sensor."""

    insights = _insights(coordinator)
    if not insights.short_term_trend:
        return None

    return {
        "current_price": _round_or_none(insights.current_price, 4),
        "delta_vs_previous": _round_or_none(insights.delta_from_previous, 4),
        "price_level": insights.relative_level,
    }


def _next_significant_low_value(coordinator: TeslaSmartChargeCoordinator) -> object | None:
    """Return the start of the next significant low window."""

    return _insights(coordinator).next_low_window_start


def _next_significant_low_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict | None:
    """Return attributes for the next significant low window."""

    insights = _insights(coordinator)
    slot = insights.next_low_slot
    if not slot or not insights.next_low_window_start or not insights.next_low_window_end:
        return None

    duration_minutes = int(
        (insights.next_low_window_end - insights.next_low_window_start).total_seconds() / 60
    )
    return {
        "start": dt_util.as_local(insights.next_low_window_start).isoformat(),
        "end": dt_util.as_local(insights.next_low_window_end).isoformat(),
        "price": _round_or_none(slot.price, 4),
        "duration_minutes": duration_minutes,
    }


def _spot_price_level_attrs(coordinator: TeslaSmartChargeCoordinator) -> dict | None:
    """Return percentile-based context for the current price."""

    insights = _insights(coordinator)
    if insights.relative_level is None:
        return None

    status = "normal"
    if insights.relative_level in {"very_low", "low"}:
        status = "cheap"
    elif insights.relative_level in {"high", "very_high"}:
        status = "expensive"

    return {
        "percentile": _round_or_none(insights.current_price_percentile, 1),
        "status": status,
        "current_price": _round_or_none(insights.current_price, 4),
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


def _price_unit(coordinator: TeslaSmartChargeCoordinator) -> str | None:
    """Return a price-per-kWh unit based on the HA currency."""

    currency = _currency_unit(coordinator)
    if not currency:
        return None
    return f"{currency}/kWh"
