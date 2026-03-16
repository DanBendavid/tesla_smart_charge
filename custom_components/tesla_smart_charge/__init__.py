"""Tesla Smart Charge integration."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import voluptuous as vol
import yaml

import homeassistant.helpers.config_validation as cv
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.exceptions import ConfigEntryNotReady

from .const import (
    ATTR_FILENAME,
    ATTR_EXISTING_DASHBOARD_FILENAME,
    ATTR_ENTRY_ID,
    CONF_ADD_TO_EXISTING_DASHBOARD,
    CONF_EXISTING_DASHBOARD_FILENAME,
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
_SMART_CHARGE_VIEW_TITLE = "Smart Charge"
_SMART_CHARGE_VIEW_PATH = "smart-charge"
_LEGACY_SMART_CHARGE_VIEW_TITLE = "Tesla Smart Charge"
_LEGACY_SMART_CHARGE_VIEW_PATH = "tesla-smart-charge"
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
                    vol.Optional(ATTR_EXISTING_DASHBOARD_FILENAME): str,
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
        add_to_existing = bool(entry.data.get(CONF_ADD_TO_EXISTING_DASHBOARD))
        existing_dashboard_filename = str(
            entry.data.get(CONF_EXISTING_DASHBOARD_FILENAME, "")
        ).strip()
        if add_to_existing or existing_dashboard_filename:
            existing_dashboard_filename = existing_dashboard_filename or "ui-lovelace.yaml"
            installed = await _async_add_template_view_to_existing_dashboard(
                hass, existing_dashboard_filename
            )
        else:
            installed = await _async_install_dashboard_template(
                hass, _DEFAULT_DASHBOARD_FILENAME
            )
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
    existing_dashboard_filename = str(
        call.data.get(ATTR_EXISTING_DASHBOARD_FILENAME, "")
    ).strip()
    if existing_dashboard_filename:
        await _async_add_template_view_to_existing_dashboard(
            hass, existing_dashboard_filename
        )
        return

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


async def _async_add_template_view_to_existing_dashboard(
    hass: HomeAssistant, filename: str
) -> bool:
    """Merge Tesla Smart Charge view into an existing Lovelace YAML dashboard."""

    filename = filename.replace("\\", "/").strip()
    if not filename:
        _LOGGER.error("Existing dashboard filename is empty")
        return False

    if not _DASHBOARD_TEMPLATE_PATH.exists():
        _LOGGER.error("Dashboard template not found: %s", _DASHBOARD_TEMPLATE_PATH)
        return False

    target_path = Path(hass.config.path(filename))

    def _merge_template_view() -> int:
        if not target_path.exists():
            raise FileNotFoundError(filename)

        template_content = _DASHBOARD_TEMPLATE_PATH.read_text(encoding="utf-8")
        existing_content = target_path.read_text(encoding="utf-8")

        template_dashboard = yaml.safe_load(template_content) or {}
        existing_dashboard = yaml.safe_load(existing_content) or {}

        if not isinstance(template_dashboard, dict):
            raise ValueError("Template dashboard is not a YAML mapping")
        if not isinstance(existing_dashboard, dict):
            raise ValueError("Existing dashboard is not a YAML mapping")

        template_views = template_dashboard.get("views")
        if not isinstance(template_views, list) or not template_views:
            raise ValueError("Template dashboard has no views to merge")

        existing_views = existing_dashboard.get("views")
        if existing_views is None:
            existing_views = []
            existing_dashboard["views"] = existing_views
        if not isinstance(existing_views, list):
            raise ValueError("Existing dashboard 'views' is not a list")

        existing_paths = {
            str(view.get("path")).strip()
            for view in existing_views
            if isinstance(view, dict) and view.get("path")
        }
        existing_titles = {
            str(view.get("title")).strip()
            for view in existing_views
            if isinstance(view, dict) and view.get("title")
        }

        views_added = 0
        for view in template_views:
            if not isinstance(view, dict):
                continue

            view_path = str(view.get("path")).strip() if view.get("path") else ""
            view_title = str(view.get("title")).strip() if view.get("title") else ""
            is_smart_charge_view = (
                view_path == _SMART_CHARGE_VIEW_PATH
                or view_title == _SMART_CHARGE_VIEW_TITLE
            )
            if is_smart_charge_view and (
                _SMART_CHARGE_VIEW_PATH in existing_paths
                or _LEGACY_SMART_CHARGE_VIEW_PATH in existing_paths
                or _SMART_CHARGE_VIEW_TITLE in existing_titles
                or _LEGACY_SMART_CHARGE_VIEW_TITLE in existing_titles
            ):
                continue
            if (view_path and view_path in existing_paths) or (
                view_title and view_title in existing_titles
            ):
                continue

            existing_views.append(view)
            if view_path:
                existing_paths.add(view_path)
            if view_title:
                existing_titles.add(view_title)
            views_added += 1

        if views_added:
            merged_content = yaml.safe_dump(
                existing_dashboard, sort_keys=False, allow_unicode=True
            )
            target_path.write_text(merged_content, encoding="utf-8")

        return views_added

    try:
        views_added = await hass.async_add_executor_job(_merge_template_view)
    except FileNotFoundError:
        _LOGGER.error("Existing dashboard file not found: %s", target_path)
        return False
    except yaml.YAMLError as err:
        _LOGGER.error(
            "Existing dashboard file is not valid YAML (%s): %s", target_path, err
        )
        return False
    except ValueError as err:
        _LOGGER.error(
            "Unable to merge dashboard template into %s: %s", target_path, err
        )
        return False
    except Exception as err:
        _LOGGER.error("Unexpected error while merging dashboard %s: %s", target_path, err)
        return False

    if views_added:
        message = (
            f"Added {views_added} Smart Charge view(s) to `{filename}`.\n\n"
            "Reload YAML configuration or restart Home Assistant to apply changes."
        )
        title = "Smart Charge view added to existing dashboard"
    else:
        message = (
            f"No change in `{filename}` because the Smart Charge view is already present."
        )
        title = "Smart Charge dashboard view already present"

    _LOGGER.warning(message)
    try:
        await hass.services.async_call(
            "persistent_notification",
            "create",
            {"title": title, "message": message},
            blocking=False,
        )
    except Exception:  # pragma: no cover - optional notification service
        _LOGGER.debug("Unable to create persistent notification for dashboard merge")

    return True


def _get_coordinators(hass: HomeAssistant, entry_id: str | None) -> list[TeslaSmartChargeCoordinator]:
    """Return coordinators based on an optional entry id."""

    if entry_id:
        coordinator = hass.data.get(DOMAIN, {}).get(entry_id)
        return [coordinator] if coordinator else []
    return list(hass.data.get(DOMAIN, {}).values())
