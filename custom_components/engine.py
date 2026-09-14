"""Pure single-phase solar charging decisions; no Home Assistant dependencies."""
def decide(s, c):
    m = s.get('memory') or {}
    phase, now = m.get('p', 'idle'), s['now']
    age = now - m.get('t', now)
    levels = sorted(int(x) for x in c['levels'].split(','))
    minimum = levels[0]
    cap = max(x for x in levels if x <= c['cap'])
    house = max(s['load'] - s['ev'], 0)
    voltage = s['voltage']
    reserve = c['reserve'] if s['soc'] < c['reserve_release'] else 0
    estimate = min(s['light'] * c['factor'], c['pv_model_max'])
    allowance = max(estimate, s['pv']) - house - reserve - c['margin']
    neutral = s['grid'] <= c['grid_limit'] and s['battery'] >= -c['battery_limit']
    safe = s['valid'] and s['day'] and s['light'] >= c['min_light'] and s['soc'] > c['floor'] and neutral and not s['fault'] and phase != 'fault' and s['work'] != c['free_state']
    command, amps, reason = 'hold', 0, 'Waiting for solar'
    def lower_for(budget):
        lower = [x for x in levels if x < s['command'] and x <= budget]
        return ('reduce', max(lower)) if lower else ('pause', 0)
    if not s['enabled']:
        reason = 'Solar mode off'
    elif phase == 'fault':
        command, reason = 'fault', 'Fault latched; disable and enable solar mode to reset'
    elif s['fault']:
        command, reason = 'fault', 'Charger fault'
    elif not s['valid']:
        command, reason = 'pause', 'Missing, stale or invalid essential readings'
    elif not s['day'] or s['light'] < c['min_light']:
        command, reason = 'pause', 'Waiting for daylight'
    elif s['soc'] <= c['floor']:
        command, reason = 'pause', 'Protecting home battery reserve'
    elif s['work'] == c['free_state']:
        command, reason = 'complete', 'Vehicle unplugged'
    elif s['on'] and s['ev_age'] > c['feedback_max'] and phase not in ('start', 'adjust', 'probe'):
        command, reason = 'fault', 'Charger power feedback stale'
    elif s['on'] and not neutral:
        deficit = max(s['grid'], 0) + max(-s['battery'], 0)
        command, amps = lower_for(min(s['command'], s['amps']) - (deficit + c['margin']) / voltage)
        reason = 'Reducing grid or battery draw'
    elif s['on'] and s['command'] > cap:
        command, amps, reason = 'reduce', cap, 'Applying current cap'
    elif phase in ('start', 'adjust', 'probe') and s['on']:
        if age > c['ack_timeout'] and s['command'] != m.get('a', 0):
            command, reason = 'fault', 'Current command not acknowledged'
        elif age > c['feedback_max']:
            command, reason = 'fault', 'No confirmed charger response'
        elif s['ev_time'] > m['t'] + c['fresh_after'] and s['amps'] > m.get('a', 0) + c['amp_tolerance']:
            command, reason = 'fault', 'Car exceeds requested current'
        elif age < c['settle'] or s['ev_time'] <= m['t'] + c['fresh_after']:
            reason = 'Waiting for fresh charger response'
        elif s['ev'] < c['idle_power']:
            command, reason = 'complete', 'Vehicle not accepting charge'
        elif phase == 'probe':
            rise = s['ev'] - m.get('e', s['ev'])
            house_change = house - m.get('h', house)
            support = s['pv'] - m.get('v', s['pv']) + m.get('b', s['battery']) - s['battery']
            step = (m.get('a', 0) - m.get('o', 0)) * voltage
            if rise >= c['rise_fraction'] * step and abs(house_change) <= c['house_tolerance'] and support >= rise + house_change - c['solar_tolerance'] and neutral:
                command, reason = 'accept', 'Solar increase confirmed'
            else:
                command, amps, reason = 'reduce', m.get('o', minimum), 'Probe inconclusive; returning to prior current'
        else:
            command, reason = 'accept', 'Charging current confirmed'
    elif s['on']:
        if phase != 'run':
            command, reason = 'pause', 'Taking control; restart at minimum current'
        elif s['command'] != m.get('a', 0):
            command, reason = 'fault', 'Unexpected charger setting change'
        elif s['work'] in (c['end_state'], c['pause_state']) and s['ev'] < c['idle_power']:
            command, reason = 'complete', 'Charging session finished'
        elif s['amps'] > s['command'] + c['amp_tolerance']:
            command, reason = 'fault', 'Car exceeds requested current'
        elif s['battery'] < reserve - c['reserve_tolerance'] and reserve > 0:
            command, amps = lower_for(s['command'] - 1)
            reason = 'Preserving battery charging power'
        elif s['command'] >= cap:
            reason = 'Charging at configured maximum'
        else:
            next_level = min(x for x in levels if x > s['command'])
            interval = c['fast_probe'] if allowance >= next_level * voltage else c['slow_probe']
            if age >= interval and neutral and s['ev_age'] <= c['probe_fresh'] and s['pv'] > c['probe_pv']:
                command, amps, reason = 'increase', next_level, 'Testing unused solar capacity'
            else:
                reason = 'Charging; waiting before next solar test'
    else:
        connected = s['work'] in (c['insert_state'], c['wait_state'], c['pause_state']) or s['session']
        if phase in ('run', 'start', 'adjust', 'probe'):
            command, reason = 'complete', 'Charger stopped; session ended'
        elif not connected:
            reason = 'Waiting for vehicle connection'
        elif s['soc'] < c['floor'] + c['soc_hysteresis']:
            command, reason = 'wait', 'Waiting for battery reserve recovery'
        elif not neutral:
            command, reason = 'wait', 'Waiting for grid and battery draw to clear'
        elif phase == 'cooldown' and age < c['cooldown']:
            reason = 'Cooling down before restart'
        elif allowance >= minimum * voltage or (s['light'] >= c['start_light'] and s['pv'] >= c['start_pv']):
            if phase != 'candidate':
                command, reason = 'candidate', 'Checking solar remains available'
            elif age >= c['start_dwell']:
                command, amps, reason = 'start', minimum, 'Starting minimum-current solar test'
            else:
                reason = 'Checking solar remains available'
        else:
            command, reason = 'wait', 'Waiting for enough sunlight to start'
    memory = dict(m)
    if command == 'fault':
        memory = dict(p='fault', t=now, a=0)
    elif command == 'pause':
        memory = dict(p='cooldown', t=now if s['on'] or phase != 'cooldown' else m.get('t', now), a=0)
    elif command == 'complete':
        memory = dict(p='idle', t=now, a=0)
    elif command == 'wait' and phase != 'cooldown':
        memory = dict(p='idle', t=now, a=0)
    elif command == 'candidate':
        memory = dict(p='candidate', t=now, a=0)
    elif command in ('start', 'reduce', 'increase'):
        memory = dict(p='probe' if command == 'increase' else 'start' if command == 'start' else 'adjust', t=now, a=amps, o=s['command'], e=round(s['ev']), v=round(s['pv']), h=round(house), b=round(s['battery']))
    elif command == 'accept':
        memory = dict(p='run', t=now, a=s['command'])
    return dict(c=command, a=amps, r=reason, m=memory, z=safe, w=round(estimate))
