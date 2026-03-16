# Tesla Smart Charge

Custom integration Home Assistant to optimize Tesla charging from tariff slots.

## About

Tesla Smart Charge is a Home Assistant custom integration that schedules Tesla charging on the cheapest tariff periods while honoring your readiness target (`Minimum SOC By Ready Time` + `Ready By Hour`).  
It also supports optional low-price bonus charging (`SOC If Cheap`) and provides dashboard-friendly sensors/services for monitoring and control.

## Features

- Automatic optimization of charging slots based on price.
- Two-stage strategy: `Minimum SOC By Ready Time` before `Ready By Hour`, then `SOC If Cheap` bonus slots on cheap prices without ready-hour limit.
- Multiple tariff sources: sensor attribute (`prices` by default), REST endpoint (JSON), and spot raw source (CU4 Particulier TTC, sliding 24h).
- Inputs exposed as entities (`number`, `switch`, `select`) for easy dashboard control.
- Built-in service to install a Lovelace dashboard template.

## Prerequisites

- Home Assistant with the Tesla entities you want to control/map (SOC sensor, charging status, charger switch, charging power, charge limit, amps, etc.).
- A tariff source that exposes upcoming prices (`Sensor Attribute`, `REST Endpoint`, or `Spot Raw` in this integration).
- For dashboard templates using `custom:apexcharts-card`: install `ApexCharts Card` from HACS (`Frontend` category).

## Installation

### HACS (Custom repository)

1. Push this integration to a public GitHub repository.
2. In Home Assistant, open HACS.
3. Open the menu (3 dots) -> `Custom repositories`.
4. Add your repository URL with category `Integration`.
5. Install `Tesla Smart Charge` from HACS.
6. Restart Home Assistant.

### Manual

1. Copy this folder to:
`/config/custom_components/tesla_smart_charge`
2. Restart Home Assistant.

## Configuration

1. Go to `Settings` -> `Devices & Services` -> `Add Integration`.
2. Add `Tesla Smart Charge`.
3. Map Tesla-related entities: battery SOC sensor, charging binary sensor, charger switch, charger power sensor, charge limit number, charging amps number, range sensor, time charge complete sensor, `charger_connected_sensor` (plug connected), and `scheduled_charging_sensor` (Tesla scheduled charging).
4. Choose a tariff source: `Sensor Attribute`, `REST Endpoint`, or `Spot Raw`.
5. Set constants: battery capacity (kWh), vehicle efficiency (Wh/km), and max charging power (kW).

## Main entities

### Numbers

- `Minimum SOC By Ready Time`
- `Ready By Hour`
- `SOC If Cheap`
- `Cheap Price Threshold` (`0.0` to `0.2`)

### Switches

- `Smart Charging Enabled`
- `Allow Immediate Charge`

### Binary sensors

- `Module Charge Controllable` (true when plug is connected and Tesla scheduled charging is disabled)

### Sensors

- `Remaining Energy Needed`
- `Estimated Distance After Charge`
- `Tariff Prices 15min`
- `Cheapest Next Slot`
- `Optimized Start Time`
- `Optimized End Time`
- `Optimized Cost`
- `Optimized Energy`
- `Optimized Schedule` (with `schedule` attribute)

## Services

- `tesla_smart_charge.reoptimize`
- `tesla_smart_charge.apply_control`
- `tesla_smart_charge.install_dashboard_template`

Example to install dashboard template:

```yaml
service: tesla_smart_charge.install_dashboard_template
data:
  filename: dashboards/tesla_smart_charge.yaml
```

## Tariff formats

Accepted tariff payloads include:

- A list of objects with timestamps and prices.
- Common timestamp keys: `start`, `timestamp`, `time`, `from`, `date`
- Common end keys: `end`, `to`
- Common price keys: `price`, `value`, `price_eur_kwh`, `price_eur_per_kwh`, `price_ttc_eur_kwh`

Minimal example:

```json
[
  {"start":"2026-03-15T10:00:00+01:00","end":"2026-03-15T10:15:00+01:00","price":0.129},
  {"start":"2026-03-15T10:15:00+01:00","end":"2026-03-15T10:30:00+01:00","price":0.136}
]
```

## Notes

- If current SOC is already above `Minimum SOC By Ready Time`, required energy can be `0`.
- Bonus slots are only used when `SOC If Cheap` is above current/required SOC and `Cheap Price Threshold` matches available future prices.
- If active charging is requested (slot or immediate mode) and charge limit is at/below current SOC, the integration temporarily bumps charge limit to `SOC + 1%` so charging can start, then restores the original value when active demand ends.
- `Module Charge Controllable` depends on both required mappings: `charger_connected_sensor` and `scheduled_charging_sensor`.
