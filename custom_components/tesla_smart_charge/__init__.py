"""Tesla Smart Charge integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    ATTR_FILENAME,
    ATTR_ENTRY_ID,
    CONF_INSTALL_DASHBOARD_ON_SETUP,
    DOMAIN,
    PLATFORMS,
    SERVICE_APPLY_CONTROL,
    SERVICE_INSTALL_DASHBOARD_TEMPLATE,
    SERVICE_REOPTIMIZE,
)
from .coordinator import TeslaSmartChargeCoordinator

_LOGGER = logging.getLogger(__name__)
_DEFAULT_DASHBOARD_FILENAME = "dashboards/tesla_smart_charge.yaml"
_DASHBOARD_TEMPLATE_PATH = Path(__file__).parent / "dashboards" / "tesla_smart_charge.yaml"
CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Set up the Tesla Smart Charge integration."""

    hass.data.setdefault(DOMAIN, {})

    if not hass.services.has_service(DOMAIN, SERVICE_REOPTIMIZE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_REOPTIMIZE,
            _handle_reoptimize,
            schema=vol.Schema({vol.Optional(ATTR_ENTRY_ID): str}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_APPLY_CONTROL):
        hass.services.async_register(
            DOMAIN,
            SERVICE_APPLY_CONTROL,
            _handle_apply_control,
            schema=vol.Schema({vol.Optional(ATTR_ENTRY_ID): str}),
        )

    if not hass.services.has_service(DOMAIN, SERVICE_INSTALL_DASHBOARD_TEMPLATE):
        hass.services.async_register(
            DOMAIN,
            SERVICE_INSTALL_DASHBOARD_TEMPLATE,
            _handle_install_dashboard_template,
            schema=vol.Schema(
                {
                    vol.Optional(ATTR_FILENAME, default=_DEFAULT_DASHBOARD_FILENAME): str,
                }
            ),
        )

    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Tesla Smart Charge from a config entry."""

    coordinator = TeslaSmartChargeCoordinator(hass, entry)

    try:
        await coordinator.async_config_entry_first_refresh()
    except Exception as err:
        raise ConfigEntryNotReady from err

    hass.data[DOMAIN][entry.entry_id] = coordinator

    unsubscribers = coordinator.async_setup_listeners()
    for unsub in unsubscribers:
        entry.async_on_unload(unsub)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    if entry.data.get(CONF_INSTALL_DASHBOARD_ON_SETUP):
        installed = await _async_install_dashboard_template(hass, _DEFAULT_DASHBOARD_FILENAME)
        if installed:
            new_data = dict(entry.data)
            new_data[CONF_INSTALL_DASHBOARD_ON_SETUP] = False
            hass.config_entries.async_update_entry(entry, data=new_data)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _handle_reoptimize(call) -> None:
    """Handle reoptimize service calls."""

    hass: HomeAssistant = call.hass
    entry_id = call.data.get(ATTR_ENTRY_ID)
    coordinators = _get_coordinators(hass, entry_id)

    await asyncio.gather(*(coord.async_request_refresh() for coord in coordinators))


async def _handle_apply_control(call) -> None:
    """Handle apply control service calls."""

    hass: HomeAssistant = call.hass
    entry_id = call.data.get(ATTR_ENTRY_ID)
    coordinators = _get_coordinators(hass, entry_id)

    await asyncio.gather(*(coord.async_apply_control() for coord in coordinators))


async def _handle_install_dashboard_template(call: ServiceCall) -> None:
    """Install the packaged Lovelace dashboard template into /config."""

    hass: HomeAssistant = call.hass
    filename = str(call.data.get(ATTR_FILENAME, _DEFAULT_DASHBOARD_FILENAME)).strip()
    await _async_install_dashboard_template(hass, filename)


async def _async_install_dashboard_template(hass: HomeAssistant, filename: str) -> bool:
    """Install the packaged Lovelace dashboard template into /config."""

    if not filename:
        filename = _DEFAULT_DASHBOARD_FILENAME
    filename = filename.replace("\\", "/")

    if not _DASHBOARD_TEMPLATE_PATH.exists():
        _LOGGER.error("Dashboard template not found: %s", _DASHBOARD_TEMPLATE_PATH)
        return False

    target_path = Path(hass.config.path(filename))

    def _copy_template() -> None:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        content = _DASHBOARD_TEMPLATE_PATH.read_text(encoding="utf-8")
        target_path.write_text(content, encoding="utf-8")

    await hass.async_add_executor_job(_copy_template)

    message = (
        f"Dashboard template installed at `{filename}`.\n\n"
        "Add this in `configuration.yaml`:\n"
        "```yaml\n"
        "lovelace:\n"
        "  dashboards:\n"
        "    tesla-smart-charge:\n"
        "      mode: yaml\n"
        "      title: Tesla Smart Charge\n"
        "      icon: mdi:ev-station\n"
        "      show_in_sidebar: true\n"
        f"      filename: {filename}\n"
        "```\n"
        "Then reload YAML configuration or restart Home Assistant."
    )

    _LOGGER.warning(message)
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {
                "title": "Tesla Smart Charge dashboard template installed",
                "message": message,
            },
            blocking=False,
        )
    except Exception:  # pragma: no cover - optional notification service
        _LOGGER.debug("Unable to create persistent notification for dashboard template")

    return True


def _get_coordinators(hass: HomeAssistant, entry_id: str | None) -> list[TeslaSmartChargeCoordinator]:
    """Return coordinators based on an optional entry id."""

    if entry_id:
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        return [coordinator] if coordinator else []
    return list(hass.data.get(DOMAIN, {}).values())
