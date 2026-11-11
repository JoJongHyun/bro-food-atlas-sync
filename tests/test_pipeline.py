"""Offline synthetic test fixtures only: never commit real accessibility XML."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'scripts'))
from parse_naver_layout import parse_layout
from match_site_place import reconcile

ATTR = 'xmlns:android="http://schemas.android.com/apk/res/android"'


def layout(hours):
    return (f'<android.widget.FrameLayout {ATTR}>'
            '<android.widget.TextView android:layout_y="182px" android:text="소복소복"/>'
            '<android.view.View>'
            '<android.view.View android:text="주소"/>'
            '<android.widget.Button android:text="강원 동해시 평원5길 8-5 1층"/>'
            '</android.view.View>'
            '<android.view.View><android.view.View android:text="영업시간"/>'
            f'<android.widget.Button android:text="{hours}"/>'
            '</android.view.View></android.widget.FrameLayout>')


class LayoutTests(unittest.TestCase):
    def test_weekly(self):
        text = ('영업 종료 수 11:00 - 15:00 목 11:00 - 15:00 금 11:00 - 15:00 '
                '토 11:00 - 15:00 일 11:00 - 15:00 월 정기휴무 (매주 월요일) '
                '화 11:00 - 15:00 접기')
        res = parse_layout(layout(text))
        self.assertTrue(res['scheduleComplete'])
        self.assertTrue(res['weeklyHours']['mon']['closed'])
        self.assertEqual(res['weeklyHours']['sun']['close'], '15:00')
        self.assertEqual(res['name'], '소복소복')

    def test_partial_does_not_count(self):
        res = parse_layout(layout('월 11:00 - 20:00 화 11:00 - 20:00'))
        self.assertFalse(res['scheduleComplete'])

    def test_next_day(self):
        text = ' '.join(f'{d} 17:00 - 다음 날 02:00' for d in '월화수목금토일')
        res = parse_layout(layout(text))
        self.assertTrue(res['scheduleComplete'])
        self.assertTrue(res['weeklyHours']['sat']['closeNextDay'])


class MatchTests(unittest.TestCase):
    def setUp(self):
        self.valid = parse_layout(layout(' '.join(f'{d} 11:00 - 15:00' for d in '월화수목금토일'))
        self.snapshot = {'places': [{'sid': '123456789', 'name': '소복소복',
                                     'roadAddress': '강원 동해시 평원5길 8-5 1층'}]}

    def test_unique_match(self):
        res = reconcile(self.valid, self.snapshot)
        self.assertEqual(res['status'], 'candidate_only')
        self.assertEqual(res['sid'], '123456789')
        self.assertFalse(res['persistedToSite'])
        self.assertEqual(res['fingerprint'], reconcile(self.valid, self.snapshot)['fingerprint'])

    def test_same_name_different_address(self):
        snapshot = {'places': [{'sid': '99', 'name': '소복소복', 'roadAddress': '서울 중구 1'}]}
        self.assertEqual(reconcile(self.valid, snapshot)['reason'], 'no_exact_name_address_match')

    def test_duplicate_fails_closed(self):
        snapshot = {'places': self.snapshot['places'] * 2}
        self.assertEqual(reconcile(self.valid, snapshot)['reason'], 'ambiguous_match')

    def test_no_sid_fails_closed(self):
        snapshot = {'places': [{'id': '12345', 'name': '소복소복', 'address': '강원 동해시 평원5길 8-5 1층'}]}
        self.assertEqual(reconcile(self.valid, snapshot)['reason'], 'matched_place_has_no_valid_sid')

    def test_claimed_sid_conflict(self):
        self.valid['sid'] = '999999'
        self.assertEqual(reconcile(self.valid, self.snapshot)['reason'], 'sid_conflict')

    def test_incomplete(self):
        self.valid['scheduleComplete'] = False
        self.assertEqual(reconcile(self.valid, self.snapshot)['reason'], 'incomplete_weekly_schedule')


if __name__ == '__main__':
    unittest.main()
