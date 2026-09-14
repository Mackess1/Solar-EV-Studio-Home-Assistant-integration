from homeassistant.helpers.entity import Entity, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from .settings import DOMAIN

class SolarEntity(Entity):
    _attr_should_poll = False
    _attr_has_entity_name = True
    def __init__(self, controller, key, name):
        self.controller = controller
        self._attr_name = name
        self._attr_unique_id = DOMAIN + '_' + key
        self._attr_device_info = DeviceInfo(identifiers={(DOMAIN, DOMAIN)}, name='Solar EV Studio', manufacturer='Custom integration', model='Solar EV controller', configuration_url='homeassistant://solar-ev-studio')
    async def async_added_to_hass(self):
        self.async_on_remove(async_dispatcher_connect(self.hass, DOMAIN + '_updated', self.async_write_ha_state))
