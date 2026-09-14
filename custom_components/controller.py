"""Own the actuator, persistent session state, and atomic settings updates."""
import asyncio
import logging
import math
import time
from homeassistant.helpers.storage import Store
from homeassistant.helpers.dispatcher import async_dispatcher_send
from .engine import decide
from .settings import DOMAIN, SOURCES, validate

LOGGER = logging.getLogger(__name__)
LEGACY_MASTER = 'input_boolean.solar_ev_charging_enabled'
LEGACY_AUTOS = ('automation.solar_ev_charging_controller', 'automation.solar_ev_mode_and_restart_interlock', 'automation.solar_ev_stop_watchdog')

class Controller:
    def __init__(self, hass, entry):
        self.hass, self.entry = hass, entry
        self.config = validate(entry.options or entry.data)
        self.store = Store(hass, 1, DOMAIN + '.runtime')
        self.lock = asyncio.Lock()
        self.enabled = False
        self.session = False
        self.memory = {}
        self.pending_stops = []
        self.status = 'Solar mode off'
        self.plan = {}
        self.factor = self.config['factor']
        self.task = None
        self.closed = False
        self.next_tick = 0
        self.urgent_since = None
        self.handover_pending = False
        self.revision = int(entry.modified_at.timestamp() * 1000000)

    async def persist(self):
        await self.store.async_save(dict(enabled=self.enabled, session=self.session, pending_stops=self.pending_stops, factor=self.factor))

    def notify(self):
        async_dispatcher_send(self.hass, DOMAIN + '_updated')

    async def start(self):
        saved = await self.store.async_load() or {}
        self.enabled = bool(saved.get('enabled', False))
        self.handover_pending = self.enabled
        self.session = bool(saved.get('session', False))
        self.pending_stops = list(saved.get('pending_stops', []))
        self.factor = min(max(saved.get('factor', self.config['factor']), self.config['factor']), self.config['factor_max'])
        self.memory = dict(p='cooldown', t=time.time(), a=0)
        if self.enabled and self.config['switch_entity'] not in self.pending_stops:
            self.pending_stops.append(self.config['switch_entity'])
        self.task = self.hass.async_create_background_task(self.run(), 'Solar EV controller')

    async def service(self, domain, service, entity, **data):
        async with asyncio.timeout(max(self.config['switch_timeout'], self.config['ack_timeout'])):
            await self.hass.services.async_call(domain, service, {'entity_id': entity, **data}, blocking=True)

    async def wait_for(self, predicate, timeout):
        end = time.monotonic() + timeout
        while not predicate():
            if time.monotonic() >= end:
                raise RuntimeError('Charger did not acknowledge command')
            await asyncio.sleep(0.5)

    async def stop(self, entity):
        # Every path that writes amps must pass this acknowledgement barrier.
        if not self.hass.states.is_state(entity, 'off'):
            await self.service('switch', 'turn_off', entity)
        await self.wait_for(lambda: self.hass.states.is_state(entity, 'off'), self.config['switch_timeout'])

    async def queue_stop(self, entity):
        if self.hass.states.is_state(entity, 'off') and entity not in self.pending_stops:
            return
        if entity not in self.pending_stops:
            self.pending_stops.append(entity)
            await self.persist()
        await self.stop(entity)
        self.pending_stops.remove(entity)
        await self.persist()

    def snapshot(self):
        c, now = self.config, time.time()
        s = dict(now=now, valid=True, enabled=self.enabled, session=self.session, memory=self.memory)
        times = {}
        for key, spec in SOURCES.items():
            if len(spec) < 4:
                continue
            entity = self.hass.states.get(c[key + '_entity'])
            try:
                value = float(entity.state)
                if not math.isfinite(value):
                    raise ValueError('Nonfinite reading')
                timestamp = entity.last_reported.timestamp()
                if entity.attributes.get('unit_of_measurement') != c[key + '_unit'] or (c[key + '_age'] and now - timestamp > c[key + '_age']):
                    s['valid'] = False
                value *= 1000 if c[key + '_unit'] == 'kW' else 1
                value *= c[key + '_sign'] if key in ('grid', 'battery') else 1
            except (ValueError, TypeError, AttributeError):
                value, timestamp, s['valid'] = 0, 0, False
            s[key], times[key] = value, timestamp
        s['work'] = self.hass.states.get(c['work_entity']).state if self.hass.states.get(c['work_entity']) else 'unavailable'
        s['on'] = self.hass.states.is_state(c['switch_entity'], 'on')
        s['day'] = self.hass.states.is_state(c['sun_entity'], c['day_state'])
        s['fault'] = s['work'] in (c['fault_state'], c['free_fault_state'])
        switch = self.hass.states.get(c['switch_entity'])
        valid_work = [c[k] for k in ('free_state','insert_state','wait_state','pause_state','end_state','charging_state','fault_state','free_fault_state')]
        s['valid'] = s['valid'] and switch is not None and switch.state in ('on','off') and s['work'] in valid_work and self.hass.states.is_state(c['mode_entity'], c['mode_state']) and 0 <= s['soc'] <= 100 and c['voltage_min'] <= s['voltage'] <= c['voltage_max'] and 0 <= s['ev'] <= c['ev_max'] and 0 <= s['pv'] <= c['pv_max'] and 0 <= s['load'] <= c['load_max']
        s['ev_time'], s['ev_age'] = times['ev'], now - times['ev']
        return s

    async def change_current(self, plan):
        c = self.config
        self.status = 'Stopping before changing amps'
        self.notify()
        await self.queue_stop(c['switch_entity'])
        if not self.enabled:
            return
        amps = int(plan['a'])
        if amps not in [int(x) for x in c['levels'].split(',')] or amps > c['cap']:
            raise RuntimeError('Rejected unsupported current')
        await self.service('number', 'set_value', c['command_entity'], value=amps)
        def acknowledged():
            state = self.hass.states.get(c['command_entity'])
            try:
                return float(state.state) == amps
            except (TypeError, ValueError, AttributeError):
                return False
        await self.wait_for(acknowledged, c['ack_timeout'])
        await asyncio.sleep(c['actuator_delay'])
        fresh = decide(self.snapshot(), {**c, 'factor': self.factor})
        if not self.enabled or not fresh['z']:
            self.memory = dict(p='cooldown', t=time.time(), a=0)
            self.status = 'Paused: conditions changed during adjustment'
            return
        self.session = True
        await self.persist()
        await self.service('switch', 'turn_on', c['switch_entity'])
        await self.wait_for(lambda: self.hass.states.is_state(c['switch_entity'], 'on'), c['switch_timeout'])
        self.memory = {**plan['m'], 't': time.time()}

    async def tick(self):
        async with self.lock:
            for entity in list(self.pending_stops):
                await self.queue_stop(entity)
            if not self.enabled:
                return
            if self.handover_pending:
                if not self.hass.is_running:
                    return
                await self.handover_legacy()
                self.handover_pending = False
                self.memory = dict(p='cooldown', t=time.time(), a=0)
            # Refuse simultaneous ownership, including legacy automations re-enabled later.
            if self.hass.states.is_state(LEGACY_MASTER, 'on') or any(self.hass.states.is_state(x, 'on') for x in LEGACY_AUTOS):
                raise RuntimeError('Legacy controller is enabled; disable it before using this integration')
            s = self.snapshot()
            p = decide(s, {**self.config, 'factor': self.factor})
            self.plan, self.memory, self.status = p, p['m'], p['r']
            if p['c'] in ('pause','fault','complete'):
                await self.queue_stop(self.config['switch_entity'])
                if p['c'] in ('fault','complete'):
                    self.session = False
                    await self.persist()
            elif p['c'] in ('start','increase','reduce'):
                await self.change_current(p)
            elif p['c'] == 'accept' and s['light'] > 0:
                self.factor = max(self.factor, min(self.config['factor_max'], s['pv']/s['light']))
                await self.persist()
            self.notify()

    async def run(self):
        while not self.closed:
            try:
                s = self.snapshot()
                urgent = s['grid'] > self.config['urgent_grid'] or s['battery'] < -self.config['urgent_battery'] or s['fault']
                self.urgent_since = (self.urgent_since or time.monotonic()) if urgent else None
                if time.monotonic() >= self.next_tick or (self.urgent_since and time.monotonic()-self.urgent_since >= self.config['urgent_dwell']):
                    self.urgent_since = None
                    await self.tick()
                    self.next_tick = time.monotonic() + self.config['poll']
            except asyncio.CancelledError:
                raise
            except Exception as err:
                self.status = str(err)
                self.memory = dict(p='fault', t=time.time(), a=0)
                if self.enabled and self.config['switch_entity'] not in self.pending_stops:
                    self.pending_stops.append(self.config['switch_entity'])
                LOGGER.warning('Solar EV stopped: %s', err)
                self.notify()
                self.next_tick = time.monotonic() + self.config['poll']
                try:
                    await self.persist()
                except Exception:
                    LOGGER.exception('Unable to persist Solar EV stop request')
            await asyncio.sleep(1)

    async def handover_legacy(self):
        if self.hass.states.get(LEGACY_MASTER):
            await self.service('input_boolean', 'turn_off', LEGACY_MASTER)
            await asyncio.sleep(1)
            interlock = 'automation.solar_ev_mode_and_restart_interlock'
            await self.wait_for(lambda: not self.hass.states.get(interlock) or self.hass.states.get(interlock).attributes.get('current', 0) == 0, 60)
        for entity in LEGACY_AUTOS:
            if self.hass.states.get(entity):
                await self.service('automation', 'turn_off', entity, stop_actions=True)

    async def set_enabled(self, enabled):
        if not enabled:
            self.enabled = False  # Interrupt an in-flight adjustment before it can resume.
        async with self.lock:
            if enabled:
                validate(self.config, self.hass.states)
                # Explicit activation transfers ownership from the earlier installation.
                await self.handover_legacy()
                await self.queue_stop(self.config['switch_entity'])
                self.handover_pending = False
                self.enabled, self.session = True, True
                self.memory = dict(p='cooldown', t=time.time(), a=0)
                self.status = 'Waiting for solar after activation'
            else:
                self.enabled = False
                self.session = False
                await self.persist()
                await self.queue_stop(self.config['switch_entity'])
                self.status = 'Solar mode off'
            await self.persist()
            self.next_tick = 0
            self.notify()

    async def save_settings(self, settings, revision):
        c = validate(settings, self.hass.states)
        if revision != self.revision:
            raise ValueError('Settings changed in another tab; reload Studio')
        self.enabled = False
        async with self.lock:
            if revision != self.revision:
                await self.queue_stop(self.config['switch_entity'])
                raise ValueError('Settings changed in another tab; reload Studio')
            self.enabled = False
            self.session = False
            for entity in (self.config['switch_entity'], c['switch_entity']):
                if entity not in self.pending_stops:
                    self.pending_stops.append(entity)
            await self.persist()
            for entity in list(self.pending_stops):
                await self.queue_stop(entity)
            self.hass.config_entries.async_update_entry(self.entry, options=c)
            self.config, self.factor = c, c['factor']
            self.revision = max(self.revision + 1, int(self.entry.modified_at.timestamp() * 1000000))
            self.memory = dict(p='cooldown', t=time.time(), a=0)
            self.status = 'Settings saved; solar mode paused'
            await self.persist()
            self.notify()

    async def close(self):
        async with self.lock:
            if self.enabled or self.pending_stops:
                for entity in set(self.pending_stops + [self.config['switch_entity']]):
                    await self.queue_stop(entity)
            self.closed = True
        if self.task:
            self.task.cancel()
            try:
                await self.task
            except asyncio.CancelledError:
                pass

    def public_state(self):
        return dict(settings=self.config, revision=self.revision, enabled=self.enabled, status=self.status, memory=self.memory, plan=self.plan, learned_factor=self.factor, pending_stops=self.pending_stops)
