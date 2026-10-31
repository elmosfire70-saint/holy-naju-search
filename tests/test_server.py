# 로컬 HTTP 경계와 실제 DB 검색·문단·가져오기·보관 파일 연결을 검증한다.
import http.client
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

from holy_naju.local_models import LocalModelError
from holy_naju.server import Handler, LocalServer
from holy_naju.storage import Library
from holy_naju.translation import translate_passage


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        path = self.root / "original.html"
        path.write_text('<html><body><p>성체와 기도 &lt;script&gt;alert(1)&lt;/script&gt;</p></body></html>', encoding="utf-8")
        with Library(self.root / "library") as library:
            self.document = library.import_file(path, language="ko", title="근거 자료")
        self.server = LocalServer(self.root / "library", port=0)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop_server)

    def stop_server(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=5)

    def request(self, path, payload=None, headers=None, raw=None):
        writing = payload is not None or raw is not None
        default = {"Origin": f"http://127.0.0.1:{self.server.server_port}", "X-Holy-Naju": "1",
                   "Content-Type": "application/octet-stream" if raw is not None else "application/json"}
        default.update(headers or {})
        connection = http.client.HTTPConnection("127.0.0.1", self.server.server_port, timeout=10)
        body = raw if raw is not None else json.dumps(payload).encode() if writing else None
        connection.request("POST" if writing else "GET", path, body=body, headers=default)
        response = connection.getresponse()
        data, status, received = response.read(), response.status, dict(response.getheaders())
        connection.close()
        return status, json.loads(data) if received["Content-Type"].startswith("application/json") else data, received

    def test_security_headers_static_allowlist_and_cross_origin(self):
        status, data, headers = self.request("/")
        self.assertEqual(status, 200)
        self.assertIn("원문과 한국어 번역".encode(), data)
        self.assertNotIn(b"variant=", data)
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertEqual(headers["Cache-Control"], "no-store")
        for path in ("/../data/library/library.sqlite3", "/api/unknown", "/%2e%2e/AGENTS.md"):
            self.assertEqual(self.request(path)[0], 404)
        self.assertEqual(self.request("/api/library", headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.request("/api/search", {"query": "성체"}, {"Origin": "https://attacker.example"})[0], 403)
        self.assertEqual(self.request("/api/search", {"query": "성체"}, {"X-Holy-Naju": ""})[0], 403)
        self.assertEqual(self.request("/api/search", {"query": "성체"}, {"Content-Type": "text/plain"})[0], 415)

    def test_search_reuse_history_passage_and_download(self):
        status, result, _ = self.request("/api/search", {"query": "성체", "source": "user_import"})
        self.assertEqual(status, 200)
        again = self.request("/api/search", {"query": "성체", "source": "user_import"})[1]
        self.assertTrue(again["reused"])
        self.assertEqual(result["id"], again["id"])
        rows = self.request("/api/history")[1]
        self.assertEqual(len(rows), 2)
        old = self.request("/api/runs/" + result["id"])[1]
        self.assertEqual(old["hits"], result["hits"])
        passage = self.request("/api/passages/" + result["hits"][0]["passage_id"])[1]
        self.assertEqual(passage["version_id"], self.document["version_id"])
        self.assertIn("성체", passage["text"])
        response = self.request("/api/assets/" + passage["asset_id"])
        self.assertEqual(response[0], 200)
        self.assertEqual(response[2]["Content-Type"], "application/octet-stream")
        self.assertIn("attachment;", response[2]["Content-Disposition"])
        self.assertEqual(response[1], (self.root / "original.html").read_bytes())
        version = self.request("/api/versions/" + passage["version_id"])[1]
        self.assertEqual(version["passages"][0]["id"], passage["id"])
        self.assertNotIn("extracted_text", version["version"])

    def test_import_reuses_existing_service_and_blocks_paths(self):
        response = self.request("/api/import?filename=scan.txt&language=ko", raw="사랑과 봉헌".encode())
        self.assertEqual(response[0], 200)
        again = self.request("/api/import?filename=scan.txt&language=ko", raw="사랑과 봉헌".encode())[1]
        self.assertTrue(again["reused_version"])
        self.assertEqual(len(self.request("/api/library")[1]), 2)
        for name in ("../escape.txt", "C%3A%5Cescape.txt", "CON.txt", "script.js", "bad.txt%00", "bad%3F.txt"):
            self.assertEqual(self.request("/api/import?filename=" + name, raw=b"test")[0], 400)
        self.assertFalse((self.root / "escape.txt").exists())
        self.assertEqual(self.request("/api/import?filename=x.txt&source=vatican", raw=b"test")[0], 400)

    def test_translation_original_and_failure_are_not_empty_success(self):
        run = self.request("/api/search", {"query": "성체"})[1]
        pid = run["hits"][0]["passage_id"]
        korean = self.request("/api/translate", {"passage_id": pid})
        self.assertEqual(korean[0], 200)
        self.assertEqual(korean[1]["kind"], "original")
        with patch("holy_naju.server.translate_passage", side_effect=LocalModelError("test_unavailable")):
            failed = self.request("/api/translate", {"passage_id": pid})
        self.assertEqual(failed[0], 502)
        self.assertEqual(failed[1]["error"], "test_unavailable")
        self.assertEqual(self.request("/api/passages/" + pid)[0], 200)

    def test_invalid_input_and_request_limit(self):
        for payload in ({"query": ""}, {"query": "성체", "source": "other"}, {"query": "성체", "root": "C:/"}, []):
            self.assertEqual(self.request("/api/search", payload)[0], 400)
        self.assertEqual(self.request("/api/translate", {"passage_id": "x", "refresh": "yes"})[0], 400)
        self.assertEqual(self.request("/api/search", raw=b"x", headers={"Content-Type": "application/json", "Content-Length": "20000"})[0], 413)
        self.assertEqual(self.request("/api/runs/missing")[0], 404)

    def test_saved_translation_reads_without_model_and_hybrid_fallback(self):
        path = self.root / "english.txt"
        path.write_text("The Eucharist and prayer.", encoding="utf-8")
        client = Mock()
        client.profile.return_value = {"name": "local-test", "digest": "test-digest"}
        client.translate.return_value = "성체와 기도."
        with Library(self.root / "library") as library:
            imported = library.import_file(path, language="en")
            pid = library.get_version(imported["version_id"])["passages"][0]["id"]
            saved = translate_passage(library, pid, client=client)
        with patch("holy_naju.local_models.OllamaClient._request", side_effect=LocalModelError("test_offline")):
            response = self.request("/api/translations/" + saved["id"])
            self.assertEqual(response[0], 200)
            self.assertEqual(response[1]["text"], "성체와 기도.")
            self.assertEqual(self.request("/api/passages/" + pid)[1]["translations"][0]["id"], saved["id"])
            fallback = self.request("/api/search", {"query": "Eucharist", "retrieval": "hybrid"})
            self.assertEqual(fallback[0], 200)
            self.assertEqual(fallback[1]["retrieval"], "keyword")
            self.assertTrue(fallback[1]["hits"])
            self.assertEqual(fallback[1]["diagnostics"]["semantic_status"], "unavailable")

    def test_disconnected_browser_does_not_send_a_second_error(self):
        with patch.object(Handler, "_send", side_effect=ConnectionAbortedError("browser navigation")) as send:
            with self.assertRaises(http.client.RemoteDisconnected):
                self.request("/")
            send.assert_called_once()

    def test_collection_status_and_bounded_api(self):
        response = self.request("/api/collections")
        self.assertEqual(response[0], 200)
        self.assertFalse(response[1]["complete"])
        scopes = response[1]["scopes"]
        self.assertTrue(any(scope["discovery_status"] == "entry_unverified" for scope in scopes))
        self.assertEqual(self.request("/api/collections/naju-messages")[0], 200)
        self.assertEqual(self.request("/api/collections/unknown")[0], 404)
        self.assertEqual(self.request("/api/collect", {"scope_id": "naju-messages", "pages": 1000})[0], 400)
        with patch("holy_naju.server.collect", return_value={"results": [], "summary": {}}) as collector:
            self.assertEqual(self.request("/api/collect", {"scope_id": "naju-messages", "retry": True})[0], 200)
            self.assertEqual(collector.call_args.kwargs, {"pages": 1, "documents": 1, "retry": True})


if __name__ == "__main__":
    unittest.main()
