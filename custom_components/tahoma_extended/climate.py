import asyncio
from datetime import timedelta
import logging

import voluptuous as vol

import homeassistant.helpers.config_validation as cv
from homeassistant.components.climate import ClimateDevice, PLATFORM_SCHEMA

from homeassistant.components.climate.const import (
    HVAC_MODE_HEAT,
    HVAC_MODE_OFF,
    PRESET_AWAY,
    PRESET_ECO,
    PRESET_COMFORT,
    PRESET_NONE,
    CURRENT_HVAC_HEAT,
    CURRENT_HVAC_IDLE,
    SUPPORT_TARGET_TEMPERATURE,
    SUPPORT_PRESET_MODE,
)
from homeassistant.const import (
    TEMP_CELSIUS,
    ATTR_TEMPERATURE,
    ATTR_BATTERY_LEVEL,
    CONF_NAME,
    CONF_ENTITY_ID,
    CONF_SENSORS,
    STATE_UNKNOWN,
    EVENT_HOMEASSISTANT_START,
)
from homeassistant.core import callback
from homeassistant.helpers.event import async_track_state_change
from . import DOMAIN as TAHOMA_DOMAIN, TahomaDevice

CONF_AWAY_TEMP = "away_temp"
CONF_ECO_TEMP = "eco_temp"
CONF_COMFORT_TEMP = "comfort_temp"
CONF_ANTI_FREEZE_TEMP = "anti_freeze_temp"

SUPPORT_AWAY_TEMP = 1
SUPPORT_ECO_TEMP = 2
SUPPORT_COMFORT_TEMP = 4
SUPPORT_ANTI_FREEZE_TEMP = 8

PRESET_ANTI_FREEZE = "Anti-freeze"

SENSOR_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_NAME): cv.string,
        vol.Required(CONF_ENTITY_ID): cv.entity_domain("sensor"),
        vol.Optional(CONF_AWAY_TEMP): vol.Coerce(float),
        vol.Optional(CONF_ECO_TEMP): vol.Coerce(float),
        vol.Optional(CONF_COMFORT_TEMP): vol.Coerce(float),
        vol.Optional(CONF_ANTI_FREEZE_TEMP): vol.Coerce(float),
    }
)

PLATFORM_SCHEMA = PLATFORM_SCHEMA.extend(
    {vol.Required(CONF_SENSORS): vol.All(cv.ensure_list, [SENSOR_SCHEMA])}
)

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=120)
SUPPORT_FLAGS = SUPPORT_TARGET_TEMPERATURE


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up Tahoma Thermostat."""
    controller = hass.data[TAHOMA_DOMAIN]["controller"]
    devices = []

    for device in hass.data[TAHOMA_DOMAIN]["devices"]["climate"]:
        name = device.label
        device_sensor = None
        for sensor in config["sensors"]:
            if sensor[CONF_NAME] == name:
                device_sensor = sensor[CONF_ENTITY_ID]
                away_temp = sensor.get(CONF_AWAY_TEMP)
                eco_temp = sensor.get(CONF_ECO_TEMP)
                comfort_temp = sensor.get(CONF_COMFORT_TEMP)
                anti_freeze_temp = sensor.get(CONF_ANTI_FREEZE_TEMP)

        if device_sensor is None:
            _LOGGER.error("Could not find a sensor for thermostat " + name)
            return
        device.temperature_sensor = device_sensor
        devices.append(
            TahomaThermostat(
                device,
                controller,
                device_sensor,
                away_temp,
                eco_temp,
                comfort_temp,
                anti_freeze_temp,
            )
        )

    async_add_entities(devices, True)


class TahomaThermostat(TahomaDevice, ClimateDevice):
    """Representation of a Tahoma thermostat."""

    def __init__(
            self,
            tahoma_device,
            controller,
            sensor_entity_id,
            away_temp,
            eco_temp,
            comfort_temp,
            anti_freeze_temp,
    ):
        """Initialize the device."""
        super().__init__(tahoma_device, controller)
        if self.tahoma_device.type == "io:AtlanticElectricalHeaterIOComponent":
            self._type = "io"
            if self.tahoma_device.active_states["core:OnOffState"] == "on":
                self._hvac_mode = HVAC_MODE_HEAT
            else:
                self._hvac_mode = HVAC_MODE_OFF
        if (
                self.tahoma_device.type
                == "somfythermostat:SomfyThermostatThermostatComponent"
        ):
            self._type = "thermostat"
            if (
                    self.tahoma_device.active_states["core:DerogationActivationState"]
                    == "active"
            ):
                self._hvac_mode = HVAC_MODE_HEAT
            else:
                self._hvac_mode = HVAC_MODE_OFF
        self._cur_temp = None
        self._unit = TEMP_CELSIUS
        self.sensor_entity_id = sensor_entity_id
        self._support_flags = SUPPORT_FLAGS
        self._current_hvac_mode = CURRENT_HVAC_IDLE
        self._hvac_list = [HVAC_MODE_HEAT, HVAC_MODE_OFF]
        self._preset_mode = None
        self._somfy_modes = 0
        self._away_temp = away_temp
        self._eco_temp = eco_temp
        self._comfort_temp = comfort_temp
        self._anti_freeze_temp = anti_freeze_temp
        if self._type == "thermostat":
            if away_temp is None:
                self._somfy_modes = self._somfy_modes | SUPPORT_AWAY_TEMP
                self._away_temp = float(
                    self.tahoma_device.active_states["somfythermostat:AwayModeTargetTemperatureState"])
            if eco_temp is None:
                self._somfy_modes = self._somfy_modes | SUPPORT_ECO_TEMP
                self._eco_temp = self.tahoma_device.active_states["somfythermostat:SleepingModeTargetTemperatureState"]
            if comfort_temp is None:
                self._somfy_modes = self._somfy_modes | SUPPORT_COMFORT_TEMP
                self._comfort_temp = self.tahoma_device.active_states["somfythermostat:AtHomeTargetTemperatureState"]
            if anti_freeze_temp is None:
                self._somfy_modes = self._somfy_modes | SUPPORT_ANTI_FREEZE_TEMP
                self._anti_freeze_temp = \
                    self.tahoma_device.active_states["somfythermostat:FreezeModeTargetTemperatureState"]
        if away_temp or eco_temp or comfort_temp or anti_freeze_temp or self._somfy_modes:
            self._support_flags = SUPPORT_FLAGS | SUPPORT_PRESET_MODE
            self._preset_mode = PRESET_NONE
        self._target_temp = 21
        self._saved_target_temp = self._target_temp
        self._temp_lock = asyncio.Lock()
        self._active = False
        self._cold_tolerance = 0.3
        self._hot_tolerance = 0.3
        self._update_caller = "none"

    def update(self):
        """Update method."""
        from time import sleep
        self.controller.get_states([self.tahoma_device])
        sensor_state = self.hass.states.get(self.sensor_entity_id)
        if sensor_state and sensor_state.state != STATE_UNKNOWN:
            self._async_update_temp(sensor_state)
        if self._type == "io":
            state = self.tahoma_device.active_states["io:TargetHeatingLevelState"]
            if state == "off":
                self._current_hvac_mode = CURRENT_HVAC_IDLE
            else:
                self._current_hvac_mode = CURRENT_HVAC_HEAT
        if self._type == "thermostat":
            # if self.tahoma_device.active_states["somfythermostat:HeatingModeState"] == "freezeMode":
            #     self._target_temp = self.tahoma_device.active_states["somfythermostat:FreezeModeTargetTemperatureState"]
            # else:
            #     self._target_temp = self.tahoma_device.active_states["core:TargetTemperatureState"]
            state = self.tahoma_device.active_states["somfythermostat:DerogationHeatingModeState"]
            _LOGGER.debug("caller: %s, target: %s, saved: %s", self._update_caller, self._target_temp,
                         self._saved_target_temp)
            self._target_temp = self.tahoma_device.active_states["core:DerogatedTargetTemperatureState"]
            if self._somfy_modes | SUPPORT_AWAY_TEMP:
                self._away_temp = self.tahoma_device.active_states["somfythermostat:AwayModeTargetTemperatureState"]
            if self._somfy_modes | SUPPORT_ECO_TEMP:
                self._eco_temp = self.tahoma_device.active_states["somfythermostat:SleepingModeTargetTemperatureState"]
            if self._somfy_modes | SUPPORT_COMFORT_TEMP:
                self._comfort_temp = self.tahoma_device.active_states["somfythermostat:AtHomeTargetTemperatureState"]
            if self._somfy_modes | SUPPORT_ANTI_FREEZE_TEMP:
                self._anti_freeze_temp = \
                    self.tahoma_device.active_states["somfythermostat:FreezeModeTargetTemperatureState"]

    @property
    def hvac_action(self):
        """Return the current running hvac operation if supported.

        Need to be one of CURRENT_HVAC_*.
        """
        return self._current_hvac_mode

    @property
    def target_temperature(self):
        """Return the temperature we try to reach."""
        return self._target_temp

    @property
    def hvac_mode(self) -> str:
        """Return current operation."""
        return self._hvac_mode

    @property
    def hvac_modes(self):
        """List of available operation modes."""
        return self._hvac_list

    @property
    def preset_mode(self):
        """Return the current preset mode, e.g., home, away, temp."""
        return self._preset_mode

    @property
    def preset_modes(self):
        """Return a list of available preset modes."""
        preset_modes = []
        if self._away_temp:
            preset_modes.append(PRESET_AWAY)
        if self._eco_temp:
            preset_modes.append(PRESET_ECO)
        if self._comfort_temp:
            preset_modes.append(PRESET_COMFORT)
        if self._anti_freeze_temp:
            preset_modes.append(PRESET_ANTI_FREEZE)
        if not preset_modes:
            return None
        preset_modes.append(PRESET_NONE)
        return preset_modes

    @property
    def supported_features(self):
        """Return the list of supported features."""
        return self._support_flags

    @property
    def temperature_unit(self):
        """Return the unit of measurement."""
        return self._unit

    @property
    def current_temperature(self):
        """Return the sensor temperature."""
        return self._cur_temp

    async def async_added_to_hass(self):
        await super().async_added_to_hass()

        async_track_state_change(
            self.hass, self.sensor_entity_id, self._async_sensor_changed
        )

        @callback
        def _async_startup(event):
            """Init on startup."""
            sensor_state = self.hass.states.get(self.sensor_entity_id)
            if sensor_state and sensor_state.state != STATE_UNKNOWN:
                self._async_update_temp(sensor_state)

        self.hass.bus.async_listen_once(EVENT_HOMEASSISTANT_START, _async_startup)

    async def _async_sensor_changed(self, entity_id, old_state, new_state):
        """Handle temperature changes."""
        if new_state is None:
            return

        self._async_update_temp(new_state)
        await self._async_control_heating()
        await self.async_update_ha_state()

    @callback
    def _async_update_temp(self, state):
        """Update thermostat with latest state from sensor."""
        try:
            self._cur_temp = float(state.state)
        except ValueError as ex:
            _LOGGER.error("Unable to update from sensor: %s", ex)

    async def _async_control_heating(self):
        """Check if we need to turn heating on or off."""
        async with self._temp_lock:
            if not self._active and None not in (self._cur_temp, self._target_temp):
                self._active = True
                _LOGGER.info(
                    "Obtained current and target temperature. "
                    "Thermostat active. %s, %s",
                    self._cur_temp,
                    self._target_temp,
                )

            if not self._active:
                return

            too_cold = self._target_temp - self._cur_temp >= self._cold_tolerance
            too_hot = self._cur_temp - self._target_temp >= self._hot_tolerance

            if too_hot:
                _LOGGER.info("Turning off heater %s", self.name)
                await self._async_heater_turn_off()
            if too_cold:
                _LOGGER.info("Turning on heater %s", self.name)
                await self._async_heater_turn_on()

    @property
    def _is_device_active(self):
        """If the toggleable device is currently active."""
        state = "on"
        if self._type == "io":
            state = self.tahoma_device.active_states["core:OnOffState"]
        return state == "on"

    def _apply_action(self, target_temperature):
        if target_temperature < 16:
            target_temperature = 16
        if self.tahoma_device.active_states['core:DerogatedTargetTemperatureState'] != target_temperature:
            from time import sleep
            self.apply_action("refreshState")
            self.apply_action("setModeTemperature", "manualMode", target_temperature)
            self.apply_action("setDerogation", target_temperature, "further_notice")
            self.apply_action("refreshState")
            sleep(20)

    async def _async_heater_turn_on(self):
        """Turn heater toggleable device on."""
        if self._type == "io":
            self.apply_action("setHeatingLevel", "comfort")
        elif self._type == "thermostat":
            self._apply_action(self.target_temperature)
        self._current_hvac_mode = CURRENT_HVAC_HEAT
        await self.async_update_ha_state()
        self._update_caller = "_async_heater_turn_on"
        self.update()

    async def _async_heater_turn_off(self):
        """Turn heater toggleable device off."""
        if self._type == "io":
            self.apply_action("setHeatingLevel", "off")
        elif self._type == "thermostat":
            self._apply_action(self.target_temperature)
        self._current_hvac_mode = CURRENT_HVAC_IDLE
        await self.async_update_ha_state()
        self._update_caller = "_async_heater_turn_off"
        self.update()

    async def async_set_hvac_mode(self, hvac_mode):
        """Set hvac mode."""
        if hvac_mode == HVAC_MODE_HEAT:
            self._hvac_mode = HVAC_MODE_HEAT
            await self._async_control_heating()
        elif hvac_mode == HVAC_MODE_OFF:
            self._hvac_mode = HVAC_MODE_OFF
            if self._is_device_active:
                await self._async_heater_turn_off()
        else:
            _LOGGER.error("Unrecognized hvac mode: %s", hvac_mode)
            return
        # Ensure we update the current operation after changing the mode
        self.schedule_update_ha_state()
        self._update_caller = "async_set_hvac_mode"
        self.update()

    async def async_set_temperature(self, **kwargs):
        """Set new target temperature."""
        temperature = kwargs.get(ATTR_TEMPERATURE)
        if temperature is None:
            return
        self._target_temp = temperature
        # if self._type == "thermostat":
        #     self.apply_action(
        #         "setModeTemperature", "manualMode", self.target_temperature
        #     )
        await self._async_control_heating()
        # self.update()

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set new preset mode.

        This method must be run in the event loop and returns a coroutine.
        """
        if preset_mode not in self.preset_modes:
            _LOGGER.error(
                "Preset " + preset_mode + " is not available for " + self._name
            )
            return
        if preset_mode == PRESET_AWAY and not self._preset_mode == PRESET_AWAY:
            self._preset_mode = PRESET_AWAY
            self._saved_target_temp = self._target_temp
            self._target_temp = self._away_temp
            await self._async_control_heating()
        elif preset_mode == PRESET_ECO and not self._preset_mode == PRESET_ECO:
            self._preset_mode = PRESET_ECO
            self._saved_target_temp = self._target_temp
            self._target_temp = self._eco_temp
            await self._async_control_heating()
        elif preset_mode == PRESET_COMFORT and not self._preset_mode == PRESET_COMFORT:
            self._preset_mode = PRESET_COMFORT
            self._saved_target_temp = self._target_temp
            self._target_temp = self._comfort_temp
            await self._async_control_heating()
        elif (
                preset_mode == PRESET_ANTI_FREEZE
                and not self._preset_mode == PRESET_ANTI_FREEZE
        ):
            self._preset_mode = PRESET_ANTI_FREEZE
            self._saved_target_temp = self._target_temp
            self._target_temp = self._anti_freeze_temp
            await self._async_control_heating()
        elif preset_mode == PRESET_NONE and not self._preset_mode == PRESET_NONE:
            self._preset_mode = PRESET_NONE
            self._target_temp = self._saved_target_temp
            await self._async_control_heating()
        await self.async_update_ha_state()
        self._update_caller = "async_set_preset_mode"
        self.update()

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        attr = {}
        super_attr = super().device_state_attributes
        if super_attr is not None:
            attr.update(super_attr)
        if "core:BatteryLevelState" in self.tahoma_device.active_states:
            attr[ATTR_BATTERY_LEVEL] = self.tahoma_device.active_states[
                "core:BatteryLevelState"
            ]
        attr["preset_mode"] = self._preset_mode
        return attr
