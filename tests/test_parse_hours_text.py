import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from parse_hours_text import parse_hours_text


class CapturedTextTest(unittest.TestCase):
    def test_actual_captured_week(self):
        text = '영업 종료11시 0분에 영업 시작 수 11:00 - 15:00 목 11:00 - 15:00 금 11:00 - 15:00 토 11:00 - 15:00 일 11:00 - 15:00 월 정기휴무 (매주 월요일) 화 11:00 - 15:00 접기'
        result = parse_hours_text(text)
        self.assertTrue(result['scheduleComplete'])
        self.assertFalse(result['identityVerified'])
        self.assertIsNone(result['sid'])
        self.assertEqual(result['weeklyHours']['mon'], {'closed': True})
        self.assertEqual(result['weeklyHours']['sun']['close'], '15:00')

    def test_partial_or_ambiguous_is_not_complete(self):
        for text in ('월 11:00 - 15:00', '월 정기휴무 (매달 1번째 월요일)'):
            self.assertFalse(parse_hours_text(text)['scheduleComplete'])

    def test_reject_empty_and_oversized(self):
        for text in ('', 'a' * 10001):
            with self.assertRaises(ValueError):
                parse_hours_text(text)


if __name__ == '__main__':
    unittest.main()
