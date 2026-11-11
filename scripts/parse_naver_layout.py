#!/usr/bin/env python3
"""Parse user-exported Naver Map accessibility XML; no network calls or site writes."""
import argparse
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path

A = '{http://schemas.android.com/apk/res/android}'
DAYS = {'월':'mon','화':'tue','수':'wed','목':'thu','금':'fri','토':'sat','일':'sun'}
RULE = re.compile(r'(?<![가-힣])(?P<day>[월화수목금토일])\s+(?:(?P<start>\d{1,2}:\d{2})\s*-\s*(?P<next>다음\s*날\s*)?(?P<end>\d{1,2}:\d{2})|(?P<closed>정기휴무|휴무))')
REGION = re.compile(r'^(서울|부산|대구|인천|광주|대전|울산|세종|경기|강원|충북|충남|전북|전남|경북|경남|제주)\b')

def parse_layout(xml_text):
    # Automate exports may contain invalid UTF-16 surrogate numeric references
    # in review emojis. Ignore those references without discarding hours fields.
    def clean_reference(m):
        value = int(m.group(1), 16) if m.group(1) else int(m.group(2))
        return '' if 0xD800 <= value <= 0xDFFF else m.group(0)
    xml_text = re.sub(r'&#(?:x([0-9A-Fa-f]+)|(\d+));', clean_reference, xml_text)
    root = ET.fromstring(xml_text)
    parents = {child: parent for parent in root.iter() for child in parent}
    def text(el):
        return el.get(A+'text', '')
    def section_buttons(label):
        for node in root.iter():
            if text(node) == label and node in parents:
                for child in parents[node].iter('android.widget.Button'):
                    if text(child):
                        yield text(child)

    schedules = list(section_buttons('영업시간'))
    addresses = [v for v in section_buttons('주소') if REGION.match(v)]
    titles = []
    for node in root.iter('android.widget.TextView'):
        value = text(node)
        try:
            y = int(node.get(A+'layout_y', '99999').removesuffix('px'))
        except ValueError:
            continue
        if 128 <= y < 340 and 1 < len(value) < 90 and not value.startswith('영업'):
            titles.append(value)

    result = {'name': titles[0] if titles else None,
              'address': addresses[0] if addresses else None,
              'sid': None,
              'source': 'user_supplied_naver_map_accessibility_xml',
              'scheduleComplete': False, 'weeklyHours': {},
              'breakTimes': None, 'lastOrder': None,
              'verification': 'not_written_to_site'}
    if not schedules:
        result['reason'] = 'no_opening_hours_control_found'
        return result

    raw = schedules[0]
    current = re.search(r'영업\s*(중|종료|전)|브레이크\s*타임', raw)
    result['displayedStatus'] = current.group(0) if current else None
    for match in RULE.finditer(raw):
        day = DAYS[match['day']]
        if day in result['weeklyHours']:
            result['reason'] = 'duplicate_weekday'
            return result
        if match['closed']:
            result['weeklyHours'][day] = {'closed': True}
            continue
        start, end = match['start'], match['end']
        for hhmm in (start, end):
            h, m = map(int, hhmm.split(':'))
            if h >= 24 or m >= 60:
                result['reason'] = 'invalid_time'
                return result
        result['weeklyHours'][day] = {
            'closed': False, 'open': start, 'close': end,
            'closeNextDay': bool(match['next']) or end <= start}
    result['scheduleComplete'] = len(result['weeklyHours']) == 7
    if not result['scheduleComplete']:
        result['reason'] = 'fewer_than_seven_explicit_weekdays'
    return result

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('xml_file', type=Path)
    parser.add_argument('--sid', help='Existing site SID confirmed by separate matching')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = parse_layout(args.xml_file.read_text(encoding='utf-8'))
    if args.sid:
        if not args.sid.isdigit():
            parser.error('SID must be numeric')
        result['sid'] = args.sid
    output = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(output, encoding='utf-8')
    else:
        print(output)

if __name__ == '__main__':
    main()
