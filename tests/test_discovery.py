# 공식 목록의 관련 후보와 외부 주소 차단 및 실패 구분을 검증한다.
import unittest
from holy_naju.discovery import catalog_candidates


class DiscoveryTests(unittest.TestCase):
    def test_candidates_without_database(self):
        path = 'documents/example_en.html'
        title = 'Mater Populi Fidelis - Doctrinal Note on Some Marian Titles'
        raw = f'<a href="{path}">{title}</a><a href="{path}">English</a>'
        for query in ['공동 구속자', '공동구속자', 'Co-redemptrix', 'Mater Populi Fidelis']:
            hits = catalog_candidates(raw, query)
            self.assertEqual(len(hits), 1)
            self.assertEqual(hits[0]['verification_status'], 'body_unverified')
        self.assertEqual(catalog_candidates(raw, 'unrelated'), [])

    def test_invalid_pages_urls_and_queries(self):
        for raw in ['<html>Access denied</html>', '<a href="https://evil.test/example_en.html">Mater</a>',
                    '<a href="https://www.vatican.va@evil.test/example_en.html">Mater</a>']:
            with self.assertRaises(ValueError):
                catalog_candidates(raw, 'Mater')
        for query in ['', None, 'a\x00b', 'a'*201]:
            with self.assertRaises(ValueError):
                catalog_candidates('', query)
