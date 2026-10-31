# 문헌 저장소의 파일 중복·원문 버전·OCR 이력·실패 롤백과 무결성을 검증한다.
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID

import pymupdf

from holy_naju.storage import Library

TESSDATA = Path("data/models/tessdata")


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Library(self.root / "library")
        self.addCleanup(self.library.db.close)
        self.path = self.root / "document.txt"
        self.path.write_text("첫 문단 사랑\n둘째 문단 기도", encoding="utf-8")

    def count(self, table):
        return self.library.db.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_schema_is_idempotent_and_foreign_keys_are_enforced(self):
        with Library(self.root / "library") as again:
            self.assertEqual(again.db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(again.db.execute("SELECT count(*) FROM sources").fetchone()[0], 3)
            with self.assertRaises(sqlite3.IntegrityError):
                with again.db:
                    again.db.execute("INSERT INTO editions(id,document_id,source_id,language) VALUES ('bad','missing','missing','ko')")
        self.assertTrue(self.library.check()["ok"])

    def test_duplicate_keeps_ids_and_records_each_acquisition(self):
        original = self.path.read_bytes()
        first = self.library.import_file(self.path, language="ko")
        alias = self.root / "renamed.txt"
        alias.write_bytes(original)
        with patch("holy_naju.storage.extract_file", side_effect=AssertionError("동일 추출 설정은 재사용해야 합니다.")):
            second = self.library.import_file(alias, language="ko")
        for key in ("asset_id", "document_id", "edition_id", "version_id"):
            self.assertEqual(first[key], second[key])
            UUID(first[key])
        self.assertTrue(second["reused_asset"] and second["reused_version"])
        self.assertEqual([self.count(t) for t in ["assets", "documents", "document_versions", "acquisitions"]], [1, 1, 1, 2])
        self.assertEqual(self.path.read_bytes(), original)
        self.assertEqual(self.count("passages"), 2)
        self.assertEqual(self.library.list_documents()[0]["title"], "document")
        self.assertTrue(self.library.check()["ok"])

    def test_newer_schema_is_rejected_without_resetting_data(self):
        result = self.library.import_file(self.path)
        self.library.db.execute("PRAGMA user_version=5")
        with self.assertRaisesRegex(ValueError, "unsupported_schema_version:5"):
            Library(self.root / "library")
        self.assertEqual(self.library.db.execute("PRAGMA user_version").fetchone()[0], 5)
        self.assertEqual(self.library.get_version(result["version_id"])["version"]["status"], "extracted")

    def test_source_update_and_old_reimport_do_not_erase_latest_version(self):
        options = {"source": "vatican", "origin_url": "https://www.vatican.va/example#section", "language": "ko"}
        old = self.library.import_file(self.path, **options)
        old_copy = self.root / "old.txt"
        old_copy.write_bytes(self.path.read_bytes())
        self.path.write_text("새로운 문단 자비", encoding="utf-8")
        new = self.library.import_file(self.path, **options)
        repeated = self.library.import_file(old_copy, **options)
        self.assertEqual(old["edition_id"], new["edition_id"])
        self.assertNotEqual(old["version_id"], new["version_id"])
        self.assertEqual(repeated["version_id"], old["version_id"])
        self.assertEqual(self.library.list_documents()[0]["current_version_id"], new["version_id"])
        self.assertIn("사랑", self.library.get_version(old["version_id"])["version"]["extracted_text"])
        self.assertTrue(self.library.check()["ok"])

    def test_shared_binary_does_not_merge_distinct_publications(self):
        first = self.library.import_file(self.path, source="vatican", origin_url="https://www.vatican.va/a", language="ko")
        second = self.library.import_file(self.path, source="vatican", origin_url="https://www.vatican.va/b", language="ko")
        self.assertEqual(first["asset_id"], second["asset_id"])
        self.assertNotEqual(first["document_id"], second["document_id"])
        attached = self.library.import_file(self.path, edition_id=first["edition_id"])
        self.assertEqual(attached["version_id"], first["version_id"])
        self.assertEqual(self.count("documents"), 2)
        with self.assertRaisesRegex(ValueError, "edition_metadata_mismatch"):
            self.library.import_file(self.path, edition_id=first["edition_id"], language="en")

    def test_failed_document_write_rolls_back_but_keeps_original_and_job(self):
        self.library.db.execute("CREATE TRIGGER fail_passage BEFORE INSERT ON passages BEGIN SELECT RAISE(ABORT, 'test_write_failure'); END")
        with self.assertRaisesRegex(sqlite3.IntegrityError, "test_write_failure"):
            self.library.import_file(self.path)
        self.assertEqual([self.count(t) for t in ["documents", "editions", "acquisitions", "document_versions", "passages"]], [0] * 5)
        self.assertEqual(self.count("assets"), 1)
        job = self.library.db.execute("SELECT * FROM ingestion_jobs").fetchone()
        self.assertEqual(job["status"], "failed")
        self.assertTrue(job["asset_id"])
        self.assertTrue(self.library.check()["ok"])
        self.library.db.execute("DROP TRIGGER fail_passage")
        result = self.library.import_file(self.path)
        self.assertTrue(result["reused_asset"])

    def test_failed_extraction_keeps_file_and_no_empty_document(self):
        self.path.write_text("", encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "empty_document"):
            self.library.import_file(self.path)
        self.assertEqual(self.count("documents"), 0)
        self.assertEqual(self.count("assets"), 1)
        self.assertEqual(self.library.db.execute("SELECT status FROM ingestion_jobs").fetchone()[0], "failed")

    def test_corrupt_asset_is_reported_and_not_overwritten(self):
        self.library.import_file(self.path)
        relative = self.library.db.execute("SELECT relative_path FROM assets").fetchone()[0]
        stored = self.library.asset_path(relative)
        stored.write_bytes(b"corrupt")
        self.assertFalse(self.library.check()["ok"])
        with self.assertRaisesRegex(ValueError, "stored_asset_hash_mismatch"):
            self.library.import_file(self.path)
        self.assertEqual(stored.read_bytes(), b"corrupt")

    def test_invalid_source_and_interrupted_copy_are_visible(self):
        with self.assertRaisesRegex(ValueError, "source_url_mismatch"):
            self.library.import_file(self.path, source="vatican", origin_url="https://example.com/")
        self.assertEqual(self.count("assets"), 0)
        stray = self.library.root / "assets" / ".stage-interrupted.txt"
        stray.write_text("interrupted", encoding="utf-8")
        self.assertTrue(any("untracked_asset" in p for p in self.library.check()["problems"]))

    @unittest.skipUnless((TESSDATA / "eng.traineddata").exists(), "영어 OCR 데이터 필요")
    def test_ocr_retry_keeps_old_version_and_page_links(self):
        scan = self.root / "scan.pdf"
        with pymupdf.open() as source:
            page = source.new_page(width=500, height=200)
            page.insert_text((30, 70), "Prayer and love 31415", fontsize=24)
            image = page.get_pixmap(dpi=200).tobytes("png")
        with pymupdf.open() as document:
            page = document.new_page(width=500, height=200)
            page.insert_image(page.rect, stream=image)
            document.save(scan)
        partial = self.library.import_file(scan, ocr_languages="eng")
        complete = self.library.import_file(scan, edition_id=partial["edition_id"], ocr_languages="eng", tessdata=TESSDATA)
        self.assertEqual(partial["status"], "partial")
        self.assertEqual(complete["status"], "extracted")
        self.assertEqual(self.count("assets"), 1)
        self.assertNotEqual(partial["version_id"], complete["version_id"])
        old = self.library.get_version(partial["version_id"])
        new = self.library.get_version(complete["version_id"])
        self.assertEqual(old["pages"][0]["status"], "ocr_required")
        self.assertIn("31415", new["pages"][0]["raw_text"])
        for passage in new["passages"]:
            self.assertEqual(passage["extraction_page_id"], new["pages"][0]["id"])
            self.assertEqual(passage["text"], new["version"]["extracted_text"][passage["start_offset"]:passage["end_offset"]])
        self.assertTrue(self.library.check()["ok"])


if __name__ == "__main__":
    unittest.main()
