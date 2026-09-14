from homeassistant.components.switch import SwitchEntity
from .entity import SolarEntity
from .settings import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([SolarMode(hass.data[DOMAIN])])

class SolarMode(SolarEntity, SwitchEntity):
    _attr_icon = 'mdi:solar-power-variant'
    def __init__(self, controller):
        super().__init__(controller, 'enabled', 'Solar charging')
    @property
    def is_on(self):
        return self.controller.enabled
    async def async_turn_on(self, **kwargs):
        await self.controller.set_enabled(True)
    async def async_turn_off(self, **kwargs):
        await self.controller.set_enabled(False)
