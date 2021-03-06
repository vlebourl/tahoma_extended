"""Tahoma light platform that implements dimmable tahoma lights."""
import logging
from datetime import timedelta

try:
    from homeassistant.components.light import LightEntity
except ImportError:
    from homeassistant.components.light import Light as LightEntity

from homeassistant.components.light import (
    ATTR_BRIGHTNESS,
    ATTR_EFFECT,
    SUPPORT_BRIGHTNESS,
    SUPPORT_EFFECT,
)

from homeassistant.const import STATE_OFF, STATE_ON


from . import DOMAIN as TAHOMA_DOMAIN, TahomaDevice

_LOGGER = logging.getLogger(__name__)

SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_platform(hass, config, async_add_entities, discovery_info=None):
    """Set up the Tahoma light platform."""
    controller = hass.data[TAHOMA_DOMAIN]["controller"]
    devices = []

    for device in hass.data[TAHOMA_DOMAIN]["devices"]["light"]:
        name = device.label
        devices.append(TahomaLight(device, controller))

    async_add_entities(devices, True)


class TahomaLight(TahomaDevice, LightEntity):
    """Representation of a Tahome light"""

    def __init__(
        self,
        tahoma_device,
        controller
    ):
        super().__init__(tahoma_device, controller)
        self._skip_update = False
        self._effect = None
        if self.tahoma_device.type == "io:DimmableLightIOComponent":
            self._type = "io"
            self._unique_id = self.tahoma_device.url
            self.update()


    @property
    def brightness(self) -> int:
        """Return the brightness of this light between 0..255."""
        _LOGGER.debug("[THM] Called to get brightness %s" % (self._brightness))
        return int(self._brightness * (255 / 100))

    @property
    def is_on(self) -> bool:
        """Return true if light is on."""
        _LOGGER.debug("[THM] Called to check is on %s" % (self._state))
        return self._state

    @property
    def supported_features(self) -> int:
        """Flag supported features."""
        return SUPPORT_BRIGHTNESS | SUPPORT_EFFECT

    async def async_turn_on(self, **kwargs) -> None:
        """Turn the light on."""
        _LOGGER.debug("[THM] Called to turn on (%s, %s)", kwargs, self._brightness)
        self._state = True
        self._skip_update = True

        if ATTR_BRIGHTNESS in kwargs:
            self._brightness = int(float(kwargs[ATTR_BRIGHTNESS]) / 255 * 100)
            self.apply_action("setIntensity", self._brightness)
        elif  ATTR_EFFECT in kwargs:
            self._effect = kwargs[ATTR_EFFECT]
            self.apply_action("wink", 100)
        else:
            self._brightness = 100
            self.apply_action("on")
        

        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs) -> None:
        """Turn the light off."""
        _LOGGER.debug("[THM] Called to turn off")
        self._state = False
        self._skip_update = True
        self.apply_action("off")

        self.async_write_ha_state()

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        attr = {}
        super_attr = super().device_state_attributes
        if super_attr is not None:
            attr.update(super_attr)
        if "core:RSSILevelState" in self.tahoma_device.active_states:
            attr["rssi"] = self.tahoma_device.active_states["core:RSSILevelState"]
        return attr

    @property
    def effect_list(self) -> list:
        """Return the list of supported effects."""
        return ["wink"]

    @property
    def effect(self) -> str:
        """Return the current effect."""
        return self._effect

    @property
    def unique_id(self):
        """Return unique ID for light."""
        return self._unique_id

    def update(self):
        """Fetch new state data for this light.
        This is the only method that should fetch new data for Home Assistant.
        """
        # Postpone the immediate state check for changes that take time.
        if self._skip_update:
            self._skip_update = False
            return

        _LOGGER.debug("[THM] Updating state...")
        self.controller.get_states([self.tahoma_device])
        self._brightness = self.tahoma_device.active_states.get("core:LightIntensityState")
        if self.tahoma_device.active_states.get("core:OnOffState") == "on":
            self._state = True
        else:
            self._state = False
