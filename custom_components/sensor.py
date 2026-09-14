from homeassistant.components.sensor import SensorEntity
from .entity import SolarEntity
from .settings import DOMAIN

async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([Status(hass.data[DOMAIN])])

class Status(SolarEntity, SensorEntity):
    def __init__(self, controller):
        super().__init__(controller, 'status', 'Status')
    @property
    def native_value(self):
        return self.controller.status[:255]
    @property
    def extra_state_attributes(self):
        c = self.controller
        return {'phase': c.memory.get('p'), 'command': c.plan.get('c'), 'target_amps': c.plan.get('a'), 'estimated_solar_w': c.plan.get('w'), 'learned_light_factor': c.factor, 'pending_stop_entities': c.pending_stops}
