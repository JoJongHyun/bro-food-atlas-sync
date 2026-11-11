import unittest
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from candidate_to_site_hours import convert_candidate
from parse_hours_text import parse_hours_text

TEXT = '영업 종료11시 0분에 영업 시작 수 11:00 - 15:00 목 11:00 - 15:00 금 11:00 - 15:00 토 11:00 - 15:00 일 11:00 - 15:00 월 정기휴무 (매주 월요일) 화 11:00 - 15:00 접기'

class CandidateTest(unittest.TestCase):
    def test_real_observation_to_site_rules(self):
        result = convert_candidate(parse_hours_text(TEXT), '2026-11-11T22:18:09+09:00')
        self.assertFalse(result['published'])
        self.assertFalse(result['identityVerified'])
        self.assertEqual(len(result['hours']['rules']), 7)
        self.assertIn({'days': [1], 'closed': True}, result['hours']['rules'])
        self.assertIn({'days': [2], 'opens': '11:00', 'closes': '15:00'}, result['hours']['rules'])

    def test_reject_incomplete(self):
        with self.assertRaises(ValueError):
            convert_candidate(parse_hours_text('월 11:00 - 15:00'), '2026-11-11T22:18:09+09:00')

    def test_reject_naive_timestamp(self):
        with self.assertRaises(ValueError):
            convert_candidate(parse_hours_text(TEXT), '2026-11-11T22:18:09')

if __name__ == '__main__':
    unittest.main()
