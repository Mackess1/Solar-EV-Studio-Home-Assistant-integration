"""Server-side settings validation shared by setup and the Studio API."""
import json
import math
import re
from collections.abc import Mapping
from pathlib import Path

DOMAIN = 'solar_ev_studio'
SCHEMA = json.loads(Path(__file__).with_name('settings.json').read_text(encoding='utf-8'))
DEFAULTS, FIELDS, SOURCES = SCHEMA['defaults'], SCHEMA['fields'], SCHEMA['sources']

def validate(settings, states=None):
    if not isinstance(settings, Mapping) or set(settings) - set(DEFAULTS):
        raise ValueError('Unknown settings fields')
    c = {**DEFAULTS, **settings}
    for key, label, _, default, minimum, maximum, *_ in FIELDS:
        value = c[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
            raise ValueError(f'{label}: enter {minimum}–{maximum}')
    try:
        levels = [int(x.strip()) for x in c['levels'].split(',')]
    except (ValueError, AttributeError):
        raise ValueError('Supported currents must be comma-separated whole amps') from None
    if not levels or len(set(levels)) != len(levels) or any(x < 6 or x > 32 for x in levels) or c['cap'] not in levels:
        raise ValueError('Choose unique currents from 6 to 32 A and include the maximum')
    c['levels'] = ','.join(str(x) for x in sorted(levels))
    if c['settle'] >= c['feedback_max'] or c['fresh_after'] >= c['settle'] or c['ack_timeout'] >= c['feedback_max']:
        raise ValueError('Feedback timeout must exceed settling and acknowledgement times')
    if c['voltage_min'] >= c['voltage_max'] or c['factor'] > c['factor_max'] or c['floor'] + c['soc_hysteresis'] > 100 or c['slow_probe'] < c['fast_probe']:
        raise ValueError('Check voltage, factor ceiling, battery margin and probe intervals')
    if c['poll'] not in (5, 6, 10, 12, 15, 20, 30):
        raise ValueError('Invalid controller check interval')
    for key in ('grid_sign', 'battery_sign'):
        if c[key] not in (-1, 1) or isinstance(c[key], bool):
            raise ValueError('Power direction must be +1 or -1')
    for key, spec in SOURCES.items():
        label, _, domain, *extra = spec
        entity = c[key + '_entity']
        if not isinstance(entity, str) or not re.fullmatch(domain + r'\.[a-z0-9_]+', entity):
            raise ValueError(f'{label}: invalid entity')
        state = states.get(entity) if states is not None else None
        if states is not None and state is None:
            raise ValueError(f'{label}: entity does not exist')
        if extra:
            unit, age = c[key + '_unit'], c[key + '_age']
            allowed = ('W', 'kW') if key in ('pv', 'grid', 'battery', 'load', 'ev') else None if key == 'light' else (extra[0],)
            if not isinstance(unit, str) or not 1 <= len(unit) <= 24 or (allowed and unit not in allowed):
                raise ValueError(f'{label}: invalid unit')
            if isinstance(age, bool) or not isinstance(age, (int, float)) or not math.isfinite(age) or not 0 <= age <= 86400:
                raise ValueError(f'{label}: invalid reading age')
            if state is not None and state.attributes.get('unit_of_measurement') != unit:
                raise ValueError(f'{label}: unit does not match entity')
    for key in DEFAULTS:
        if key.endswith('_state') and (not isinstance(c[key], str) or not re.fullmatch(r'[a-zA-Z0-9_ -]{1,60}', c[key])):
            raise ValueError(f'Invalid state name: {key}')
    return c
