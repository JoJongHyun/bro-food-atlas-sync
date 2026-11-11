#!/usr/bin/env python3
"""Match a Naver Map accessibility extraction to exactly one site SID.

Reads an exported /api/data JSON snapshot. Never fetches or writes the site.
"""
import argparse
import hashlib
import json
import re
import sys
import unicodedata
from pathlib import Path


def normalized(value):
    if not isinstance(value, str):
        return ''
    value = unicodedata.normalize('NFKC', value).casefold()
    # Do not strip branch names, digits or address components.
    return re.sub(r'[\s,().-]+', '', value)


def pick_string(place, fields):
    for key in fields:
        val = place.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ''


def reconcile(extraction, site):
    if not isinstance(site, dict) or not isinstance(site.get('places'), list):
        return {'status': 'invalid_site_snapshot', 'reason': 'places must be a list'}
    if not extraction.get('scheduleComplete') or len(extraction.get('weeklyHours') or {}) != 7:
        return {'status': 'pending', 'reason': 'incomplete_weekly_schedule'}
    name = normalized(extraction.get('name'))
    address = normalized(extraction.get('address'))
    if not name or not address:
        return {'status': 'pending', 'reason': 'missing_name_or_address'}

    candidates = []
    for place in site['places']:
        if not isinstance(place, dict):
            continue
        stored_name = pick_string(place, ('name', 'title', 'businessName'))
        stored_address = pick_string(place, ('roadAddress', 'road_address', 'address'))
        if normalized(stored_name) != name or normalized(stored_address) != address:
            continue
        sid = pick_string(place, ('sid', 'naverSid', 'naverPlaceId'))
        # Generic id can be an internal site identifier; never infer SID from it.
        if not sid.isdigit():
            return {'status': 'pending', 'reason': 'matched_place_has_no_valid_sid'}
        candidates.append((sid, stored_name, stored_address))

    if not candidates:
        return {'status': 'pending', 'reason': 'no_exact_name_address_match'}
    if len(candidates) != 1 or len({sid for sid, _, _ in candidates}) != 1:
        return {'status': 'pending', 'reason': 'ambiguous_match', 'candidates': len(candidates)}
    sid, business, site_address = candidates[0]
    claimed_sid = extraction.get('sid')
    if claimed_sid and str(claimed_sid) != sid:
        return {'status': 'pending', 'reason': 'sid_conflict'}

    rules = extraction['weeklyHours']
    fingerprint = hashlib.sha256(json.dumps(
        {'sid': sid, 'rules': rules}, ensure_ascii=False, sort_keys=True,
        separators=(',', ':')
    ).encode('utf-8')).hexdigest()
    return {
        'status': 'candidate_only',
        'sid': sid,
        'name': business,
        'address': site_address,
        'matchBasis': 'exact_normalized_name_and_address',
        'scheduleComplete': True,
        'weeklyHours': rules,
        'breakTimes': extraction.get('breakTimes'),
        'lastOrder': extraction.get('lastOrder'),
        'source': 'naver_map_accessibility_user_export',
        'fingerprint': fingerprint,
        'persistedToSite': False,
    }


def main():
    cli = argparse.ArgumentParser(description=__doc__)
    cli.add_argument('extracted_json', type=Path)
    cli.add_argument('site_api_snapshot_json', type=Path)
    cli.add_argument('--output', type=Path)
    args = cli.parse_args()
    extracted = json.loads(args.extracted_json.read_text(encoding='utf-8'))
    site = json.loads(args.site_api_snapshot_json.read_text(encoding='utf-8'))
    result = reconcile(extracted, site)
    content = json.dumps(result, ensure_ascii=False, indent=2) + '\n'
    if args.output:
        args.output.write_text(content, encoding='utf-8')
    else:
        print(content)
    return 0 if result['status'] == 'candidate_only' else 2


if __name__ == '__main__':
    sys.exit(main())
