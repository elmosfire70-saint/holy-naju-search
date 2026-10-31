# 로컬 모델 경계와 임베딩·번역 캐시 및 모델 실패 시 근거 검색 보존을 검증한다.
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from holy_naju.local_models import LocalModelError, OllamaClient
from holy_naju.search import get_run, search
from holy_naju.storage import Library
from holy_naju.translation import get_translation, translate_passage


class FakeClient:
    def __init__(self):
        self.digest = "digest-1"
        self.embed_calls = 0
        self.translate_calls = 0
        self.available = True

    def profile(self, name, capability):
        if not self.available:
            raise LocalModelError("test_unavailable")
        return {"name": name, "digest": self.digest, "runtime_version": "test", "num_ctx": 4096}

    def embed(self, texts, profile):
        self.embed_calls += 1
        return [[1.0, 0.0] if "Eucharist" in t or "성체" in t else [0.0, 1.0] for t in texts]

    def translate(self, text, profile):
        self.translate_calls += 1
        return "51 성체와 교회에 관한 검증용 번역."


class LocalModelTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Library(self.root / "library")
        self.addCleanup(self.library.db.close)
        self.path = self.root / "document.txt"
        self.path.write_text("51 The Eucharist and the Church.\nPrayer brings hope.", encoding="utf-8")
        self.doc = self.library.import_file(self.path, language="en", title="Source")
        self.passage = self.library.get_version(self.doc["version_id"])["passages"][0]["id"]
        self.client = FakeClient()

    def test_hybrid_finds_foreign_passage_and_reuses_without_model_inference(self):
        first = search(self.library, "성체", retrieval="hybrid", client=self.client)
        self.assertEqual(first["retrieval"], "hybrid")
        self.assertEqual(first["hits"][0]["passage_id"], self.passage)
        calls = self.client.embed_calls
        again = search(self.library, "성체", retrieval="hybrid", client=self.client)
        self.assertTrue(again["reused"])
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(calls, self.client.embed_calls)
        refreshed = search(self.library, "성체", retrieval="hybrid", client=self.client, refresh=True)
        self.assertNotEqual(first["id"], refreshed["id"])
        self.assertEqual(calls, self.client.embed_calls)
        self.assertEqual(first["hits"][0]["highlight_ranges"], [])
        self.assertTrue(self.library.check()["ok"])

    def test_model_revision_and_source_revision_keep_old_runs(self):
        first = search(self.library, "성체", retrieval="hybrid", client=self.client)
        self.client.digest = "digest-2"
        changed = search(self.library, "성체", retrieval="hybrid", client=self.client)
        self.assertNotEqual(first["id"], changed["id"])
        self.assertEqual(get_run(self.library, first["id"])["model_profile"]["digest"], "digest-1")
        self.path.write_text("Another document about hope.", encoding="utf-8")
        self.library.import_file(self.path, edition_id=self.doc["edition_id"])
        updated = search(self.library, "성체", retrieval="hybrid", client=self.client)
        self.assertNotEqual(updated["index_generation_id"], first["index_generation_id"])
        self.assertEqual(get_run(self.library, first["id"])["hits"], first["hits"])

    def test_unavailable_model_and_invalid_vector_use_labeled_keyword_fallback(self):
        self.client.available = False
        result = search(self.library, "Eucharist", retrieval="hybrid", client=self.client)
        self.assertEqual(result["retrieval"], "keyword")
        self.assertTrue(result["hits"])
        self.assertEqual(result["diagnostics"]["semantic_status"], "unavailable")
        self.client.available = True
        with patch.object(self.client, "embed", return_value=[[0.0, 0.0], [0.0, 0.0]]):
            result = search(self.library, "Eucharist", retrieval="hybrid", client=self.client)
        self.assertEqual(result["retrieval"], "keyword")
        self.assertEqual(self.library.db.execute("SELECT count(*) FROM search_runs WHERE retrieval='hybrid'").fetchone()[0], 0)

    def test_filter_excludes_documents_before_semantic_ranking(self):
        result = search(self.library, "성체", source="naju", retrieval="hybrid", client=self.client)
        self.assertEqual(result["hits"], [])
        self.assertEqual(self.client.embed_calls, 0)

    def test_long_passage_context_limit_keeps_tail_evidence_and_original(self):
        path = self.root / 'long.txt'
        original = 'ordinary text. ' * 1500 + 'Eucharist tail evidence.'
        path.write_text(original, encoding='utf-8')
        document = self.library.import_file(path, language='en', title='Long source')
        passage = self.library.get_version(document['version_id'])['passages'][0]
        calls = []
        def limited_embed(texts, profile):
            calls.extend(texts)
            if any(len(text.encode('utf-8')) > 2048 for text in texts):
                raise LocalModelError('synthetic_context_length_exceeded')
            return [[1.0, 0.0] if 'Eucharist' in text or '성체' in text else [0.0, 1.0] for text in texts]
        with patch.object(self.client, 'embed', side_effect=limited_embed):
            result = search(self.library, '성체', retrieval='hybrid', client=self.client)
            self.assertEqual(result['retrieval'], 'hybrid')
            matches = [h for h in result['hits'] if h['passage_id'] == passage['id']]
            self.assertEqual(len(matches), 1)
            self.assertEqual(matches[0]['version_id'], document['version_id'])
            start, end = matches[0]['retrieval_signals']['semantic']['passage_range']
            self.assertIn('Eucharist tail evidence.', original[start:end])
            call_count = len(calls)
            again = search(self.library, '성체', retrieval='hybrid', client=self.client)
            self.assertEqual(result['id'], again['id'])
            self.assertEqual(len(calls), call_count)
        self.assertTrue(any('Eucharist tail evidence.' in text for text in calls))
        stored = self.library.db.execute('SELECT text FROM passages WHERE id=?', (passage['id'],)).fetchone()[0]
        self.assertEqual(stored, original)

    def test_segment_ranges_cover_unicode_and_long_title_without_gaps(self):
        from holy_naju.semantic import _segments
        for text in ('', '짧은 글', '제목🙂' * 900 + '\n' + '한글 e\u0301 Latin 끝🙂 ' * 600):
            covered = [False] * len(text)
            previous_end = 0
            for start, end, segment in _segments(text):
                self.assertEqual(text[start:end], segment)
                self.assertLessEqual(len(segment.encode('utf-8')), 2000)
                self.assertLessEqual(start, previous_end)
                self.assertGreater(end, previous_end)
                covered[start:end] = [True] * (end-start)
                previous_end = end
            self.assertTrue(all(covered))
            self.assertEqual(previous_end, len(text))

    def test_new_ranking_revision_invalidates_runs_but_reuses_same_input_vectors(self):
        with patch('holy_naju.semantic.HYBRID_REVISION', 'hybrid-rrf-1'):
            old = search(self.library, '성체', retrieval='hybrid', client=self.client)
        calls = self.client.embed_calls
        current = search(self.library, '성체', retrieval='hybrid', client=self.client)
        self.assertNotEqual(old['id'], current['id'])
        self.assertEqual(self.client.embed_calls, calls)
        self.assertEqual(get_run(self.library, old['id'])['hits'], old['hits'])
        self.assertTrue(search(self.library, '성체', retrieval='hybrid', client=self.client)['reused'])

    def test_translation_preserves_original_and_model_revision(self):
        first = translate_passage(self.library, self.passage, client=self.client)
        second = translate_passage(self.library, self.passage, client=self.client)
        self.assertTrue(second["reused"])
        self.assertEqual(self.client.translate_calls, 1)
        self.assertEqual(first["review_status"], "unreviewed")
        self.assertEqual(first["version_id"], self.doc["version_id"])
        self.client.digest = "digest-2"
        new = translate_passage(self.library, self.passage, client=self.client)
        self.assertNotEqual(first["id"], new["id"])
        saved = get_translation(self.library, first["id"])
        self.assertEqual(saved["model_profile"]["digest"], "digest-1")
        self.assertIn("Eucharist", saved["original"])

    def test_failed_translation_is_not_success_cache(self):
        with patch.object(self.client, "translate", side_effect=LocalModelError("test_failure")):
            with self.assertRaises(LocalModelError):
                translate_passage(self.library, self.passage, client=self.client)
        failed = self.library.db.execute("SELECT * FROM translations").fetchone()
        self.assertEqual(failed["status"], "failed")
        good = translate_passage(self.library, self.passage, client=self.client)
        self.assertEqual(good["status"], "completed")
        self.assertFalse(good["reused"])

    def test_korean_original_does_not_need_model(self):
        path = self.root / "korean.txt"
        path.write_text("사랑과 기도", encoding="utf-8")
        result = self.library.import_file(path, language="ko")
        pid = self.library.get_version(result["version_id"])["passages"][0]["id"]
        self.client.available = False
        self.assertEqual(translate_passage(self.library, pid, client=self.client)["kind"], "original")

    def test_cloud_model_redirect_and_invalid_response_rejected(self):
        client = OllamaClient()
        with self.assertRaises(LocalModelError):
            client.profile("model:cloud", "embedding")
        with patch.object(client, "_request", return_value={"models": [{"name": "alias", "digest": "x", "remote_host": "remote"}]}):
            with self.assertRaises(LocalModelError):
                client.profile("alias", "embedding")
        with patch.object(client, "_digest", return_value="local"), patch.object(client, "_request", return_value={"remote_model": "remote"}):
            with self.assertRaisesRegex(LocalModelError, "remote_model_blocked"):
                client.profile("alias", "completion")
        profile = {"name": "test", "digest": "old", "num_ctx": 4096}
        with patch.object(client, "_request", return_value={"embeddings": [[float("nan")]]}), patch.object(client, "_digest", return_value="old"):
            with self.assertRaises(LocalModelError):
                client.embed(["source"], profile)
        with patch.object(client, "_request", return_value={"embeddings": [[1.0]]}), patch.object(client, "_digest", return_value="new"):
            with self.assertRaisesRegex(LocalModelError, "model_changed"):
                client.embed(["source"], profile)

    def test_existing_keyword_cache_survives_schema_migration(self):
        first = search(self.library, "Prayer")
        root = self.root / "legacy"
        root.mkdir()
        legacy = sqlite3.connect(root / "library.sqlite3")
        for name in ("001_documents.sql", "002_search.sql"):
            legacy.executescript(Path("holy_naju/migrations", name).read_text(encoding="utf-8"))
        # 버전 2에 존재하던 문헌·검색 행만 옮겨 현재 스키마 전환을 실제로 거친다.
        tables = ("sources", "documents", "editions", "assets", "ingestion_jobs", "acquisitions",
                  "document_versions", "extraction_pages", "passages", "index_generations",
                  "search_runs", "search_hits", "search_history")
        for table in tables:
            columns = [r[1] for r in legacy.execute(f"PRAGMA table_info({table})")]
            rows = self.library.db.execute(f"SELECT {','.join(columns)} FROM {table}").fetchall()
            legacy.executemany(f"INSERT INTO {table} VALUES ({','.join('?' for _ in columns)})", rows)
        generation = first["index_generation_id"]
        legacy.execute("UPDATE search_state SET current_generation_id=?", (generation,))
        legacy.commit()
        legacy.close()
        with Library(root) as migrated:
            self.assertEqual(migrated.db.execute("PRAGMA user_version").fetchone()[0], 4)
            again = search(migrated, "Prayer")
            self.assertTrue(again["reused"])
            self.assertEqual(first["id"], again["id"])
            self.assertEqual(first["hits"], again["hits"])
            self.assertEqual(again["retrieval"], "keyword")

    def test_translation_request_and_unfinished_output(self):
        client = OllamaClient()
        profile = {"name": "test", "digest": "local"}
        result = {"done": True, "done_reason": "stop", "message": {"content": '{"translation":"하느님과 성령"}'}}
        with patch.object(client, "_assert_unchanged"), patch.object(client, "_request", return_value=result) as request:
            self.assertEqual(client.translate("God and the Holy Spirit", profile), "하느님과 성령")
            payload = request.call_args.args[1]
            self.assertIn("God=하느님", payload["messages"][0]["content"])
            self.assertFalse(payload["stream"])
            result["done_reason"] = "length"
            with self.assertRaisesRegex(LocalModelError, "translation_incomplete"):
                client.translate("source", profile)
            result["done_reason"] = "stop"
            result["message"]["content"] = '{"translation":"말씀 كذلك"}'
            with self.assertRaisesRegex(LocalModelError, "unexpected_script"):
                client.translate("source", profile)


if __name__ == "__main__":
    unittest.main()
