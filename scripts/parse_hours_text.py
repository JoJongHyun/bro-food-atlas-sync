#!/usr/bin/env python3
"""Convert one manually captured Automate hours_text value to candidate JSON.

This program neither opens Naver Map nor updates any site. The result has no
verified place identity and must not be automatically written to production.
"""
import json
import sys
import xml.etree.ElementTree as ET
from parse_naver_layout import A, parse_layout


def parse_hours_text(text):
    if not isinstance(text, str) or not text.strip() or len(text) > 10000:
        raise ValueError('invalid_or_empty_hours_text')
    # Build only the elements the existing conservative parser needs. Escape
    # is handled by ElementTree; arbitrary UI text cannot inject XML nodes.
    root = ET.Element('root')
    row = ET.SubElement(root, 'row')
    label = ET.SubElement(row, 'node')
    label.set(A + 'text', '영업시간')
    button = ET.SubElement(row, 'android.widget.Button')
    button.set(A + 'text', text)
    parsed = parse_layout(ET.tostring(root, encoding='unicode'))
    parsed['source'] = 'manually_captured_screen_text'
    parsed['identityVerified'] = False
    parsed['verification'] = 'candidate_not_written_to_site'
    return parsed


def main():
    try:
        candidate = parse_hours_text(sys.stdin.read(10001))
        print(json.dumps(candidate, ensure_ascii=False, indent=2))
        return 0 if candidate['scheduleComplete'] else 2
    except ValueError as error:
        print(json.dumps({'error': str(error)}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
