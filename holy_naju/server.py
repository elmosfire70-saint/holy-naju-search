# 개인 PC의 루프백에서 문헌 검색·번역·가져오기 API와 연구실 화면을 제공한다.
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import logging
from pathlib import Path, PureWindowsPath
import sqlite3
import tempfile
from urllib.parse import parse_qs, quote, urlsplit

from holy_naju.local_models import LocalModelError
from holy_naju.search import get_run, history, search
from holy_naju.storage import Library, MAX_FILE_BYTES, MEDIA_TYPES, file_hash
from holy_naju.translation import get_translation, translate_passage

WEB = Path(__file__).with_name("web")
STATIC = {"/": ("index.html", "text/html; charset=utf-8"),
          "/app.js": ("app.js", "text/javascript; charset=utf-8"),
          "/app.css": ("app.css", "text/css; charset=utf-8")}


def passage_detail(library, passage_id):
    row = library.db.execute(
        "SELECT p.*,e.language,e.canonical_url,d.title,s.kind AS source,v.asset_id,v.status AS extraction_status,"
        "v.created_at AS version_created_at,x.review_status AS ocr_review_status "
        "FROM passages p JOIN document_versions v ON v.id=p.version_id JOIN editions e ON e.id=v.edition_id "
        "JOIN documents d ON d.id=e.document_id JOIN sources s ON s.id=e.source_id "
        "LEFT JOIN extraction_pages x ON x.id=p.extraction_page_id WHERE p.id=?", (passage_id,)).fetchone()
    if row is None:
        raise KeyError(passage_id)
    result = dict(row)
    result["locator"] = json.loads(result["locator"])
    result["translations"] = [dict(t) for t in library.db.execute(
        "SELECT id,status,review_status,created_at,prompt_revision,error FROM translations "
        "WHERE passage_id=? ORDER BY created_at DESC,rowid DESC LIMIT 20", (passage_id,))]
    return result


class LocalServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, root="data/library", port=8766):
        self.root = Path(root).resolve()
        with Library(self.root):
            pass
        super().__init__(("127.0.0.1", port), Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        # 개인 질의와 가져오기 파일명을 HTTP 접근 로그에 남기지 않는다.
        pass

    def _send(self, status, data, content_type="application/json; charset=utf-8", filename=None):
        if isinstance(data, (dict, list)):
            data = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; img-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        self.send_header("Connection", "close")
        if filename:
            self.send_header("Content-Disposition", "attachment; filename*=UTF-8''" + quote(filename, safe=""))
        self.end_headers()
        self.close_connection = True
        self.wfile.write(data)

    def _dispatch(self, writing=False):
        try:
            port = self.server.server_port
            hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}
            if self.headers.get("Host") not in hosts:
                return self._send(403, {"error": "invalid_host"})
            path = urlsplit(self.path).path
            if not writing and path == "/favicon.ico":
                return self._send(204, b"", "image/x-icon")
            if writing:
                if (self.headers.get("Origin") != "http://" + self.headers["Host"] or
                        self.headers.get("X-Holy-Naju") != "1"):
                    return self._send(403, {"error": "same_origin_required"})
                uploading = path == "/api/import"
                expected_type = "application/octet-stream" if uploading else "application/json"
                if self.headers.get("Content-Type", "").split(";")[0] != expected_type:
                    return self._send(415, {"error": "invalid_content_type"})
                lengths = self.headers.get_all("Content-Length", [])
                if len(lengths) != 1 or self.headers.get("Transfer-Encoding"):
                    raise ValueError("content_length_required")
                size = int(lengths[0])
                if not 0 < size <= (MAX_FILE_BYTES if uploading else 16384):
                    return self._send(413, {"error": "request_too_large_or_empty"})
                self.connection.settimeout(30)
                body = self.rfile.read(size)
                if len(body) != size:
                    raise ValueError("incomplete_request")
                payload = body if uploading else json.loads(body)
                if not uploading and not isinstance(payload, dict):
                    raise ValueError("json_object_required")
                with Library(self.server.root) as library:
                    result = self._post(library, path, payload)
                return self._send(200, result)
            if path in STATIC:
                filename, content_type = STATIC[path]
                return self._send(200, (WEB / filename).read_bytes(), content_type)
            with Library(self.server.root) as library:
                if path.startswith("/api/assets/"):
                    row = library.db.execute("SELECT * FROM assets WHERE id=?", (path.removeprefix("/api/assets/"),)).fetchone()
                    if row is None:
                        raise KeyError(path)
                    asset = library.asset_path(row["relative_path"])
                    if file_hash(asset) != row["sha256"]:
                        raise ValueError("asset_changed")
                    return self._send(200, asset.read_bytes(), "application/octet-stream", row["original_filename"])
                result = self._get(library, path)
            self._send(200, result)
        except KeyError:
            self._send(404, {"error": "not_found"})
        except LocalModelError as error:
            self._send(502, {"error": str(error)})
        except (ValueError, TypeError) as error:
            self._send(400, {"error": str(error)})
        except sqlite3.Error as error:
            logging.exception("Local database request failed")
            self._send(503, {"error": "database_unavailable", "detail": type(error).__name__})
        except (ConnectionError, TimeoutError):
            pass
        except Exception:
            logging.exception("Local request failed")
            self._send(500, {"error": "internal_error"})

    def _get(self, library, path):
        if path == "/api/library":
            return library.list_documents()
        if path == "/api/history":
            return history(library, limit=100)
        for prefix, getter in (("/api/runs/", get_run), ("/api/passages/", passage_detail),
                               ("/api/translations/", get_translation)):
            if path.startswith(prefix):
                return getter(library, path.removeprefix(prefix))
        if path.startswith("/api/versions/"):
            result = library.get_version(path.removeprefix("/api/versions/"))
            del result["version"]["extracted_text"]
            return result
        raise KeyError(path)

    def _post(self, library, path, payload):
        if path == "/api/search":
            allowed = {"query", "source", "language", "document_type", "issued_from", "issued_to",
                       "mode", "limit", "refresh", "retrieval"}
            if "query" not in payload or payload.keys() - allowed:
                raise ValueError("invalid_search_fields")
            return search(library, **payload)
        if path == "/api/translate":
            if set(payload) - {"passage_id", "refresh"} or not isinstance(payload.get("passage_id"), str):
                raise ValueError("invalid_translation_fields")
            if type(payload.get("refresh", False)) is not bool:
                raise ValueError("invalid_refresh")
            return translate_passage(library, **payload)
        if path == "/api/import":
            options = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
            if options.keys() - {"filename", "language", "title"} or any(len(v) != 1 for v in options.values()):
                raise ValueError("invalid_import_fields")
            name = options.get("filename", [""])[0]
            if (not name or len(name) > 240 or PureWindowsPath(name).is_reserved() or name.rstrip(' .') != name or any(c in name for c in '/\\:<>"|?*\x00') or
                    any(ord(c) < 32 for c in name) or Path(name).suffix.lower() not in MEDIA_TYPES):
                raise ValueError("invalid_filename_or_format")
            language = options.get("language", ["und"])[0]
            if language not in {"ko", "en", "it", "la", "und"}:
                raise ValueError("invalid_import_language")
            title = options.get("title", [""])[0]
            if len(title) > 500:
                raise ValueError("title_too_long")
            with tempfile.TemporaryDirectory(prefix="holy-naju-import-") as folder:
                uploaded = Path(folder) / name
                uploaded.write_bytes(payload)
                return library.import_file(uploaded, title=title or None, language=language,
                                           tessdata="data/models/tessdata")
        raise KeyError(path)

    def do_GET(self):
        self._dispatch()

    def do_POST(self):
        self._dispatch(writing=True)

    def do_OPTIONS(self):
        self._send(403, {"error": "cross_origin_not_supported"})
