"""Coordinator for Tesla Smart Charge integration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any

from aiohttp import ClientError, ClientTimeout
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_OFF,
    STATE_ON,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.event import async_track_state_change_event, async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import (
    CONF_BATTERY_CAPACITY,
    CONF_BATTERY_SENSOR,
    CONF_CHARGE_LIMIT_NUMBER,
    CONF_CHARGER_CONNECTED_SENSOR,
    CONF_CHARGER_POWER_SENSOR,
    CONF_CHARGER_SWITCH,
    CONF_CHARGING_AMPS_NUMBER,
    CONF_CHARGING_SENSOR,
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
    DEFAULT_ALLOW_IMMEDIATE_CHARGE,
    DEFAULT_CHEAP_PRICE_THRESHOLD,
    DEFAULT_DISTANCE_UNIT,
    DEFAULT_OPPORTUNISTIC_SOC,
    DEFAULT_READY_BY_HOUR,
    DEFAULT_SMART_CHARGING_ENABLED,
    DEFAULT_TARGET_DISTANCE,
    DEFAULT_TARGET_ENERGY_KWH,
    DEFAULT_TARGET_SOC,
    DISTANCE_UNIT_MI,
    DOMAIN,
    INPUT_ALLOW_IMMEDIATE_CHARGE,
    INPUT_CHEAP_PRICE_THRESHOLD,
    INPUT_DISTANCE_UNIT,
    INPUT_OPPORTUNISTIC_SOC,
    INPUT_READY_BY_HOUR,
    INPUT_SMART_CHARGING_ENABLED,
    INPUT_TARGET_DISTANCE,
    INPUT_TARGET_ENERGY,
    INPUT_TARGET_SOC,
    PLANNING_HORIZON_WEEK,
    TARIFF_SOURCE_REST,
    TARIFF_SOURCE_SENSOR,
    TARIFF_SOURCE_SPOT,
    TARIFF_SOURCE_SPOT_TOMORROW,
)
from .optimizer import (
    OptimizerResult,
    TariffSlot,
    optimize_schedule,
)

_LOGGER = logging.getLogger(__name__)

_KM_PER_MI = 1.60934

_SOBRY_SPOT_URL = "https://api.sobry.co/api/prices/raw"
_SOBRY_RAW_PRICING_PARAMS = {
    "segment": "C5",
    "turpe": "CU4",
    "profil": "particulier",
    "display": "TTC",
}
_SOBRY_HEADERS = {
    "User-Agent": "sobry-energy-app/0.1 (+https://sobry.co)",
    "Accept": "application/json",
}
# Day-ahead data is typically published around 12:55-13:08 local time.
# We gate tomorrow fetches slightly after that window to avoid premature requests.
_DAY_AHEAD_PUBLISH_HOUR = 13
_DAY_AHEAD_PUBLISH_MINUTE = 10
_FORCE_CHARGE_LIMIT_MARGIN_SOC = 1.0

_ENERGY_INPUT_KEYS = {
    INPUT_TARGET_SOC,
    INPUT_TARGET_ENERGY,
    INPUT_TARGET_DISTANCE,
}


@dataclass
class TeslaVehicleState:
    """Snapshot of Tesla entity values."""

    soc: float | None = None
    charging: bool | None = None
    charger_switch_on: bool | None = None
    charger_power_kw: float | None = None
    range_km: float | None = None
    time_charge_complete: datetime | None = None
    charge_limit: float | None = None
    charging_amps: float | None = None
    charger_connected: bool | None = None
    scheduled_charging_enabled: bool | None = None


@dataclass
class TeslaSmartChargeInputs:
    """User inputs and preferences."""

    target_soc: float = DEFAULT_TARGET_SOC
    target_energy_kwh: float = DEFAULT_TARGET_ENERGY_KWH
    target_distance: float = DEFAULT_TARGET_DISTANCE
    ready_by_hour: float = DEFAULT_READY_BY_HOUR
    opportunistic_target_soc: float = DEFAULT_OPPORTUNISTIC_SOC
    cheap_price_threshold: float = DEFAULT_CHEAP_PRICE_THRESHOLD
    distance_unit: str = DEFAULT_DISTANCE_UNIT
    smart_charging_enabled: bool = DEFAULT_SMART_CHARGING_ENABLED
    allow_immediate_charge: bool = DEFAULT_ALLOW_IMMEDIATE_CHARGE
    last_user_input: str = INPUT_TARGET_SOC

    def get(self, key: str) -> Any:
        """Return an input value by key."""

        return getattr(self, key)

    def set(self, key: str, value: Any, set_last: bool = True) -> None:
        """Set an input value by key."""

        setattr(self, key, value)
        if set_last:
            self.last_user_input = key


@dataclass
class TeslaSmartChargeData:
    """Coordinator data used by sensors."""

    module_charge_controllable: bool | None
    plug_connected: bool | None
    tesla_scheduled_charging_enabled: bool | None
    remaining_energy_kwh: float | None
    estimated_distance_km: float | None
    tariff_prices: list[dict]
    cheapest_slot: TariffSlot | None
    optimized_start: datetime | None
    optimized_end: datetime | None
    optimized_cost: float | None
    optimized_energy_kwh: float | None
    optimized_schedule: list[dict]


def get_device_info(entry: ConfigEntry) -> DeviceInfo:
    """Return device info for the integration."""

    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name="Tesla Smart Charge",
        manufacturer="Tesla Smart Charge",
        model="Entity-Bound Optimizer",
    )


class TeslaSmartChargeCoordinator(DataUpdateCoordinator[TeslaSmartChargeData]):
    """DataUpdateCoordinator for Tesla Smart Charge."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the coordinator."""

        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=5),
        )
        self.entry = entry
        self.inputs = TeslaSmartChargeInputs()
        self._input_entities: dict[str, Any] = {}
        self._vehicle_state = TeslaVehicleState()
        self._tariff_slots: list[TariffSlot] = []
        self._enabled_slots: list[TariffSlot] = []
        self._bonus_slots: set[TariffSlot] = set()
        self._last_charging_power_kw: float | None = None
        self._temporary_charge_limit_restore_soc: float | None = None
        self._hold_restored_charge_limit = False

        self._battery_capacity_kwh = _safe_float(entry.data.get(CONF_BATTERY_CAPACITY)) or 0.0
        self._vehicle_efficiency_wh_per_km = (
            _safe_float(entry.data.get(CONF_VEHICLE_EFFICIENCY)) or 0.0
        )
        self._max_charging_power_kw = (
            _safe_float(entry.data.get(CONF_MAX_CHARGING_POWER)) or 0.0
        )
        self._tariff_source = entry.data.get(CONF_TARIFF_SOURCE, TARIFF_SOURCE_SENSOR)

    @property
    def tariff_source(self) -> str:
        """Return the tariff source."""

        return self._tariff_source

    @property
    def battery_capacity_kwh(self) -> float:
        """Return configured battery capacity."""

        return self._battery_capacity_kwh

    @property
    def vehicle_efficiency_wh_per_km(self) -> float:
        """Return configured vehicle efficiency."""

        return self._vehicle_efficiency_wh_per_km

    @property
    def max_charging_power_kw(self) -> float:
        """Return configured max charging power."""

        return self._max_charging_power_kw

    @callback
    def async_setup_listeners(self) -> list[callable]:
        """Set up listeners for source entity changes."""

        entity_ids = [
            self.entry.data.get(CONF_BATTERY_SENSOR),
            self.entry.data.get(CONF_CHARGING_SENSOR),
            self.entry.data.get(CONF_CHARGER_SWITCH),
            self.entry.data.get(CONF_CHARGER_POWER_SENSOR),
            self.entry.data.get(CONF_CHARGE_LIMIT_NUMBER),
            self.entry.data.get(CONF_CHARGING_AMPS_NUMBER),
            self.entry.data.get(CONF_RANGE_SENSOR),
            self.entry.data.get(CONF_TIME_CHARGE_COMPLETE_SENSOR),
            self.entry.data.get(CONF_CHARGER_CONNECTED_SENSOR),
            self._scheduled_charging_entity_id(),
        ]
        if self._tariff_source == TARIFF_SOURCE_SENSOR:
            entity_ids.append(self.entry.data.get(CONF_TARIFF_SENSOR))

        tracked = [entity_id for entity_id in entity_ids if entity_id]
        unsub_state = async_track_state_change_event(
            self.hass, tracked, self._handle_source_event
        )
        unsub_time = async_track_time_interval(
            self.hass, self._handle_time_event, timedelta(minutes=1)
        )

        return [unsub_state, unsub_time]

    def register_input_entity(self, key: str, entity: Any) -> None:
        """Register an input entity for refresh callbacks."""

        self._input_entities[key] = entity

    def set_input_value(self, key: str, value: Any, set_last: bool = False) -> None:
        """Set input value without scheduling refresh."""

        value = self._normalize_input_value(key, value)
        self.inputs.set(key, value, set_last=set_last)

    async def async_set_user_input(self, key: str, value: Any) -> None:
        """Handle a user input change."""

        value = self._normalize_input_value(key, value)
        set_last = key in _ENERGY_INPUT_KEYS
        self.inputs.set(key, value, set_last=set_last)
        primary_key = self.inputs.last_user_input
        await self._async_sync_inputs(primary_key)
        self._notify_input_entities()
        await self.async_request_refresh()

    async def async_apply_control(self) -> None:
        """Apply optimized schedule to the charger switch."""

        if not self.inputs.smart_charging_enabled:
            await self._async_set_charge_limit(apply_configured_target=False)
            return

        charger_switch = self.entry.data.get(CONF_CHARGER_SWITCH)
        if not charger_switch:
            await self._async_set_charge_limit(apply_configured_target=False)
            return

        if self.inputs.allow_immediate_charge:
            _LOGGER.debug("Immediate charge enabled; turning on charger")
            await self._async_turn_on(charger_switch)
            await self._async_set_charge_limit(force_for_active_charge=True)
            return

        now = dt_util.now()
        current_slot = next(
            (slot for slot in self._enabled_slots if slot.start <= now < slot.end),
            None,
        )
        in_slot = current_slot is not None
        in_bonus_slot = current_slot in self._bonus_slots if current_slot else False
        _LOGGER.debug(
            "Applying schedule control: in_slot=%s in_bonus_slot=%s",
            in_slot,
            in_bonus_slot,
        )

        if in_slot:
            await self._async_turn_on(charger_switch)
        else:
            await self._async_turn_off(charger_switch)

        await self._async_set_charge_limit(
            use_bonus_target=in_bonus_slot,
            force_for_active_charge=in_slot,
        )

    @callback
    def _handle_source_event(self, event: Any) -> None:
        """React to source entity changes."""

        self.async_update_listeners()
        _LOGGER.debug("Source entity change detected, refreshing optimizer")
        self.hass.async_create_task(self.async_request_refresh())

    @callback
    def _handle_time_event(self, now: datetime) -> None:
        """Apply control on a schedule."""

        self.hass.async_create_task(self.async_apply_control())

    async def _async_update_data(self) -> TeslaSmartChargeData:
        """Fetch data for the coordinator."""

        try:
            now = dt_util.now()
            vehicle_state = self._read_vehicle_state()
            self._vehicle_state = vehicle_state

            tariff_slots = await self._async_get_tariff_slots()
            self._tariff_slots = tariff_slots

            charging_power_kw = self._calculate_charging_power_kw(vehicle_state)
            self._last_charging_power_kw = charging_power_kw

            await self._async_sync_inputs(self.inputs.last_user_input, vehicle_state)
            self._notify_input_entities()

            required_energy_kwh = max(0.0, self.inputs.target_energy_kwh or 0.0)
            remaining_energy_kwh = required_energy_kwh
            estimated_distance_km = self._estimate_distance_after_charge(
                vehicle_state, required_energy_kwh
            )
            module_charge_controllable = self._is_module_charge_controllable(vehicle_state)

            optimizer_result, horizon_slots, bonus_slots = self._optimize_ready_window(
                required_energy_kwh=required_energy_kwh,
                charging_power_kw=charging_power_kw,
                tariff_slots=tariff_slots,
                vehicle_state=vehicle_state,
                now=now,
            )
            self._enabled_slots = optimizer_result.enabled_slots
            self._bonus_slots = bonus_slots
            _LOGGER.debug(
                (
                    "Optimizer result: energy=%.2f kWh power=%.2f kW slots=%d enabled=%d "
                    "bonus=%d cost=%.2f"
                ),
                required_energy_kwh,
                charging_power_kw,
                len(tariff_slots),
                len(optimizer_result.enabled_slots),
                len(bonus_slots),
                optimizer_result.total_cost,
            )

            tariff_prices = [
                {
                    "start": dt_util.as_local(slot.start).isoformat(),
                    "end": dt_util.as_local(slot.end).isoformat(),
                    "price": slot.price,
                }
                for slot in sorted(tariff_slots, key=lambda item: item.start)
            ]

            cheapest_slot = None
            if horizon_slots:
                future_slots = [slot for slot in horizon_slots if slot.end > now]
                if future_slots:
                    cheapest_slot = min(future_slots, key=lambda item: item.price)

            return TeslaSmartChargeData(
                module_charge_controllable=module_charge_controllable,
                plug_connected=vehicle_state.charger_connected,
                tesla_scheduled_charging_enabled=vehicle_state.scheduled_charging_enabled,
                remaining_energy_kwh=remaining_energy_kwh,
                estimated_distance_km=estimated_distance_km,
                tariff_prices=tariff_prices,
                cheapest_slot=cheapest_slot,
                optimized_start=optimizer_result.start,
                optimized_end=optimizer_result.end,
                optimized_cost=optimizer_result.total_cost,
                optimized_energy_kwh=optimizer_result.total_energy_kwh,
                optimized_schedule=optimizer_result.schedule,
            )
        except Exception as err:
            raise UpdateFailed(str(err)) from err

    async def _async_sync_inputs(
        self,
        primary_key: str,
        vehicle_state: TeslaVehicleState | None = None,
    ) -> None:
        """Sync input values based on the primary input and latest state."""

        vehicle_state = vehicle_state or self._vehicle_state
        energy_needed = self._calculate_energy_needed(
            primary_key,
            vehicle_state,
        )
        energy_needed = max(0.0, energy_needed)
        _LOGGER.debug(
            "Sync inputs: primary=%s energy_needed=%.2f",
            primary_key,
            energy_needed,
        )

        self.inputs.set(INPUT_TARGET_ENERGY, _round(energy_needed, 2), set_last=False)

        if (
            primary_key != INPUT_TARGET_SOC
            and vehicle_state.soc is not None
            and self._battery_capacity_kwh > 0
        ):
            target_soc = vehicle_state.soc + (energy_needed / self._battery_capacity_kwh) * 100
            target_soc = min(100.0, max(0.0, target_soc))
            self.inputs.set(INPUT_TARGET_SOC, _round(target_soc, 0), set_last=False)

        if self._vehicle_efficiency_wh_per_km > 0:
            distance_km = (energy_needed * 1000.0) / self._vehicle_efficiency_wh_per_km
            if self.inputs.distance_unit == DISTANCE_UNIT_MI:
                distance_value = distance_km / _KM_PER_MI
            else:
                distance_value = distance_km
            self.inputs.set(
                INPUT_TARGET_DISTANCE,
                _round(distance_value, 1),
                set_last=False,
            )

    def _calculate_energy_needed(
        self,
        primary_key: str,
        vehicle_state: TeslaVehicleState,
    ) -> float:
        """Calculate required energy based on the selected input."""

        fallback_energy = self.inputs.target_energy_kwh or 0.0

        if primary_key == INPUT_TARGET_SOC:
            if vehicle_state.soc is None or self._battery_capacity_kwh <= 0:
                return fallback_energy
            target_soc = self.inputs.target_soc or 0.0
            return max(
                0.0,
                (target_soc - vehicle_state.soc) * self._battery_capacity_kwh / 100.0,
            )

        if primary_key == INPUT_TARGET_DISTANCE:
            if self._vehicle_efficiency_wh_per_km <= 0:
                return fallback_energy
            distance = self.inputs.target_distance or 0.0
            if self.inputs.distance_unit == DISTANCE_UNIT_MI:
                distance_km = distance * _KM_PER_MI
            else:
                distance_km = distance
            return max(0.0, (distance_km * self._vehicle_efficiency_wh_per_km) / 1000.0)

        return fallback_energy

    def _optimize_ready_window(
        self,
        required_energy_kwh: float,
        charging_power_kw: float,
        tariff_slots: list[TariffSlot],
        vehicle_state: TeslaVehicleState,
        now: datetime,
    ) -> tuple[OptimizerResult, list[TariffSlot], set[TariffSlot]]:
        """Build a two-stage schedule: required SOC by deadline, bonus SOC on full future horizon."""

        if charging_power_kw <= 0 or not tariff_slots:
            return OptimizerResult([], [], None, None, 0.0, 0.0), [], set()

        future_slots = sorted(
            [slot for slot in tariff_slots if slot.end > now],
            key=lambda slot: slot.start,
        )
        if not future_slots:
            return OptimizerResult([], [], None, None, 0.0, 0.0), [], set()

        ready_slots = self._slots_until_ready_deadline(future_slots, now)
        required_scope = ready_slots if ready_slots else future_slots

        required_result = optimize_schedule(
            required_energy_kwh,
            charging_power_kw,
            required_scope,
            None,
            PLANNING_HORIZON_WEEK,
            now,
        )
        required_slots = set(required_result.enabled_slots)
        bonus_slots: set[TariffSlot] = set()

        bonus_energy_kwh = self._calculate_bonus_energy_kwh(vehicle_state, required_energy_kwh)
        cheap_threshold = _safe_float(self.inputs.cheap_price_threshold) or 0.0
        if bonus_energy_kwh > 0 and cheap_threshold > 0:
            bonus_candidates = [
                slot
                for slot in future_slots
                if slot not in required_slots and slot.price <= cheap_threshold
            ]
            if bonus_candidates:
                bonus_result = optimize_schedule(
                    bonus_energy_kwh,
                    charging_power_kw,
                    bonus_candidates,
                    None,
                    PLANNING_HORIZON_WEEK,
                    now,
                )
                bonus_slots = set(bonus_result.enabled_slots)

        enabled_slots = sorted(required_slots | bonus_slots, key=lambda slot: slot.start)
        if not enabled_slots:
            return OptimizerResult([], [], None, None, 0.0, 0.0), future_slots, bonus_slots

        schedule: list[dict] = []
        total_energy = 0.0
        total_cost = 0.0
        soc_projection = _safe_float(vehicle_state.soc)
        can_project_soc = soc_projection is not None and self._battery_capacity_kwh > 0
        if can_project_soc:
            soc_projection = max(0.0, min(100.0, soc_projection))

        for slot in future_slots:
            enabled = slot in required_slots or slot in bonus_slots
            if slot in required_slots:
                stage = "required"
            elif slot in bonus_slots:
                stage = "cheap_bonus"
            else:
                stage = "disabled"

            if enabled:
                slot_energy = charging_power_kw * slot.duration_hours
                total_energy += slot_energy
                total_cost += slot_energy * slot.price
                if can_project_soc and soc_projection is not None:
                    soc_projection = min(
                        100.0,
                        soc_projection + (slot_energy / self._battery_capacity_kwh) * 100.0,
                    )

            soc_end = _round(soc_projection, 2) if can_project_soc and soc_projection is not None else None

            schedule.append(
                {
                    "start": dt_util.as_local(slot.start).isoformat(),
                    "end": dt_util.as_local(slot.end).isoformat(),
                    "price": slot.price,
                    "enabled": enabled,
                    "stage": stage,
                    "soc_end": soc_end,
                }
            )

        return (
            OptimizerResult(
                schedule=schedule,
                enabled_slots=enabled_slots,
                start=enabled_slots[0].start,
                end=enabled_slots[-1].end,
                total_cost=total_cost,
                total_energy_kwh=total_energy,
            ),
            future_slots,
            bonus_slots,
        )

    def _slots_until_ready_deadline(
        self, tariff_slots: list[TariffSlot], now: datetime
    ) -> list[TariffSlot]:
        """Return slots between now and the effective ready deadline (today or tomorrow)."""

        deadline = self._next_ready_deadline(now)
        future_slots = sorted(
            (slot for slot in tariff_slots if slot.end > now),
            key=lambda slot: slot.start,
        )
        return [slot for slot in future_slots if slot.end <= deadline]

    def _next_ready_deadline(self, now: datetime) -> datetime:
        """Return ready deadline at configured hour for today, else tomorrow (local time)."""

        local_now = dt_util.as_local(now)
        ready_hour = int(_safe_float(self.inputs.ready_by_hour) or DEFAULT_READY_BY_HOUR)
        ready_hour = max(0, min(23, ready_hour))
        today_deadline = local_now.replace(
            hour=ready_hour,
            minute=0,
            second=0,
            microsecond=0,
        )
        if local_now < today_deadline:
            return today_deadline
        return today_deadline + timedelta(days=1)

    def _calculate_bonus_energy_kwh(
        self, vehicle_state: TeslaVehicleState, required_energy_kwh: float
    ) -> float:
        """Return additional energy needed to reach opportunistic SOC target."""

        if vehicle_state.soc is None or self._battery_capacity_kwh <= 0:
            return 0.0

        current_soc = vehicle_state.soc
        bonus_soc = self._bonus_target_soc()
        total_bonus_energy_kwh = max(
            0.0,
            (bonus_soc - current_soc) * self._battery_capacity_kwh / 100.0,
        )
        return max(0.0, total_bonus_energy_kwh - required_energy_kwh)

    def _is_module_charge_controllable(self, vehicle_state: TeslaVehicleState) -> bool | None:
        """Return whether module control prerequisites are met."""

        if (
            vehicle_state.charger_connected is None
            or vehicle_state.scheduled_charging_enabled is None
        ):
            return None

        return vehicle_state.charger_connected and not vehicle_state.scheduled_charging_enabled

    def _normalize_input_value(self, key: str, value: Any) -> Any:
        """Normalize input values."""

        if key in (INPUT_TARGET_SOC, INPUT_OPPORTUNISTIC_SOC):
            numeric = _safe_float(value)
            if numeric is None:
                return value
            return max(0.0, min(100.0, numeric))

        if key == INPUT_READY_BY_HOUR:
            numeric = _safe_float(value)
            if numeric is None:
                return value
            return float(max(0, min(23, round(numeric))))

        if key == INPUT_CHEAP_PRICE_THRESHOLD:
            numeric = _safe_float(value)
            if numeric is None:
                return value
            return max(0.0, min(0.2, numeric))

        return value

    def _bonus_target_soc(self) -> float:
        """Return opportunistic SOC target clamped above minimum SOC."""

        min_soc = _safe_float(self.inputs.target_soc) or 0.0
        opportunistic_soc = _safe_float(self.inputs.opportunistic_target_soc) or min_soc
        return min(100.0, max(min_soc, opportunistic_soc))

    def _estimate_distance_after_charge(
        self, vehicle_state: TeslaVehicleState, energy_needed_kwh: float
    ) -> float | None:
        """Estimate driving distance after charging."""

        if (
            self._battery_capacity_kwh <= 0
            or self._vehicle_efficiency_wh_per_km <= 0
            or vehicle_state.soc is None
        ):
            return None

        current_energy = (vehicle_state.soc / 100.0) * self._battery_capacity_kwh
        total_energy = min(self._battery_capacity_kwh, current_energy + energy_needed_kwh)
        return (total_energy * 1000.0) / self._vehicle_efficiency_wh_per_km

    def _calculate_charging_power_kw(self, vehicle_state: TeslaVehicleState) -> float:
        """Return the effective charging power."""

        power_kw = vehicle_state.charger_power_kw
        if power_kw is None or power_kw <= 0:
            power_kw = self._max_charging_power_kw

        if self._max_charging_power_kw > 0:
            power_kw = min(power_kw, self._max_charging_power_kw)

        return max(0.0, power_kw or 0.0)

    async def _async_get_tariff_slots(self) -> list[TariffSlot]:
        """Load tariff slots from the configured source."""

        try:
            if self._tariff_source == TARIFF_SOURCE_REST:
                slots = await self._async_fetch_tariff_from_rest()
            elif self._tariff_source == TARIFF_SOURCE_SPOT:
                slots = await self._async_fetch_tariff_from_spot()
            elif self._tariff_source == TARIFF_SOURCE_SPOT_TOMORROW:
                slots = await self._async_fetch_tariff_from_spot_tomorrow()
            else:
                slots = self._async_fetch_tariff_from_sensor()
        except UpdateFailed as err:
            if self._tariff_slots:
                _LOGGER.warning(
                    "Tariff fetch failed for source %s: %s. Reusing %d cached slots.",
                    self._tariff_source,
                    err,
                    len(self._tariff_slots),
                )
                slots = self._tariff_slots
            else:
                _LOGGER.warning(
                    "Tariff fetch failed for source %s: %s. Continuing with empty slots.",
                    self._tariff_source,
                    err,
                )
                slots = []
        except Exception as err:  # pragma: no cover - defensive safety net
            if self._tariff_slots:
                _LOGGER.exception(
                    "Unexpected tariff fetch error for source %s. Reusing %d cached slots.",
                    self._tariff_source,
                    len(self._tariff_slots),
                )
                slots = self._tariff_slots
            else:
                _LOGGER.exception(
                    "Unexpected tariff fetch error for source %s. Continuing with empty slots.",
                    self._tariff_source,
                )
                slots = []

        _LOGGER.debug("Loaded %d tariff slots from %s", len(slots), self._tariff_source)
        return slots

    def _async_fetch_tariff_from_sensor(self) -> list[TariffSlot]:
        """Parse tariff slots from a sensor attribute."""

        sensor_id = self.entry.data.get(CONF_TARIFF_SENSOR)
        attribute = self.entry.data.get(CONF_TARIFF_ATTRIBUTE)
        if not sensor_id or not attribute:
            return []

        state = self.hass.states.get(sensor_id)
        if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            return []

        raw = state.attributes.get(attribute)
        return self._parse_tariff_list(raw)

    async def _async_fetch_tariff_from_rest(self) -> list[TariffSlot]:
        """Fetch tariff slots from a REST endpoint."""

        url = self.entry.data.get(CONF_TARIFF_REST_URL)
        if not url:
            return []

        headers = self.entry.data.get(CONF_TARIFF_REST_HEADERS)
        session = async_get_clientsession(self.hass)

        async with session.get(
            url, headers=headers, timeout=ClientTimeout(total=15)
        ) as resp:
            if resp.status >= 400:
                raise UpdateFailed(f"Tariff REST error {resp.status}")
            data = await resp.json()

        path = self.entry.data.get(CONF_TARIFF_REST_JSON_PATH)
        if path:
            data = _resolve_json_path(data, path)

        return self._parse_tariff_list(data)

    async def _async_fetch_tariff_from_spot(self) -> list[TariffSlot]:
        """Fetch spot slots from now until end of tomorrow (J+1)."""

        now = dt_util.now()
        now_local = dt_util.as_local(now)
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        day_after_start = tomorrow_start + timedelta(days=1)
        horizon_end = day_after_start

        today_slots = await self._async_fetch_spot_raw_window(
            start_date=today_start.date().isoformat(),
            end_date=tomorrow_start.date().isoformat(),
        )

        tomorrow_slots: list[TariffSlot] = []
        if (
            now_local.hour > _DAY_AHEAD_PUBLISH_HOUR
            or (
                now_local.hour == _DAY_AHEAD_PUBLISH_HOUR
                and now_local.minute >= _DAY_AHEAD_PUBLISH_MINUTE
            )
        ):
            try:
                tomorrow_slots = await self._async_fetch_spot_raw_window(
                    start_date=tomorrow_start.date().isoformat(),
                    end_date=day_after_start.date().isoformat(),
                )
            except UpdateFailed as err:
                _LOGGER.debug("Tomorrow raw prices unavailable yet: %s", err)
        else:
            _LOGGER.debug(
                "Skipping tomorrow raw fetch before %02d:%02d local time",
                _DAY_AHEAD_PUBLISH_HOUR,
                _DAY_AHEAD_PUBLISH_MINUTE,
            )

        merged: dict[datetime, TariffSlot] = {}
        for slot in today_slots + tomorrow_slots:
            merged[slot.start] = slot

        if not tomorrow_slots and self._tariff_slots:
            cached_tomorrow = [
                slot
                for slot in self._tariff_slots
                if slot.start >= tomorrow_start and slot.start < day_after_start
            ]
            for slot in cached_tomorrow:
                merged.setdefault(slot.start, slot)

        slots = sorted(merged.values(), key=lambda slot: slot.start)
        # Keep the in-progress slot (end > now) so control can start charging immediately.
        return [slot for slot in slots if slot.end > now and slot.start < horizon_end]

    async def _async_fetch_tariff_from_spot_tomorrow(self) -> list[TariffSlot]:
        """Backward-compatible alias to raw rolling source."""

        return await self._async_fetch_tariff_from_spot()

    async def _async_fetch_spot_raw_window(
        self, start_date: str, end_date: str
    ) -> list[TariffSlot]:
        """Fetch Sobry raw prices for a date window."""

        params = {
            "start": start_date,
            "end": end_date,
            **_SOBRY_RAW_PRICING_PARAMS,
        }
        data = await self._async_fetch_sobry_raw_payload(params, start_date, end_date)
        normalized = _normalize_sobry_prices(data)
        slots = self._parse_tariff_list(normalized)
        if slots:
            _LOGGER.debug(
                "Sobry raw %s->%s returned %d entries, parsed %d slots (pricing params)",
                start_date,
                end_date,
                len(normalized),
                len(slots),
            )
            return slots

        _LOGGER.warning(
            "Sobry raw %s->%s produced no usable slots with pricing params; retrying spot-only payload.",
            start_date,
            end_date,
        )
        fallback_params = {"start": start_date, "end": end_date}
        fallback_data = await self._async_fetch_sobry_raw_payload(
            fallback_params, start_date, end_date
        )
        fallback_normalized = _normalize_sobry_prices(fallback_data)
        fallback_slots = self._parse_tariff_list(fallback_normalized)
        _LOGGER.warning(
            "Sobry raw fallback %s->%s returned %d entries, parsed %d slots.",
            start_date,
            end_date,
            len(fallback_normalized),
            len(fallback_slots),
        )
        return fallback_slots

    async def _async_fetch_sobry_raw_payload(
        self, params: dict[str, str], start_date: str, end_date: str
    ) -> Any:
        """Request Sobry raw payload and return parsed JSON."""

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                _SOBRY_SPOT_URL,
                params=params,
                headers=_SOBRY_HEADERS,
                timeout=ClientTimeout(total=20),
            ) as resp:
                if resp.status >= 400:
                    raise UpdateFailed(
                        f"Spot raw API error {resp.status} for {start_date}->{end_date}"
                    )
                return await resp.json(content_type=None)
        except ClientError as err:
            raise UpdateFailed("Unable to fetch spot raw prices") from err
        except ValueError as err:
            raise UpdateFailed("Invalid spot raw payload") from err

    def _parse_tariff_list(self, raw: Any) -> list[TariffSlot]:
        """Parse a list of tariff entries into slots."""

        if isinstance(raw, dict):
            if raw.get("success") is False:
                return []
            if isinstance(raw.get("prices"), list):
                raw = raw.get("prices")
            elif isinstance(raw.get("data"), list):
                raw = raw.get("data")

        if not isinstance(raw, list):
            return []

        if raw and all(isinstance(item, (int, float)) for item in raw):
            return _build_slots_from_prices(raw)

        entries: list[dict[str, Any]] = []
        for item in raw:
            if not isinstance(item, dict):
                continue

            start = _parse_datetime(
                item.get("start")
                or item.get("timestamp")
                or item.get("time")
                or item.get("from")
                or item.get("date")
            )
            if not start:
                continue

            end = _parse_datetime(item.get("end") or item.get("to"))
            duration = _safe_float(item.get("duration_minutes") or item.get("duration"))

            price = _safe_float(_extract_price(item))
            if price is None:
                continue

            entries.append({"start": start, "end": end, "duration": duration, "price": price})

        if not entries:
            return []

        entries.sort(key=lambda entry: entry["start"])
        slots: list[TariffSlot] = []
        last_duration: timedelta | None = None

        for index, entry in enumerate(entries):
            start = entry["start"]
            end = entry["end"]
            duration = entry["duration"]

            if not end:
                if duration:
                    end = start + timedelta(minutes=duration)
                    last_duration = timedelta(minutes=duration)
                else:
                    next_start = (
                        entries[index + 1]["start"] if index + 1 < len(entries) else None
                    )
                    if next_start and next_start > start:
                        end = next_start
                        last_duration = end - start
                    elif last_duration:
                        end = start + last_duration
                    else:
                        end = start + timedelta(minutes=15)

            slots.append(TariffSlot(start=start, end=end, price=entry["price"]))

        return slots

    def _read_vehicle_state(self) -> TeslaVehicleState:
        """Read current vehicle state from mapped entities."""

        battery_state = self.hass.states.get(self.entry.data.get(CONF_BATTERY_SENSOR))
        charging_state = self.hass.states.get(self.entry.data.get(CONF_CHARGING_SENSOR))
        charger_switch_state = self.hass.states.get(
            self.entry.data.get(CONF_CHARGER_SWITCH)
        )
        charger_power_state = self.hass.states.get(
            self.entry.data.get(CONF_CHARGER_POWER_SENSOR)
        )
        range_state = self.hass.states.get(self.entry.data.get(CONF_RANGE_SENSOR))
        time_charge_state = self.hass.states.get(
            self.entry.data.get(CONF_TIME_CHARGE_COMPLETE_SENSOR)
        )
        charge_limit_state = self.hass.states.get(
            self.entry.data.get(CONF_CHARGE_LIMIT_NUMBER)
        )
        charging_amps_state = self.hass.states.get(
            self.entry.data.get(CONF_CHARGING_AMPS_NUMBER)
        )
        charger_connected_state = self.hass.states.get(
            self.entry.data.get(CONF_CHARGER_CONNECTED_SENSOR)
        )
        scheduled_charging_state = self.hass.states.get(
            self._scheduled_charging_entity_id()
        )

        soc = _safe_float(_state_value(battery_state))
        charging = _state_on(charging_state)
        charger_switch_on = _state_on(charger_switch_state)
        charger_power_kw = _power_to_kw(charger_power_state)
        range_km = _range_to_km(range_state)
        time_charge_complete = _parse_datetime(_state_value(time_charge_state))
        charge_limit = _safe_float(_state_value(charge_limit_state))
        charging_amps = _safe_float(_state_value(charging_amps_state))
        charger_connected = _state_on(charger_connected_state)
        scheduled_charging_enabled = _state_on(scheduled_charging_state)

        return TeslaVehicleState(
            soc=soc,
            charging=charging,
            charger_switch_on=charger_switch_on,
            charger_power_kw=charger_power_kw,
            range_km=range_km,
            time_charge_complete=time_charge_complete,
            charge_limit=charge_limit,
            charging_amps=charging_amps,
            charger_connected=charger_connected,
            scheduled_charging_enabled=scheduled_charging_enabled,
        )

    def _scheduled_charging_entity_id(self) -> str | None:
        """Return scheduled charging binary sensor entity id."""

        return self.entry.data.get(CONF_SCHEDULED_CHARGING_SENSOR)

    async def _async_turn_on(self, entity_id: str) -> None:
        """Turn on a switch entity."""

        state = self.hass.states.get(entity_id)
        if state and state.state == STATE_ON:
            return

        await self.hass.services.async_call(
            "switch",
            "turn_on",
            {ATTR_ENTITY_ID: entity_id},
            blocking=False,
        )

    async def _async_turn_off(self, entity_id: str) -> None:
        """Turn off a switch entity."""

        state = self.hass.states.get(entity_id)
        if state and state.state == STATE_OFF:
            return

        await self.hass.services.async_call(
            "switch",
            "turn_off",
            {ATTR_ENTITY_ID: entity_id},
            blocking=False,
        )

    async def _async_set_charge_limit(
        self,
        use_bonus_target: bool = False,
        force_for_active_charge: bool = False,
        apply_configured_target: bool = True,
    ) -> None:
        """Set charge limit, with optional temporary bump while active charging is requested."""

        charge_limit_entity = self.entry.data.get(CONF_CHARGE_LIMIT_NUMBER)
        if not charge_limit_entity:
            return

        state = self.hass.states.get(charge_limit_entity)
        current = _safe_float(_state_value(state))

        if force_for_active_charge:
            self._hold_restored_charge_limit = False

        if (
            not force_for_active_charge
            and self._temporary_charge_limit_restore_soc is not None
        ):
            restore_soc = self._temporary_charge_limit_restore_soc
            if current is not None and abs(current - restore_soc) < 1:
                self._temporary_charge_limit_restore_soc = None
                self._hold_restored_charge_limit = True
                return

            await self.hass.services.async_call(
                "number",
                "set_value",
                {ATTR_ENTITY_ID: charge_limit_entity, "value": round(restore_soc)},
                blocking=False,
            )
            _LOGGER.debug(
                "Restoring original charge limit to %.1f%% after temporary bump.",
                restore_soc,
            )
            self._temporary_charge_limit_restore_soc = None
            self._hold_restored_charge_limit = True
            return

        if not force_for_active_charge and self._hold_restored_charge_limit:
            return

        if not apply_configured_target:
            return

        configured_target_soc = (
            self._bonus_target_soc() if use_bonus_target else self.inputs.target_soc
        )
        if configured_target_soc is None:
            return

        target_soc = configured_target_soc
        if force_for_active_charge:
            soc = self._read_vehicle_state().soc
            if (
                soc is not None
                and configured_target_soc is not None
                and configured_target_soc <= soc
                and (current is None or current <= soc)
            ):
                if self._temporary_charge_limit_restore_soc is None and current is not None:
                    self._temporary_charge_limit_restore_soc = current
                bumped_target = min(
                    100.0,
                    max(configured_target_soc, soc + _FORCE_CHARGE_LIMIT_MARGIN_SOC),
                )
                if bumped_target > configured_target_soc:
                    _LOGGER.debug(
                        (
                            "Temporarily increasing charge limit from %.1f%% to %.1f%% "
                            "to allow charging (SOC=%.1f%%)."
                        ),
                        configured_target_soc,
                        bumped_target,
                        soc,
                    )
                    target_soc = bumped_target

        if current is not None and abs(current - target_soc) < 1:
            return

        await self.hass.services.async_call(
            "number",
            "set_value",
            {ATTR_ENTITY_ID: charge_limit_entity, "value": round(target_soc)},
            blocking=False,
        )

    def _notify_input_entities(self) -> None:
        """Update input entity state in HA."""

        for entity in self._input_entities.values():
            if entity.hass:
                entity.async_write_ha_state()


def _safe_float(value: Any) -> float | None:
    """Return float for value or None."""

    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _state_value(state: Any) -> str | None:
    """Return raw state value."""

    if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    return state.state


def _state_on(state: Any) -> bool | None:
    """Return True if state is on, False if off, None if unknown."""

    if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None
    return state.state == STATE_ON


def _power_to_kw(state: Any) -> float | None:
    """Parse charger power to kW."""

    if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None

    value = _safe_float(state.state)
    if value is None:
        return None

    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "").lower()
    if unit in {"w", "watt", "watts"}:
        return value / 1000.0

    return value


def _range_to_km(state: Any) -> float | None:
    """Parse range to kilometers."""

    if not state or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
        return None

    value = _safe_float(state.state)
    if value is None:
        return None

    unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT, "").lower()
    if unit in {"mi", "mile", "miles"}:
        return value * _KM_PER_MI

    return value


def _parse_datetime(value: Any) -> datetime | None:
    """Parse a value into a timezone-aware datetime."""

    if value is None:
        return None

    if isinstance(value, datetime):
        return dt_util.as_local(value)

    if isinstance(value, (int, float)):
        return dt_util.as_local(datetime.fromtimestamp(value, tz=dt_util.UTC))

    if isinstance(value, str):
        parsed = dt_util.parse_datetime(value)
        if parsed:
            return dt_util.as_local(parsed)

    return None


def _round(value: float, digits: int) -> float:
    """Round a float safely."""

    return round(value, digits)


def _build_slots_from_prices(prices: list[float]) -> list[TariffSlot]:
    """Build tariff slots from a list of prices starting now."""

    start = _align_to_next_quarter(dt_util.now())
    slots = []
    for index, price in enumerate(prices):
        slot_start = start + timedelta(minutes=15 * index)
        slot_end = slot_start + timedelta(minutes=15)
        slots.append(TariffSlot(start=slot_start, end=slot_end, price=float(price)))
    return slots


def _extract_price(item: dict[str, Any]) -> Any:
    """Return the most relevant price value from a tariff entry."""

    for key in (
        "price_ttc_eur_kwh",
        "price_ht_eur_kwh",
        "price_eur_per_kwh",
        "price_eur_kwh",
        "price",
        "value",
        "tariff",
        "spot_price_eur_kwh",
    ):
        if key in item:
            return item.get(key)
    return None


def _align_to_next_quarter(now: datetime) -> datetime:
    """Align a datetime to the next 15-minute boundary."""

    minute = (now.minute // 15) * 15
    aligned = now.replace(minute=minute, second=0, microsecond=0)
    if aligned < now:
        aligned += timedelta(minutes=15)
    return aligned


def _normalize_sobry_prices(data: Any) -> list[dict[str, Any]]:
    """Normalize Sobry API payload for tariff slot parsing."""

    if isinstance(data, dict):
        if isinstance(data.get("data"), list):
            data = data.get("data")
        elif isinstance(data.get("prices"), list):
            data = data.get("prices")
    if not isinstance(data, list):
        return []

    normalized: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue

        timestamp = item.get("timestamp") or item.get("start") or item.get("date")
        start = _parse_datetime(timestamp)
        if start is None and isinstance(timestamp, str):
            try:
                start = dt_util.as_local(datetime.fromisoformat(timestamp.replace("Z", "+00:00")))
            except ValueError:
                start = None
        if start is None:
            continue

        price = _safe_float(item.get("price_ttc_eur_kwh"))
        if price is None:
            price = _safe_float(item.get("price_ht_eur_kwh"))
        if price is None:
            price = _safe_float(item.get("price_eur_per_kwh"))
        if price is None:
            price = _safe_float(item.get("spot_price_eur_kwh"))
        if price is None:
            spot_price_mwh = _safe_float(item.get("spot_price"))
            if spot_price_mwh is None:
                continue
            price = spot_price_mwh / 1000.0

        normalized.append({"start": start, "price_eur_per_kwh": price})

    return normalized


def _resolve_json_path(data: Any, path: str) -> Any:
    """Resolve a dot-delimited JSON path."""

    current = data
    for part in path.split("."):
        if isinstance(current, dict) and part in current:
            current = current[part]
        elif isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return None
        else:
            return None
    return current
