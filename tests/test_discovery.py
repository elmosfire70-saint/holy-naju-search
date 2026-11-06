# 공식 목록의 관련 후보와 외부 주소 차단 및 실패 구분을 검증한다.
import unittest
import json
from unittest.mock import Mock
from holy_naju.discovery import CATALOG_URL, catalog_candidates, document_url, live_search, search_candidates
from holy_naju.public_fetch import CollectionBlocked


class DiscoveryTests(unittest.TestCase):
    def test_live_search_missing_target_uses_catalog_and_exact_evidence(self):
        url = 'https://www.vatican.va/roman_curia/congregations/cfaith/documents/example_en.html'
        listing = f'<a href="{url}">Note on Marian Titles</a>'.encode()
        body = ('<html><title>Example</title><body><div class="testo"><p>22. '
                + 'Context matters. '*10 + 'Co-redemptrix is discussed here.</p></div></body></html>').encode()
        client = Mock()
        client.fetch.side_effect = [json.dumps({'response': {'numFound': 0, 'docs': []}}).encode(), listing, body]
        result = live_search('공동 구속자', client)
        hit = result['results'][0]
        self.assertEqual(hit['verification_status'], 'matched')
        evidence = hit['evidence'][0]
        start, end = evidence['ranges'][0]
        self.assertEqual(evidence['text'][start:end], 'Co-redemptrix')
        self.assertIn('22.', evidence['text'])
        self.assertEqual(client.fetch.call_args_list[1].args, (CATALOG_URL,))
        self.assertEqual(result['remote_total'], 0)
        self.assertFalse(result['complete_coverage'])

    def test_failure_not_empty_and_block_stops_requests(self):
        client = Mock()
        client.fetch.side_effect = OSError('offline')
        self.assertEqual(live_search('Mater', client)['status'], 'failed')
        client.reset_mock()
        client.fetch.side_effect = CollectionBlocked('http_403')
        with self.assertRaises(CollectionBlocked):
            live_search('Mater', client)
        self.assertEqual(client.fetch.call_count, 1)
        client.reset_mock()
        with self.assertRaises(ValueError):
            live_search('', client)
        client.fetch.assert_not_called()

    def test_json_shape_and_result_url_boundaries(self):
        for payload in [{}, {'response': {'docs': [], 'numFound': -1}},
                        {'response': {'docs': {}, 'numFound': 0}}]:
            with self.assertRaises(ValueError):
                search_candidates(payload, 'request')
        for url in ['https://evil.test/documents/x.html', 'https://www.vatican.va@evil.test/documents/x.html',
                    'https://www.vatican.va/content/documents/%2e%2e/x.html',
                    'http://www.vatican.va/content/documents/x.html', '/bin/private.html']:
            with self.assertRaises(ValueError):
                document_url(url)

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
