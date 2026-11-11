"""Extract weekly hours from a saved Naver Place HTML response, without fetching it."""
import json
import re
from html.parser import HTMLParser


class Metadata(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta' and (attrs.get('property') == 'og:url' or attrs.get('id') == 'og:url'):
            self.urls.append(attrs.get('content', ''))


def extract(html, expected_sid):
    sid = str(expected_sid)
    if not re.fullmatch(r'\d{1,20}', sid):
        raise ValueError('invalid SID')
    metadata = Metadata()
    metadata.feed(html)
    if not any(re.search(r'/restaurant/' + re.escape(sid) + r'/home(?:[?#]|$)', u) for u in metadata.urls):
        raise ValueError('page identity does not match SID')
    candidates = []
    for match in re.finditer(r'"newBusinessHours"\s*:\s*', html):
        try:
            value, _ = json.JSONDecoder().raw_decode(html, match.end())
        except ValueError:
            continue
        if isinstance(value, list) and value:
            candidates.append(value)
    if len(candidates) != 1 or len(candidates[0]) != 1:
        raise ValueError('missing or ambiguous opening hours')
    record = candidates[0][0]
    rows = record.get('businessHours') if isinstance(record, dict) else None
    if not isinstance(rows, list):
        raise ValueError('missing daily hours')
    days = [row.get('day') for row in rows if isinstance(row, dict)]
    if len(days) != 7 or set(days) != set('월화수목금토일'):
        raise ValueError('incomplete or ambiguous weekdays')
    return {'sid': sid, 'businessHours': rows,
            'businessStatusDescription': record.get('businessStatusDescription'),
            'comingIrregularClosedDays': record.get('comingIrregularClosedDays'),
            'comingRegularClosedDays': record.get('comingRegularClosedDays'),
            'freeText': record.get('freeText')}
