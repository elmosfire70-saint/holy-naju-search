# 짧은 한국어 검색·필터·캐시·원문 변경과 과거 검색 근거 보존을 검증한다.
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from holy_naju.search import get_run, history, search
from holy_naju.storage import Library


class SearchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Library(self.root / "library")
        self.addCleanup(self.library.db.close)
        self.korean_path = self.root / "korean.txt"
        self.korean_path.write_text("성체를 사랑으로 모십니다.\n기도와 봉헌으로 하루를 보냅니다.", encoding="utf-8")
        self.korean = self.library.import_file(self.korean_path, source="naju", language="ko",
                                              origin_url="https://najumary.or.kr/test/10", title="한국어 문헌")
        self.english_path = self.root / "english.txt"
        self.english_path.write_text("The Eucharist builds communion.\nPrayer and love sustain hope.", encoding="utf-8")
        self.english = self.library.import_file(self.english_path, source="vatican", language="en",
                                               origin_url="https://www.vatican.va/test/10", title="English document")

    def test_short_korean_substring_and_phrase(self):
        result = search(self.library, "성체")
        self.assertEqual(len(result["hits"]), 1)
        self.assertEqual(result["hits"][0]["version_id"], self.korean["version_id"])
        self.assertTrue(search(self.library, "기도")['hits'])
        self.assertTrue(search(self.library, "성체를 사랑", mode="phrase")["hits"])
        self.assertFalse(search(self.library, "기도 사랑", mode="phrase")["hits"])
        self.assertTrue(search(self.library, "기도 봉헌")["hits"])
        self.assertTrue(search(self.library, "성")["hits"])

    def test_short_keyword_title_weight_and_plain_text_highlights(self):
        path = self.root / "title.txt"
        path.write_text("다른 본문입니다.", encoding="utf-8")
        imported = self.library.import_file(path, title="성체", language="ko")
        result = search(self.library, "성체")
        self.assertEqual(result["hits"][0]["document_id"], imported["document_id"])
        self.assertEqual(result["hits"][0]["title_highlight_ranges"], [[0, 2]])
        self.assertEqual(result["hits"][0]["highlight_ranges"], [])

    def test_keyword_filters_and_punctuation_are_literal(self):
        self.assertTrue(search(self.library, "Eucharist", source="vatican", language="EN")["hits"])
        self.assertFalse(search(self.library, "Eucharist", source="naju")["hits"])
        self.assertFalse(search(self.library, "' OR 1=1 --")["hits"])
        with self.library.db:
            self.library.db.execute("UPDATE documents SET issued_on='2020-01-01',document_type='encyclical' WHERE id=?",
                                    (self.english["document_id"],))
            self.library.db.execute("UPDATE editions SET language='EN' WHERE id=?", (self.english["edition_id"],))
        self.assertTrue(search(self.library, "Eucharist", language="en")["hits"])
        self.assertTrue(search(self.library, "Eucharist", document_type="encyclical", issued_from="2019-01-01", issued_to="2021-01-01")["hits"])
        self.assertFalse(search(self.library, "Eucharist", issued_from="2021-01-01")["hits"])

    def test_cache_reuse_and_record_for_each_request(self):
        first = search(self.library, "  Prayer   love ", language="EN")
        with patch("holy_naju.search._ranked_hits", side_effect=AssertionError("결과를 재사용해야 합니다.")):
            again = search(self.library, "love prayer", language="en")
        self.assertTrue(again["reused"])
        self.assertEqual(first["id"], again["id"])
        self.assertEqual(first["hits"], again["hits"])
        self.assertEqual(len(history(self.library)), 2)
        self.assertEqual(history(self.library)[0]["query_original"], "love prayer")
        self.assertEqual(history(self.library)[0]["reused"], 1)
        for options in ({"limit": 1}, {"mode": "phrase"}, {"source": "vatican"}, {"refresh": True}):
            self.assertNotEqual(first["id"], search(self.library, "Prayer love", language="en", **options)["id"])

    def test_new_document_and_updated_version_invalidate_cache_but_keep_old_run(self):
        first = search(self.library, "성체")
        self.korean_path.write_text("자비의 길을 따릅니다.", encoding="utf-8")
        self.library.import_file(self.korean_path, edition_id=self.korean["edition_id"])
        new = search(self.library, "성체")
        self.assertFalse(new["hits"])
        self.assertNotEqual(first["index_generation_id"], new["index_generation_id"])
        self.assertEqual(get_run(self.library, first["id"])["hits"], first["hits"])
        self.assertEqual(first["hits"][0]["version_id"], self.korean["version_id"])
        self.korean_path.write_text("성체와 사랑으로 살아갑니다.", encoding="utf-8")
        self.library.import_file(self.korean_path, language="ko")
        self.assertTrue(search(self.library, "성체")["hits"])

    def test_metadata_change_is_snapshotted_and_duplicate_import_keeps_generation(self):
        first = search(self.library, "Eucharist")
        self.library.import_file(self.english_path, edition_id=self.english["edition_id"])
        self.assertTrue(search(self.library, "Eucharist")["reused"])
        with self.library.db:
            self.library.db.execute("UPDATE documents SET title='Changed title' WHERE id=?", (self.english["document_id"],))
        changed = search(self.library, "Eucharist")
        self.assertFalse(changed["reused"])
        self.assertEqual(changed["hits"][0]["title"], "Changed title")
        self.assertEqual(get_run(self.library, first["id"])["hits"][0]["title"], "English document")

    def test_empty_is_reusable_but_failure_rolls_back(self):
        empty = search(self.library, "없는검색어")
        self.assertEqual(empty["hits"], [])
        self.assertTrue(search(self.library, "없는검색어")["reused"])
        before = len(history(self.library))
        generations = self.library.db.execute("SELECT count(*) FROM index_generations").fetchone()[0]
        path = self.root / "new.txt"
        path.write_text("새로운 문헌", encoding="utf-8")
        self.library.import_file(path)
        with patch("holy_naju.search._ranked_hits", side_effect=sqlite3.OperationalError("test_failure")):
            with self.assertRaisesRegex(sqlite3.OperationalError, "test_failure"):
                search(self.library, "새로운")
        self.assertEqual(len(history(self.library)), before)
        self.assertEqual(self.library.db.execute("SELECT count(*) FROM index_generations").fetchone()[0], generations)
        self.assertTrue(search(self.library, "새로운")["hits"])
        self.assertEqual(get_run(self.library, empty["id"])["hits"], [])

    def test_partial_versions_excluded_and_highlights_point_to_original(self):
        with self.library.db:
            self.library.db.execute("UPDATE document_versions SET status='partial' WHERE id=?", (self.korean["version_id"],))
        self.assertFalse(search(self.library, "성체")["hits"])
        result = search(self.library, "Eucharist")
        self.assertTrue(result["hits"])
        for hit in result["hits"]:
            row = self.library.db.execute("SELECT * FROM passages WHERE id=?", (hit["passage_id"],)).fetchone()
            self.assertEqual(hit["excerpt"], row["text"][hit["excerpt_start"]:hit["excerpt_start"] + len(hit["excerpt"])])
            for start, end in hit["highlight_ranges"]:
                self.assertEqual(hit["excerpt"][start:end].lower(), "eucharist")
            self.assertEqual(hit["locator"], json.loads(row["locator"]))
        self.assertTrue(self.library.check()["ok"])

    def test_invalid_input_does_not_create_history(self):
        for query, options in [("", {}), ("\x00", {}), ("x", {"limit": 0}), ("x", {"limit": True}),
                               ("x", {"source": "other"}), ("x", {"source": []}), ("x", {"refresh": "false"}),
                               ("x", {"mode": []}), ("x", {"issued_from": "2021-02-30"}),
                               ("x", {"issued_from": "2021-01-01", "issued_to": "2020-01-01"})]:
            with self.assertRaises(ValueError):
                search(self.library, query, **options)
        self.assertFalse(history(self.library))

    def test_migrate_legacy_document_without_data_loss(self):
        root = self.root / "legacy"
        root.mkdir()
        db = sqlite3.connect(root / "library.sqlite3")
        db.executescript(Path("holy_naju/migrations/001_documents.sql").read_text(encoding="utf-8"))
        db.execute("INSERT INTO documents(id,title,created_at) VALUES ('legacy','Preserved','2020-01-01')")
        db.commit()
        db.close()
        with Library(root) as migrated:
            self.assertEqual(migrated.db.execute("PRAGMA user_version").fetchone()[0], 3)
            self.assertEqual(migrated.db.execute("SELECT title FROM documents WHERE id='legacy'").fetchone()[0], "Preserved")
            self.assertFalse(search(migrated, "anything")["hits"])
            self.assertTrue(migrated.check()["ok"])


if __name__ == "__main__":
    unittest.main()
