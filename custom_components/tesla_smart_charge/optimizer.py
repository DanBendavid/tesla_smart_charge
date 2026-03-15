"""Optimizer for Tesla Smart Charge.

Example tariff JSON (15-minute slots):
[
  {"start": "2026-01-21T00:00:00+01:00", "end": "2026-01-21T00:15:00+01:00", "price": 0.12},
  {"start": "2026-01-21T00:15:00+01:00", "end": "2026-01-21T00:30:00+01:00", "price": 0.10},
  {"start": "2026-01-21T00:30:00+01:00", "end": "2026-01-21T00:45:00+01:00", "price": 0.15}
]
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Iterable, Sequence

from homeassistant.util import dt as dt_util

from .const import (
    PLANNING_HORIZON_TOMORROW,
    PLANNING_HORIZON_TONIGHT,
    PLANNING_HORIZON_WEEK,
)


@dataclass(frozen=True)
class TariffSlot:
    """Represents a single tariff slot."""

    start: datetime
    end: datetime
    price: float

    @property
    def duration_hours(self) -> float:
        """Return the slot duration in hours."""

        return max(0.0, (self.end - self.start).total_seconds() / 3600.0)


@dataclass
class OptimizerResult:
    """Optimizer output for a given tariff schedule."""

    schedule: list[dict]
    enabled_slots: list[TariffSlot]
    start: datetime | None
    end: datetime | None
    total_cost: float
    total_energy_kwh: float


def filter_slots_for_horizon(
    slots: Sequence[TariffSlot],
    planning_horizon: str,
    now: datetime | None = None,
) -> list[TariffSlot]:
    """Filter slots based on the planning horizon."""

    if not slots:
        return []

    local_now = dt_util.as_local(now) if now else dt_util.now()

    if planning_horizon == PLANNING_HORIZON_TOMORROW:
        start = (local_now + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        end = start + timedelta(days=1)
    elif planning_horizon == PLANNING_HORIZON_WEEK:
        start = local_now
        end = start + timedelta(days=7)
    else:
        start = local_now
        end = local_now.replace(hour=23, minute=59, second=59, microsecond=0)

    filtered: list[TariffSlot] = []
    for slot in slots:
        if slot.end <= start or slot.start >= end:
            continue
        filtered.append(slot)

    return filtered


def optimize_schedule(
    required_energy_kwh: float,
    charging_power_kw: float,
    slots: Sequence[TariffSlot],
    max_cost: float | None,
    planning_horizon: str,
    now: datetime | None = None,
) -> OptimizerResult:
    """Select the cheapest slots to satisfy energy and cost constraints."""

    if required_energy_kwh <= 0 or charging_power_kw <= 0 or not slots:
        return OptimizerResult([], [], None, None, 0.0, 0.0)

    filtered_slots = filter_slots_for_horizon(slots, planning_horizon, now)
    if not filtered_slots:
        return OptimizerResult([], [], None, None, 0.0, 0.0)

    enabled_slots, total_energy, total_cost = _select_slots(
        filtered_slots,
        required_energy_kwh,
        charging_power_kw,
        max_cost,
    )

    enabled_set = set(enabled_slots)
    schedule: list[dict] = []
    for slot in sorted(filtered_slots, key=lambda item: item.start):
        schedule.append(
            {
                "start": dt_util.as_local(slot.start).isoformat(),
                "end": dt_util.as_local(slot.end).isoformat(),
                "price": slot.price,
                "enabled": slot in enabled_set,
            }
        )

    start = min((slot.start for slot in enabled_slots), default=None)
    end = max((slot.end for slot in enabled_slots), default=None)

    return OptimizerResult(schedule, enabled_slots, start, end, total_cost, total_energy)


def estimate_cost_for_energy(
    required_energy_kwh: float,
    charging_power_kw: float,
    slots: Sequence[TariffSlot],
    planning_horizon: str,
    now: datetime | None = None,
) -> float:
    """Estimate cost for a required energy amount using cheapest slots."""

    if required_energy_kwh <= 0 or charging_power_kw <= 0 or not slots:
        return 0.0

    filtered_slots = filter_slots_for_horizon(slots, planning_horizon, now)
    if not filtered_slots:
        return 0.0

    _, _, total_cost = _select_slots(
        filtered_slots,
        required_energy_kwh,
        charging_power_kw,
        max_cost=None,
    )
    return total_cost


def estimate_energy_for_cost(
    max_cost: float,
    charging_power_kw: float,
    slots: Sequence[TariffSlot],
    planning_horizon: str,
    now: datetime | None = None,
) -> float:
    """Estimate deliverable energy within a max cost budget."""

    if max_cost <= 0 or charging_power_kw <= 0 or not slots:
        return 0.0

    filtered_slots = filter_slots_for_horizon(slots, planning_horizon, now)
    if not filtered_slots:
        return 0.0

    _, total_energy, _ = _select_slots(
        filtered_slots,
        None,
        charging_power_kw,
        max_cost=max_cost,
    )
    return total_energy


def _select_slots(
    slots: Sequence[TariffSlot],
    energy_needed_kwh: float | None,
    charging_power_kw: float,
    max_cost: float | None,
) -> tuple[list[TariffSlot], float, float]:
    """Pick the cheapest slots until energy or cost limits are reached."""

    sorted_slots = sorted(slots, key=lambda item: item.price)
    enabled: list[TariffSlot] = []
    total_energy = 0.0
    total_cost = 0.0
    remaining = energy_needed_kwh

    for slot in sorted_slots:
        if remaining is not None and remaining <= 0:
            break

        slot_energy = charging_power_kw * slot.duration_hours
        if slot_energy <= 0:
            continue

        slot_cost = slot_energy * slot.price
        if max_cost is not None and total_cost + slot_cost > max_cost:
            continue

        enabled.append(slot)
        total_energy += slot_energy
        total_cost += slot_cost
        if remaining is not None:
            remaining -= slot_energy

    return enabled, total_energy, total_cost
