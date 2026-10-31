# 목록 발견·중복/차단/재개·수집 버전 연결과 공개 전송 경계를 검증한다.
from io import BytesIO
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import HTTPError

from holy_naju.collections import _worker_lock, collect, initialize, normalize_url, summary, task_list
from holy_naju.public_fetch import CollectionBlocked, NoRedirect, PublicClient
from holy_naju.search import get_run, search
from holy_naju.storage import Library

ROOT = "https://najumary.or.kr/Messages1/"
DOC = ROOT + "?bmode=view&idx=123"
LIST = b'<html><body><a href="?bmode=view&idx=123&q=context">2026 message</a><a href="?page=2&q=context">2</a><a href="https://evil.example/">bad</a></body></html>'
BODY = '<html><div class="view_tit">2026년 1월 1일 사랑의 메시지</div><div class="board_txt_area"><p>사랑과 기도에 관한 통합 검증용 합성 문장입니다. 실제 종교 문헌 인용이 아니며 원문 보관과 검색 기록 연결을 확인합니다.</p></div></html>'.encode()


class FakeClient:
    def __init__(self, responses):
        self.responses, self.calls = responses, []

    def fetch(self, url):
        self.calls.append(url)
        result = self.responses[url]
        if isinstance(result, BaseException):
            raise result
        return result


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.library = Library(self.root / "library")
        self.addCleanup(self.library.db.close)
        initialize(self.library)
        self.scope = dict(self.library.db.execute("SELECT * FROM collection_scopes WHERE id='naju-messages'").fetchone())

    def test_listing_discovery_and_bounded_resume_import(self):
        client = FakeClient({ROOT: LIST, DOC: BODY})
        first = collect(self.library, "naju-messages", pages=1, documents=0, client=client)
        self.assertEqual(client.calls, [ROOT])
        state = next(s for s in first["summary"]["scopes"] if s["id"] == "naju-messages")
        self.assertEqual((state["discovered"], state["linked"], state["lists_pending"]), (1, 0, 1))
        second = collect(self.library, "naju-messages", pages=0, documents=1, client=client)
        self.assertEqual(second["results"][0]["state"], "done")
        version_id = second["results"][0]["version_id"]
        self.assertTrue(self.library.get_version(version_id)["passages"])
        self.assertTrue(search(self.library, "사랑")["hits"])
        self.assertTrue(search(self.library, "사랑", document_type="message")["hits"])
        third = collect(self.library, "naju-messages", pages=0, documents=1, client=client)
        self.assertFalse(third["results"])
        self.assertEqual(client.calls, [ROOT, DOC])
        self.assertTrue(self.library.check()["ok"])

    def test_repeated_page_and_empty_listing_are_not_completion(self):
        client = FakeClient({ROOT: LIST, ROOT + "?page=2": LIST})
        collect(self.library, "naju-messages", pages=2, documents=0, client=client)
        rows = task_list(self.library, "naju-messages")["tasks"]
        self.assertTrue(any(t["error"] and "repeated_listing_content" in t["error"] for t in rows))
        self.assertFalse(summary(self.library)["complete"])
        other = FakeClient({ROOT: b"<html>nothing</html>"})
        result = collect(self.library, "naju-messages", pages=1, documents=0, refresh=True, client=other)
        self.assertEqual(result["results"][0]["state"], "failed")

    def test_block_retry_and_interrupt_resume_keep_evidence(self):
        blocked = collect(self.library, "naju-messages", pages=1, documents=1,
                          client=FakeClient({ROOT: CollectionBlocked("robots_unavailable")}))
        self.assertEqual(blocked["stopped"], "access_or_policy_blocked")
        self.assertEqual(blocked["results"][0]["state"], "blocked")
        challenge = collect(self.library, "naju-messages", retry=True, client=FakeClient({ROOT: b"<html><title>Just a moment</title></html>"}))
        self.assertEqual(challenge["stopped"], "access_or_policy_blocked")
        self.assertEqual(challenge["results"][0]["state"], "blocked")
        client = FakeClient({ROOT: LIST, DOC: KeyboardInterrupt()})
        with self.assertRaises(KeyboardInterrupt):
            collect(self.library, "naju-messages", pages=1, documents=1, retry=True, client=client)
        self.assertEqual(self.library.db.execute("SELECT count(*) FROM collection_tasks WHERE state='running'").fetchone()[0], 1)
        collect(self.library, "naju-messages", pages=0, documents=1, client=FakeClient({DOC: BODY}))
        self.assertEqual(self.library.db.execute("SELECT count(*) FROM collection_attempts WHERE state='interrupted'").fetchone()[0], 1)
        self.assertEqual(self.library.db.execute("SELECT count(*) FROM collection_tasks WHERE state='running'").fetchone()[0], 0)

    def test_refresh_retains_old_versions_hits_and_failed_update_link(self):
        client = FakeClient({ROOT: LIST, DOC: BODY})
        collect(self.library, "naju-messages", pages=1, documents=1, client=client)
        old = search(self.library, "사랑")
        client.responses[DOC] = BODY.replace('사랑과 기도'.encode(), '사랑과 새로운 기도'.encode())
        new = collect(self.library, "naju-messages", pages=0, documents=1, refresh=True, client=client)
        self.assertNotEqual(old["hits"][0]["version_id"], new["results"][0]["version_id"])
        self.assertEqual(get_run(self.library, old["id"])["hits"], old["hits"])
        client.responses[DOC] = CollectionBlocked("http_403")
        failed = collect(self.library, "naju-messages", pages=0, documents=1, refresh=True, client=client)
        self.assertEqual(failed["results"][0]["state"], "blocked")
        self.assertEqual(failed["results"][0]["version_id"], new["results"][0]["version_id"])

    def test_url_boundaries_unresolved_scope_and_single_worker(self):
        self.assertEqual(normalize_url(self.scope, ROOT + "?q=opaque&page=1"), (ROOT, "list"))
        self.assertEqual(normalize_url(self.scope, DOC + "&q=opaque&t=board#reply"), (DOC, "document"))
        for url in ("http://najumary.or.kr/Messages1/", "https://evil.example/Messages1/", "https://user@najumary.or.kr/Messages1/", ROOT + "?page=0", ROOT + "?page=2&category=private", "https://najumary.or.kr/%4dessages1/"):
            with self.assertRaises(ValueError):
                normalize_url(self.scope, url)
        with self.assertRaisesRegex(ValueError, "entry_unverified"):
            collect(self.library, "trent-and-earlier")
        with _worker_lock(self.library):
            with self.assertRaisesRegex(ValueError, "worker_busy"):
                collect(self.library, "naju-messages", client=FakeClient({ROOT: LIST}))
        for pages in (-1, True, 21):
            with self.assertRaises(ValueError):
                collect(self.library, "naju-messages", pages=pages)

    def test_migrate_v3_without_losing_documents_or_search(self):
        root = self.root / "legacy"
        root.mkdir()
        db = sqlite3.connect(root / "library.sqlite3")
        for name in ("001_documents.sql", "002_search.sql", "003_local_models.sql"):
            db.executescript(Path("holy_naju/migrations", name).read_text(encoding="utf-8"))
        db.execute("INSERT INTO documents(id,title,created_at) VALUES ('preserved','Old document','2020')")
        db.commit()
        db.close()
        with Library(root) as library:
            self.assertEqual(library.db.execute("PRAGMA user_version").fetchone()[0], 4)
            self.assertEqual(library.db.execute("SELECT title FROM documents WHERE id='preserved'").fetchone()[0], "Old document")
            self.assertTrue(library.check()["ok"])

    def test_robots_policy_and_http_validation(self):
        client = PublicClient(self.root / "evidence")
        robot = b"User-agent: *\nDisallow: /Messages1/\nCrawl-delay: 2\n"
        with patch.object(client, "_get", return_value=(robot, "text/plain")) as fetch:
            with self.assertRaisesRegex(CollectionBlocked, "robots_disallowed"):
                client.fetch(ROOT)
            self.assertEqual(fetch.call_count, 1)
        client = PublicClient(self.root / "other")
        with patch.object(client, "_get", return_value=(b"<html>challenge</html>", "text/html")):
            with self.assertRaisesRegex(CollectionBlocked, "robots_unavailable"):
                client.fetch(ROOT)
        with self.assertRaises(ValueError):
            client.fetch("https://localhost/private")
        with self.assertRaises(CollectionBlocked):
            NoRedirect().redirect_request(None, None, 302, "", {}, ROOT)
        with patch.object(client.opener, "open", side_effect=HTTPError(ROOT, 403, "Forbidden", {}, BytesIO())):
            with self.assertRaisesRegex(CollectionBlocked, "http_403"):
                client._get(ROOT)


if __name__ == "__main__":
    unittest.main()
