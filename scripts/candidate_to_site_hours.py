#!/usr/bin/env python3
"""Convert an unverified extracted candidate to a site-format preview only."""
from datetime import datetime

DAY = {'sun': 0, 'mon': 1, 'tue': 2, 'wed': 3, 'thu': 4, 'fri': 5, 'sat': 6}


def _minutes(value):
    if not isinstance(value, str) or len(value) != 5 or value[2] != ':':
        raise ValueError('invalid_time')
    try:
        h, m = int(value[:2]), int(value[3:])
    except ValueError:
        raise ValueError('invalid_time')
    if not 0 <= h < 24 or not 0 <= m < 60:
        raise ValueError('invalid_time')
    return h * 60 + m


def convert_candidate(candidate, observed_at):
    """Return a preview, never an identity-verified or published record."""
    observed = datetime.fromisoformat(observed_at.replace('Z', '+00:00'))
    if observed.tzinfo is None:
        raise ValueError('timestamp_requires_timezone')
    weekly = candidate.get('weeklyHours')
    if not candidate.get('scheduleComplete') or not isinstance(weekly, dict) or set(weekly) != set(DAY):
        raise ValueError('incomplete_schedule')
    breaks = candidate.get('breakTimes') or {}
    last_orders = candidate.get('lastOrder') or {}
    if set(breaks) - set(DAY) or set(last_orders) - set(DAY):
        raise ValueError('invalid_day')
    rules = []
    for day, num in DAY.items():
        item = weekly[day]
        if item.get('closed') is True:
            if day in breaks or day in last_orders:
                raise ValueError('conflicting_closure')
            rules.append({'days': [num], 'closed': True})
            continue
        if item.get('closed') is not False:
            raise ValueError('unknown_day')
        start, end = _minutes(item.get('open')), _minutes(item.get('close'))
        if start == end:
            raise ValueError('ambiguous_equal_times')
        overnight = item.get('closeNextDay') is True
        if overnight != (end < start):
            raise ValueError('unsupported_overnight_range')
        order = last_orders.get(day)
        if order is not None:
            last = _minutes(order)
            if (last + (1440 if overnight and last < start else 0)) not in range(start, end + (1440 if overnight else 0) + 1):
                raise ValueError('invalid_last_order')
        br = breaks.get(day)
        if br is not None:
            if overnight or not isinstance(br, list) or len(br) != 2:
                raise ValueError('unsupported_break')
            b1, b2 = map(_minutes, br)
            if not start < b1 < b2 < end:
                raise ValueError('invalid_break')
            rules.append({'days': [num], 'opens': item['open'], 'closes': br[0]})
            last_rule = {'days': [num], 'opens': br[1], 'closes': item['close']}
        else:
            last_rule = {'days': [num], 'opens': item['open'], 'closes': item['close']}
        if order:
            last_rule['lastOrder'] = order
        rules.append(last_rule)
    return {'hours': {'rules': rules, 'source': 'manually_captured_screen_text', 'verifiedAt': observed.isoformat()},
            'identityVerified': False, 'published': False}
