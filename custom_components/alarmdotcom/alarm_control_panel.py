"""Interfaces with Alarm.com alarm control panels."""

from __future__ import annotations

import logging  # Add this import
import re
from collections.abc import Mapping
from typing import Any

from homeassistant import core
from homeassistant.components.alarm_control_panel import (
    AlarmControlPanelEntity,
    AlarmControlPanelState,
    AlarmControlPanelEntityFeature,
    CodeFormat,
)
from homeassistant.components.alarm_control_panel.const import AlarmControlPanelState
from homeassistant.config_entries import ConfigEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback, DiscoveryInfoType
from pyalarmdotcomajax.devices.partition import Partition as libPartition
from pyalarmdotcomajax.exceptions import NotAuthorized

from .base_device import HardwareBaseDevice
from .const import (
    CONF_ARM_AWAY,
    CONF_ARM_CODE,
    CONF_ARM_HOME,
    CONF_ARM_NIGHT,
    CONF_FORCE_BYPASS,
    CONF_NO_ENTRY_DELAY,
    CONF_SILENT_ARM,
    DATA_CONTROLLER,
    DOMAIN,
)
from .controller import AlarmIntegrationController

LOGGER = logging.getLogger(__name__)  # This will now work

async def async_setup_entry(
    hass: core.HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
    discovery_info: DiscoveryInfoType | None = None,  # pylint: disable=unused-argument
) -> None:
    """Set up the sensor platform and create a master device."""

    controller: AlarmIntegrationController = hass.data[DOMAIN][config_entry.entry_id][DATA_CONTROLLER]

    async_add_entities(
        AlarmControlPanel(
            controller=controller,
            device=device,
        )
        for device in controller.api.devices.partitions.values()
    )


class AlarmControlPanel(HardwareBaseDevice, AlarmControlPanelEntity):  # type: ignore
    """Alarm.com Alarm Control Panel entity."""

    device_type_name: str = "Alarm Control Panel"
    _device: libPartition

    def __init__(
        self,
        controller: AlarmIntegrationController,
        device: libPartition,
    ) -> None:
        """Pass coordinator to CoordinatorEntity."""

        super().__init__(controller, device)

        self._attr_code_format = (
            (
                CodeFormat.NUMBER
                if (isinstance(arm_code, str) and re.search(r"^\d+$", arm_code))
                else CodeFormat.TEXT
            )
            if (arm_code := controller.options.get(CONF_ARM_CODE))
            else None
        )

        self._attr_supported_features = (
            AlarmControlPanelEntityFeature.ARM_HOME | AlarmControlPanelEntityFeature.ARM_AWAY
        )

        if self._device.supports_night_arming:
            self._attr_supported_features |= AlarmControlPanelEntityFeature.ARM_NIGHT

    @property
    def extra_state_attributes(self) -> Mapping[str, Any] | None:
        """Return the state attributes of the entity."""

        return {
            "uncleared_issues": str(self._device.uncleared_issues),
            **getattr(super(), "extra_state_attributes", {}),
        }

    @property
    def alarm_state(self) -> AlarmControlPanelState:
        """Return the current state of the alarm using AlarmControlPanelState enum."""
        if self._device.malfunction:
            return AlarmControlPanelState.UNKNOWN
        
        if self._device.state == self._device.desired_state:
            match self._device.state:
                case libPartition.DeviceState.DISARMED:
                    return AlarmControlPanelState.DISARMED
                case libPartition.DeviceState.ARMED_STAY:
                    return AlarmControlPanelState.ARMED_HOME
                case libPartition.DeviceState.ARMED_AWAY:
                    return AlarmControlPanelState.ARMED_AWAY
                case libPartition.DeviceState.ARMED_NIGHT:
                    return AlarmControlPanelState.ARMED_NIGHT
        else:
            match self._device.desired_state:
                case libPartition.DeviceState.DISARMED:
                    return AlarmControlPanelState.DISARMING
                case (
                    libPartition.DeviceState.ARMED_STAY
                    | libPartition.DeviceState.ARMED_AWAY
                    | libPartition.DeviceState.ARMED_NIGHT
                ):
                    return AlarmControlPanelState.ARMING
        
        LOGGER.error(
            f"Cannot determine state. Found raw state of {self._device.state} and desired state of"
            f" {self._device.desired_state}."
        )
        return AlarmControlPanelState.UNKNOWN

    async def async_alarm_disarm(self, code: str | None = None) -> None:
        """Send disarm command."""
        if self._validate_code(code):
            try:
                await self._device.async_disarm()
            except NotAuthorized:
                self._show_permission_error("disarm")

    async def async_alarm_arm_night(self, code: str | None = None) -> None:
        """Send arm night command."""

        arm_options = self._controller.options.get(CONF_ARM_NIGHT, {})

        if self._validate_code(code):
            try:
                await self._device.async_arm_night(
                    force_bypass=CONF_FORCE_BYPASS in arm_options,
                    no_entry_delay=CONF_NO_ENTRY_DELAY in arm_options,
                    silent_arming=CONF_SILENT_ARM in arm_options,
                )
            except NotAuthorized:
                self._show_permission_error("arm_night")

    async def async_alarm_arm_home(self, code: str | None = None) -> None:
        """Send arm home command."""

        arm_options = self._controller.options.get(CONF_ARM_HOME, {})

        if self._validate_code(code):
            try:
                await self._device.async_arm_stay(
                    force_bypass=CONF_FORCE_BYPASS in arm_options,
                    no_entry_delay=CONF_NO_ENTRY_DELAY in arm_options,
                    silent_arming=CONF_SILENT_ARM in arm_options,
                )
            except NotAuthorized:
                self._show_permission_error("arm_home")

    async def async_alarm_arm_away(self, code: str | None = None) -> None:
        """Send arm away command."""

        arm_options = self._controller.options.get(CONF_ARM_AWAY, {})

        if self._validate_code(code):
            try:
                await self._device.async_arm_away(
                    force_bypass=CONF_FORCE_BYPASS in arm_options,
                    no_entry_delay=CONF_NO_ENTRY_DELAY in arm_options,
                    silent_arming=CONF_SILENT_ARM in arm_options,
                )
            except NotAuthorized:
                self._show_permission_error("arm_away")

    def _validate_code(self, code: str | None) -> bool | str:
        """Validate given code."""
        check: bool | str = (arm_code := self._controller.options.get(CONF_ARM_CODE)) in [
            None,
            "",
        ] or code == arm_code
        if not check:
            LOGGER.warning("Wrong code entered.")
        return check
