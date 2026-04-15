
# ⚡ Tesla Smart Charge

[English](README.md) | [Français](README.fr.md)

[](https://github.com/hacs/integration)
[](https://opensource.org/licenses/MIT)
[](https://www.home-assistant.io/)

**Optimize your Tesla charging based on dynamic electricity tariffs.** This Home Assistant integration automatically schedules charging sessions during the cheapest windows while ensuring your car is ready exactly when you need it.

-----

## ✨ Key Features

  * **Dual-Stage Optimization:**
    1.  **Readiness Priority:** Reaches your `Min. SOC at Ready Time` by your `Departure Time`.
    2.  **Bonus "Cheap" Charging:** Continues to `Target SOC (Low Rate)` only during ultra-low price windows, regardless of time.
  * **Flexible Tariff Sources:** Supports Sensor Attributes, REST Endpoints (JSON), and Raw Spot prices (CU4 Particulier TTC).
  * **Market sensors for dashboards/tickers:** Exposes the current spot price, change vs the previous slot, short-term trend, next significant low, and current relative price level.
  * **Smart Automation:** Automatically bumps the Tesla charge limit by $+1\%$ if needed to wake the car and trigger a session.
  * **Plug & Play Dashboard:** Built-in service to generate a dedicated Lovelace view with `ApexCharts` integration.

-----

## 🛠 Prerequisites

1.  **Tesla Integration:** An active Tesla integration (Official or Custom) providing SOC, Amps, Charger Switch, and Plug Status.
2.  **Tariff Data:** A sensor or API providing upcoming price data.
3.  **Frontend (Optional):** Install `ApexCharts Card` and `HTML Template Card` via HACS (`Frontend`) for the best visual experience and support for `custom:html-template-card`.

-----

## 🚀 Installation

### Option 1: HACS (Recommended)

1.  Open **HACS** \> **Integrations**.
2.  Click the 3 dots (top right) \> **Custom repositories**.
3.  Paste this Repo URL and select **Integration** as the category.
4.  Click **Install** and **Restart** Home Assistant.

### Option 2: Manual

1.  Copy the `tesla_smart_charge` folder to your `/config/custom_components/` directory.
2.  **Restart** Home Assistant.

-----

## ⚙️ Configuration

1.  Navigate to **Settings** \> **Devices & Services** \> **Add Integration**.
2.  Search for **Tesla Smart Charge**.
3.  **Entity Mapping:** Map your Tesla's sensors (SOC, Charge Limit, Amps, etc.).
4.  **Constants:** Define battery capacity (kWh), vehicle efficiency (Wh/km), and max power (kW).

-----

## 📊 Core Entities

| Icon | Entity Type | Name | Purpose |
| :--- | :--- | :--- | :--- |
| 🔢 | **Number** | `Min. SOC at Ready Time` | Target battery level for departure. |
| 🕒 | **Number** | `Departure Time` | Deadline for the minimum SOC target. |
| 💰 | **Number** | `Price Limit Threshold` | Price ceiling for "Bonus" charging. |
| ⚡ | **Switch** | `Enable Smart Charging` | Master toggle for the optimizer. |
| 🛰️ | **Binary Sensor** | `Smart Charging Status` | Green if plug is in & Tesla scheduler is off. |

-----

## 📈 Market Sensors

These sensors are designed for a compact market-style display, so you can render a meaningful ticker instead of only showing raw tariff arrays.

| Name | Type | Primary Value | Useful Attributes |
| :--- | :--- | :--- | :--- |
| `Current Spot Price` | Sensor | Current spot price in `EUR/kWh` | `start`, `end`, `source` |
| `Price Change vs Previous Slot` | Sensor | Absolute delta vs the previous slot | `delta_percent`, `direction`, `current_price`, `previous_price` |
| `Short-Term Price Trend` | Sensor | `up`, `down`, or `stable` | `current_price`, `delta_vs_previous`, `price_level` |
| `Next Significant Low` | Timestamp Sensor | Start of the next practical low window | `end`, `price`, `duration_minutes` |
| `Current Price Level` | Sensor | `very_low`, `low`, `normal`, `high`, `very_high` | `percentile`, `status`, `current_price` |

Example compact output:

```text
SPOT 0.164 EUR/kWh  DELTA -0.012  TREND down  NEXT LOW 11:30  STATUS cheap
```

-----

## 🛠 Services

| Service | Description |
| :--- | :--- |
| `reoptimize` | Manually triggers a recalculation of the charging schedule. |
| `apply_control` | Forces the current state (Start/Stop) to the vehicle. |
| `install_dashboard_template` | Generates a YAML dashboard file in your config. |

**Example Dashboard Installation:**

```yaml
service: tesla_smart_charge.install_dashboard_template
data:
  filename: dashboards/tesla_smart_charge.yaml
  # existing_dashboard_filename: ui-lovelace.yaml (Optional)
```

-----

## 💡 Technical Notes

> [\!IMPORTANT]
> **Controllability:** The `Smart Charging Status` sensor must be `True` for the integration to work. This requires the car to be **plugged in** and the **internal Tesla scheduled charging to be disabled** (to avoid conflicts).

  * **Spot Prices:** Tomorrow's prices are fetched after `13:10` local time. The optimizer looks ahead up to 48 hours to find the best slots.
  * **Delta vs previous slot:** The analytics keep the previous-slot context so the ticker can expose a meaningful live market delta.
  * **Short-term trend:** The trend is computed across several slots to avoid overreacting to a single 15-minute move.
  * **Next significant low:** This is not just the absolute minimum; the algorithm first looks for a practical local trough, then expands the contiguous low-price window.
  * **Relative level:** The `very_low` to `very_high` status is derived from a percentile computed on the day of the current slot.
  * **Efficiency:** Calculations use your defined `Wh/km` and battery `kWh` to estimate the duration needed to reach targets.
  * **JSON Format:** The integration expects a list of objects with timestamps (`start`, `end`) and a `price` key.

-----

## 🤝 Contributing

Feedback and Pull Requests are welcome\! Feel free to open an issue for bug reports or feature requests.
