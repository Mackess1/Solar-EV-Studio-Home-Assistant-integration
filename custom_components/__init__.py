"""Solar EV Studio custom integration."""
from pathlib import Path
import voluptuous as vol
from homeassistant.components import frontend, panel_custom, websocket_api
from homeassistant.components.http import StaticPathConfig
from homeassistant.const import EVENT_HOMEASSISTANT_STOP
from homeassistant.core import callback
from .controller import Controller
from .settings import DOMAIN

async def async_setup(hass, config):
    await hass.http.async_register_static_paths([StaticPathConfig('/solar_ev_studio_frontend', str(Path(__file__).parent / 'frontend'), False)])
    websocket_api.async_register_command(hass, ws_get)
    websocket_api.async_register_command(hass, ws_save)
    websocket_api.async_register_command(hass, ws_enable)
    return True

async def async_setup_entry(hass, entry):
    controller = Controller(hass, entry)
    hass.data[DOMAIN] = controller
    try:
        await hass.config_entries.async_forward_entry_setups(entry, ['sensor', 'switch'])
        await panel_custom.async_register_panel(hass, frontend_url_path='solar-ev-studio', webcomponent_name='solar-ev-integration-panel', sidebar_title='Solar EV Studio', sidebar_icon='mdi:solar-power-variant', module_url='/solar_ev_studio_frontend/studio.js?v=1.0.0', require_admin=True, config_panel_domain=DOMAIN)
        await controller.start()
    except Exception:
        if controller.task:
            await controller.close()
        await hass.config_entries.async_unload_platforms(entry, ['sensor','switch'])
        frontend.async_remove_panel(hass, 'solar-ev-studio')
        hass.data.pop(DOMAIN, None)
        raise
    async def shutdown(event):
        await controller.close()
    entry.async_on_unload(hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STOP, shutdown))
    return True

async def async_unload_entry(hass, entry):
    controller = hass.data[DOMAIN]
    try:
        await controller.close()
    except Exception:
        return False
    result = await hass.config_entries.async_unload_platforms(entry, ['sensor','switch'])
    if result:
        frontend.async_remove_panel(hass, 'solar-ev-studio')
        hass.data.pop(DOMAIN, None)
    return result

def get_controller(hass, connection):
    connection.require_admin()
    if DOMAIN not in hass.data:
        raise ValueError('Add the Solar EV Studio integration first')
    return hass.data[DOMAIN]

@websocket_api.websocket_command({vol.Required('type'): DOMAIN + '/get'})
@callback
def ws_get(hass, connection, msg):
    try:
        connection.send_result(msg['id'], get_controller(hass, connection).public_state())
    except ValueError as err:
        connection.send_error(msg['id'], 'not_loaded', str(err))

@websocket_api.websocket_command({vol.Required('type'): DOMAIN + '/save', vol.Required('settings'): dict, vol.Required('revision'): int})
@websocket_api.async_response
async def ws_save(hass, connection, msg):
    controller = get_controller(hass, connection)
    try:
        await controller.save_settings(msg['settings'], msg['revision'])
        connection.send_result(msg['id'], controller.public_state())
    except Exception as err:
        controller.status = 'Settings save failed: ' + str(err)
        controller.notify()
        connection.send_error(msg['id'], 'save_failed', str(err))

@websocket_api.websocket_command({vol.Required('type'): DOMAIN + '/enable', vol.Required('enabled'): bool})
@websocket_api.async_response
async def ws_enable(hass, connection, msg):
    controller = get_controller(hass, connection)
    try:
        await controller.set_enabled(msg['enabled'])
        connection.send_result(msg['id'], controller.public_state())
    except Exception as err:
        controller.status = 'Control failed: ' + str(err)
        controller.notify()
        connection.send_error(msg['id'], 'control_failed', str(err))
