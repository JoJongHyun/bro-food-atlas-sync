import unittest
import sys
from pathlib import Path
from xml.sax.saxutils import quoteattr
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from parse_naver_layout import parse_layout


def layout(hours):
    return f'''<root xmlns:android="http://schemas.android.com/apk/res/android">
    <android.widget.TextView android:layout_y="200px" android:text="가게"/>
    <row><node android:text="주소"/><android.widget.Button android:text="강원 동해시 평원5길 8-5 1층"/></row>
    <row><node android:text="영업시간"/><android.widget.Button android:text={quoteattr(hours)}/></row></root>'''


class ParseLayoutTest(unittest.TestCase):
    def test_full_week_and_closed(self):
        result = parse_layout(layout('영업 종료 수 11:00 - 15:00 목 11:00 - 15:00 금 11:00 - 15:00 토 11:00 - 15:00 일 11:00 - 15:00 월 정기휴무 (매주 월요일) 화 11:00 - 15:00 접기'))
        self.assertTrue(result['scheduleComplete'])
        self.assertEqual(result['weeklyHours']['mon'], {'closed': True})
        self.assertEqual(result['weeklyHours']['sun']['open'], '11:00')

    def test_break_last_order_and_overnight(self):
        result = parse_layout(layout('월 9:00 - 18:00 14:00 - 15:00 브레이크타임 17:30 라스트오더 화 17:00 - 다음 날 02:00 수 정기휴무 목 정기휴무 금 정기휴무 토 정기휴무 일 정기휴무 접기'))
        self.assertTrue(result['scheduleComplete'])
        self.assertEqual(result['breakTimes']['mon'], ['14:00', '15:00'])
        self.assertEqual(result['lastOrder']['mon'], '17:30')
        self.assertTrue(result['weeklyHours']['tue']['closeNextDay'])
        self.assertEqual(result['weeklyHours']['mon']['open'], '09:00')

    def test_monthly_closure_must_not_become_weekly(self):
        result = parse_layout(layout('월 정기휴무 (매달 1번째 월요일) 화 11:00 - 15:00 수 11:00 - 15:00 목 11:00 - 15:00 금 11:00 - 15:00 토 11:00 - 15:00 일 11:00 - 15:00'))
        self.assertFalse(result['scheduleComplete'])
        self.assertEqual(result['reason'], 'unsupported_conditional_closure')

    def test_unknown_hours_are_rejected(self):
        result = parse_layout(layout('월 11:00 - 15:00 브레이크타임 화 11:00 - 15:00'))
        self.assertFalse(result['scheduleComplete'])
        self.assertEqual(result['reason'], 'unsupported_hours_details')

    def test_bad_time_rejected(self):
        result = parse_layout(layout('월 11:00 - 25:30 화 11:00 - 15:00'))
        self.assertEqual(result['reason'], 'invalid_time')


if __name__ == '__main__':
    unittest.main()
