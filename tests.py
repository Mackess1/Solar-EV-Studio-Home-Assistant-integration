"""Run with Python 3.12+: python tests.py. No live charger or HA needed."""
import asyncio
from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
import sys
import types

ROOT = Path(__file__).parent
PACKAGE = ROOT / 'custom_components/solar_ev_studio'
pkg = types.ModuleType('solar_ev_studio'); pkg.__path__ = [str(PACKAGE)]; sys.modules[pkg.__name__] = pkg
from solar_ev_studio.engine import decide
from solar_ev_studio.settings import DEFAULTS, validate
assert validate(types.MappingProxyType(DEFAULTS))['cap'] == 32

scenarios = json.loads((ROOT/'test-cases.json').read_text())
for case in scenarios:
    s = case['s']
    c = {**DEFAULTS, **{k:s[k] for k in ('cap','floor','factor','reserve','margin')}}
    result = decide(s,c)
    assert (result['c'],result['a']) == (case['c'],case['a']), (case['name'],result)
for bad in ({'cap':33},{'levels':'6,6,32'},{'cap':7},{'factor':float('nan')},{'grid_sign':0},{'pv_entity':'number.wrong'},{'pv_unit':'kWh'},{'settle':300}):
    try: validate({**DEFAULTS,**bad})
    except ValueError: pass
    else: raise AssertionError(bad)

for name in ('homeassistant','homeassistant.helpers','homeassistant.helpers.storage','homeassistant.helpers.dispatcher'):
    sys.modules[name] = types.ModuleType(name)
class Store:
    def __init__(self,*args): self.data = {}
    async def async_save(self,data): self.data = dict(data)
    async def async_load(self): return self.data
sys.modules['homeassistant.helpers.storage'].Store = Store
sys.modules['homeassistant.helpers.dispatcher'].async_dispatcher_send = lambda *args: None
from solar_ev_studio.controller import Controller

class States(dict):
    def is_state(self,entity,state): return self.get(entity) is not None and self[entity].state == state
def state(value,unit=None): return types.SimpleNamespace(state=str(value),attributes={'unit_of_measurement':unit},last_reported=datetime.now(timezone.utc))

async def actuator(stop_fails=False,ack_fails=False,unsafe=False,disable_midflight=False):
    calls=[]
    states=States({DEFAULTS['switch_entity']:state('on'),DEFAULTS['command_entity']:state(8,'A')})
    async def service(domain,action,data,blocking):
        calls.append((domain,action,data.get('value')))
        if action == 'turn_off' and not stop_fails: states[data['entity_id']]=state('off')
        if action == 'turn_on': states[data['entity_id']]=state('on')
        if action == 'set_value' and not ack_fails: states[data['entity_id']]=state(data['value'],'A')
        if action == 'set_value' and disable_midflight: ctl.enabled=False
    entry=types.SimpleNamespace(data=dict(DEFAULTS),options={},modified_at=datetime.now(timezone.utc))
    hass=types.SimpleNamespace(states=states,services=types.SimpleNamespace(async_call=service))
    ctl=Controller(hass,entry);ctl.enabled=True
    ctl.config.update(actuator_delay=0,switch_timeout=.01,ack_timeout=.01)
    ctl.memory={'p':'adjust','a':10,'t':1800000000}
    snap={**scenarios[0]['s'],'on':False,'memory':ctl.memory,'valid':not unsafe}
    ctl.snapshot=lambda:snap
    p={'a':10,'m':{'p':'probe','a':10,'o':8,'t':1800000000}}
    try: await ctl.change_current(p)
    except RuntimeError:
        assert stop_fails or ack_fails
    if stop_fails: assert not any(x[1]=='set_value' for x in calls)
    if stop_fails or ack_fails or unsafe or disable_midflight: assert not any(x[1]=='turn_on' for x in calls)
    else: assert [x[1] for x in calls] == ['turn_off','set_value','turn_on']
    return calls

async def run():
    await actuator()
    await actuator(stop_fails=True)
    await actuator(ack_fails=True)
    await actuator(unsafe=True)
    await actuator(disable_midflight=True)
    for failed, stale in ((False,False),(True,False),(False,True)):
        from solar_ev_studio.settings import SOURCES
        states=States({v[1]:state(0,v[3] if len(v)>3 else None) for v in SOURCES.values()})
        states[DEFAULTS['switch_entity']]=state('on')
        entry=types.SimpleNamespace(data=dict(DEFAULTS),options={},modified_at=datetime.now(timezone.utc))
        updates=[]
        async def service(domain,action,data,blocking):
            if failed: raise RuntimeError('Stop failed')
            states[data['entity_id']]=state('off')
        def update(entry,options):
            assert states.is_state(DEFAULTS['switch_entity'],'off')
            entry.options=options;entry.modified_at=datetime.now(timezone.utc);updates.append(options)
        hass=types.SimpleNamespace(states=states,services=types.SimpleNamespace(async_call=service),config_entries=types.SimpleNamespace(async_update_entry=update))
        ctl=Controller(hass,entry);ctl.enabled=True
        try: await ctl.save_settings({**DEFAULTS,'cap':24},ctl.revision-1 if stale else ctl.revision)
        except (ValueError,RuntimeError): assert failed or stale
        if stale: assert ctl.enabled and not updates
        elif failed: assert not ctl.enabled and not updates and ctl.pending_stops
        else: assert not ctl.enabled and len(updates)==1 and ctl.config['cap']==24 and not ctl.pending_stops
asyncio.run(run())
print(f'{len(scenarios)} decision scenarios, invalid-settings checks, 5 actuator scenarios, and 3 save transaction scenarios passed.')
