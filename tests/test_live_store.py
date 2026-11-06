# 실시간 결과만 보관하며 중복·원문 변경·이전 근거·장애 상태를 보존하는지 검증한다.
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import Mock, patch

from holy_naju.discovery import CATALOG_URL
from holy_naju.live_store import get_live_run, search_and_store
from holy_naju.public_fetch import CollectionBlocked
from holy_naju.storage import Library

URL = 'https://www.vatican.va/roman_curia/congregations/cfaith/documents/sample_en.html'
OTHER = 'https://www.vatican.va/roman_curia/congregations/cfaith/documents/other_en.html'


class LiveStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.library = Library(Path(self.temp.name) / 'library')
        self.addCleanup(self.library.db.close)
        self.body = self.html('Co-redemptrix is discussed, not automatically endorsed.')
        self.client = Mock()
        self.client.fetch.side_effect = self.fetch

    def html(self, text):
        return ('<html><title>Example document</title><body><div class="testo"><p>'
                + 'Source context. '*10 + text + '</p></div></body></html>').encode()

    def fetch(self, url, **kwargs):
        if url == CATALOG_URL:
            return f'<a href="{URL}">Some Marian Titles</a><a href="{OTHER}">More Marian Titles</a>'.encode()
        if url == URL:
            return self.body
        if url == OTHER:
            return self.html('An unrelated subject without the requested term.')
        return json.dumps({'response': {'numFound': 0, 'docs': []}}).encode()

    def count(self, table):
        return self.library.db.execute(f'SELECT count(*) FROM {table}').fetchone()[0]

    def test_only_matched_document_stored_and_reused_but_new_online_run(self):
        first = search_and_store(self.library, '공동 구속자', self.client)
        self.assertEqual(self.count('assets'), 1)
        self.assertEqual(self.count('document_versions'), 1)
        self.assertEqual(len(first['results']), 2)
        self.assertEqual(first['results'][1]['verification_status'], 'no_match')
        self.assertNotIn('version_id', first['results'][1])
        evidence = first['results'][0]['stored_evidence'][0]
        text = self.library.db.execute('SELECT text FROM passages WHERE id=?', (evidence['passage_id'],)).fetchone()[0]
        self.assertEqual(text[evidence['start']:evidence['end']], evidence['excerpt'])
        self.client.reset_mock()
        second = search_and_store(self.library, '공동 구속자', self.client)
        self.assertNotEqual(first['id'], second['id'])
        self.assertEqual(self.client.fetch.call_count, 4)
        self.assertEqual(self.count('assets'), 1)
        self.assertEqual(first['results'][0]['version_id'], second['results'][0]['version_id'])
        with patch('holy_naju.live_store.live_search', side_effect=AssertionError('network forbidden')):
            self.assertEqual(get_live_run(self.library, first['id']), first)
        self.assertTrue(self.library.check()['ok'])

    def test_changed_document_keeps_old_snapshot_and_constraints(self):
        first = search_and_store(self.library, '공동구속자', self.client)
        self.body = self.html('A changed explanation of Co-redemptrix.')
        second = search_and_store(self.library, '공동구속자', self.client)
        self.assertNotEqual(first['results'][0]['version_id'], second['results'][0]['version_id'])
        self.assertEqual(get_live_run(self.library, first['id']), first)
        self.assertEqual(self.count('assets'), 2)
        with self.assertRaises(sqlite3.IntegrityError):
            with self.library.db:
                self.library.db.execute('UPDATE live_search_evidence SET passage_id=?', ('missing',))
        self.assertTrue(self.library.check()['ok'])

    def test_block_and_storage_failure_are_not_successful_empty_results(self):
        self.client.fetch.side_effect = CollectionBlocked('http_403')
        with self.assertRaises(CollectionBlocked):
            search_and_store(self.library, '공동 구속자', self.client)
        self.assertEqual(self.library.db.execute('SELECT status FROM live_search_runs').fetchone()[0], 'failed')
        self.assertEqual(self.count('assets'), 0)
        self.client.fetch.side_effect = self.fetch
        with patch.object(self.library, 'import_file', side_effect=OSError('disk full')):
            result = search_and_store(self.library, '공동 구속자', self.client)
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['results'][0]['verification_status'], 'failed')
        self.assertEqual(self.count('live_search_evidence'), 0)
        self.assertEqual(self.count('assets'), 0)

    def test_v4_upgrade_preserves_existing_document(self):
        root = Path(self.temp.name) / 'legacy'
        root.mkdir()
        db = sqlite3.connect(root / 'library.sqlite3')
        for name in ['001_documents.sql', '002_search.sql', '003_local_models.sql', '004_collections.sql']:
            db.executescript(Path('holy_naju/migrations', name).read_text(encoding='utf-8'))
        db.execute("INSERT INTO documents(id,title,created_at) VALUES ('old','Preserved','2026')")
        db.commit()
        db.close()
        with Library(root) as migrated:
            self.assertEqual(migrated.db.execute('PRAGMA user_version').fetchone()[0], 5)
            self.assertEqual(migrated.db.execute('SELECT title FROM documents').fetchone()[0], 'Preserved')
            self.assertTrue(migrated.check()['ok'])
