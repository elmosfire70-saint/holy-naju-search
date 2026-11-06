# 원본 파일을 보존하고 문헌·추출 버전·페이지·문단을 SQLite에 연결한다.
from datetime import datetime, timezone
import hashlib
from importlib.metadata import version as package_version
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from urllib.parse import urlsplit, urlunsplit
from uuid import uuid4, uuid5, NAMESPACE_URL

from holy_naju.extraction import EXTRACTOR_REVISION, extract_file

MEDIA_TYPES = {".html": "text/html", ".htm": "text/html", ".txt": "text/plain",
               ".pdf": "application/pdf", ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
SOURCE_INFO = {"vatican": ("교황청", "https://www.vatican.va"),
               "naju": ("나주 공식 사이트", "https://najumary.or.kr"),
               "user_import": ("사용자 가져오기", None)}
MAX_FILE_BYTES = 50 * 1024 * 1024


def now():
    return datetime.now(timezone.utc).isoformat()


def encode(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def file_hash(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def canonical_url(url, source):
    if not url:
        return None
    parsed = urlsplit(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("invalid_origin_url")
    allowed = {"vatican": {"www.vatican.va", "vatican.va", "press.vatican.va"},
               "naju": {"najumary.or.kr", "www.najumary.or.kr"}}
    if source in allowed and (parsed.hostname not in allowed[source] or parsed.port not in (None, 443)):
        raise ValueError("source_url_mismatch")
    return urlunsplit(parsed._replace(fragment=""))


class Library:
    def __init__(self, root="data/library"):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        (self.root / "assets").mkdir(exist_ok=True)
        self.db = sqlite3.connect(self.root / "library.sqlite3", timeout=30)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys = ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        try:
            migrations = ("001_documents.sql", "002_search.sql", "003_local_models.sql", "004_collections.sql", "005_live_search.sql")
            if version > len(migrations):
                raise ValueError(f"unsupported_schema_version:{version}")
            for name in migrations[version:]:
                sql = (Path(__file__).parent / "migrations" / name).read_text(encoding="utf-8")
                self.db.executescript("BEGIN IMMEDIATE;\n" + sql + "\nCOMMIT;")
            with self.db:
                for kind, (name, base) in SOURCE_INFO.items():
                    self.db.execute("INSERT OR IGNORE INTO sources VALUES (?,?,?,?)",
                                    (str(uuid5(NAMESPACE_URL, base or "holy-naju:user_import")), kind, name, base))
        except Exception:
            self.db.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.db.close()

    def asset_path(self, relative):
        path = (self.root / relative).resolve()
        if not path.is_relative_to(self.root / "assets"):
            raise ValueError("asset_path_outside_library")
        return path

    def _save_asset(self, path, job_id):
        stage = None
        try:
            with path.open("rb") as source, tempfile.NamedTemporaryFile(
                    dir=self.root / "assets", suffix=path.suffix.lower(), prefix=".stage-", delete=False) as target:
                stage = Path(target.name)
                total = 0
                while block := source.read(1024 * 1024):
                    total += len(block)
                    if total > MAX_FILE_BYTES:
                        raise ValueError("file_too_large")
                    target.write(block)
            digest = file_hash(stage)
            existing = self.db.execute("SELECT * FROM assets WHERE sha256=?", (digest,)).fetchone()
            if existing and existing["media_type"] != MEDIA_TYPES[path.suffix.lower()]:
                raise ValueError("asset_format_mismatch")
            relative = existing["relative_path"] if existing else f"assets/{digest[:2]}/{digest}{path.suffix.lower()}"
            target = self.asset_path(relative)
            with self.db:
                self.db.execute("UPDATE ingestion_jobs SET pending_path=?, updated_at=? WHERE id=?",
                                (relative, now(), job_id))
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                if file_hash(target) != digest:
                    raise ValueError("stored_asset_hash_mismatch")
            else:
                os.replace(stage, target)
            asset_id = existing["id"] if existing else str(uuid4())
            with self.db:
                if not existing:
                    self.db.execute("INSERT INTO assets VALUES (?,?,?,?,?,?)",
                                    (asset_id, digest, MEDIA_TYPES[path.suffix.lower()], total, relative, path.name))
                self.db.execute("UPDATE ingestion_jobs SET asset_id=?, updated_at=? WHERE id=?",
                                (asset_id, now(), job_id))
            return asset_id, target, digest, bool(existing)
        finally:
            if stage is not None and stage.exists():
                stage.unlink()

    def import_file(self, path, *, source="user_import", origin_url=None, language="und",
                    origin_kind="user_import", title=None, edition_id=None, ocr_languages="eng+kor", tessdata=None):
        path = Path(path).resolve()
        job_id = str(uuid4())
        with self.db:
            self.db.execute("INSERT INTO ingestion_jobs(id,target,status,created_at,updated_at) VALUES (?,?,'running',?,?)",
                            (job_id, str(path), now(), now()))
        try:
            if source not in SOURCE_INFO or origin_kind not in {"user_import", "download"}:
                raise ValueError("invalid_source_or_origin")
            url = canonical_url(origin_url, source)
            if path.suffix.lower() not in MEDIA_TYPES or not path.is_file():
                raise ValueError("unsupported_or_missing_file")
            edition = None
            if edition_id:
                edition = self.db.execute("SELECT e.*, s.kind FROM editions e JOIN sources s ON s.id=e.source_id WHERE e.id=?",
                                          (edition_id,)).fetchone()
                if edition is None:
                    raise ValueError("unknown_edition")
                if (source != "user_import" and source != edition["kind"]) or (language != "und" and language != edition["language"]):
                    raise ValueError("edition_metadata_mismatch")
                source, language = edition["kind"], edition["language"]
                if url and url != edition["canonical_url"]:
                    raise ValueError("edition_url_mismatch")
            elif source != "user_import" and not url:
                raise ValueError("official_source_requires_url_or_edition")
            if origin_kind == "download" and not url:
                url = edition["canonical_url"] if edition else None
                if not url:
                    raise ValueError("download_requires_origin_url")
            asset_id, stored_path, digest, reused_asset = self._save_asset(path, job_id)
            source_id = self.db.execute("SELECT id FROM sources WHERE kind=?", (source,)).fetchone()[0]
            if edition is None:
                if url:
                    edition = self.db.execute("SELECT * FROM editions WHERE source_id=? AND canonical_url=? AND language=?",
                                              (source_id, url, language)).fetchone()
                else:
                    edition = self.db.execute("SELECT e.* FROM editions e JOIN acquisitions a ON a.edition_id=e.id "
                                              "WHERE e.source_id=? AND e.language=? AND e.canonical_url IS NULL AND a.asset_id=? LIMIT 1",
                                              (source_id, language, asset_id)).fetchone()
            profile = {"format": stored_path.suffix, "source": source, "extractor_revision": EXTRACTOR_REVISION}
            parser_package = {".pdf": "PyMuPDF", ".html": "beautifulsoup4", ".htm": "beautifulsoup4", ".docx": "python-docx"}.get(stored_path.suffix)
            if parser_package:
                profile["parser_revision"] = package_version(parser_package)
            if stored_path.suffix == ".pdf":
                profile["ocr_languages"] = ocr_languages
                profile["ocr_models"] = {lang: file_hash(Path(tessdata) / f"{lang}.traineddata")
                                         if tessdata and (Path(tessdata) / f"{lang}.traineddata").is_file() else None
                                         for lang in ocr_languages.split("+")}
            cached = self.db.execute("SELECT id,status FROM document_versions WHERE edition_id=? AND asset_id=? "
                                     "AND extraction_profile=? AND status='extracted' ORDER BY created_at DESC LIMIT 1",
                                     (edition["id"], asset_id, encode(profile))).fetchone() if edition else None
            extraction_key = None
            if cached is None:
                # 추출은 보관된 불변 파일에서 실행해 사용자 원본 변경과 경쟁하지 않는다.
                extracted = extract_file(stored_path, source, ocr_languages, tessdata)
                if extracted["status"] == "empty":
                    raise ValueError("empty_document")
                extraction_key = hashlib.sha256(encode({"profile": profile, "result": extracted}).encode()).hexdigest()
            status = cached["status"] if cached else extracted["status"]
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                if edition is None:
                    document_id, edition_id = str(uuid4()), str(uuid4())
                    document_title = title or extracted["title"] or path.stem
                    if not title and document_title == stored_path.stem:
                        document_title = path.stem
                    self.db.execute("INSERT INTO documents(id,title,created_at) VALUES (?,?,?)",
                                    (document_id, document_title, now()))
                    self.db.execute("INSERT INTO editions(id,document_id,source_id,language,canonical_url) VALUES (?,?,?,?,?)",
                                    (edition_id, document_id, source_id, language, url))
                else:
                    document_id, edition_id = edition["document_id"], edition["id"]
                acquisition_id = str(uuid4())
                self.db.execute("INSERT INTO acquisitions VALUES (?,?,?,?,?,?,?,?,?)",
                                (acquisition_id, edition_id, asset_id, origin_kind, url, str(path), now(), job_id, None))
                version = cached or self.db.execute("SELECT id FROM document_versions WHERE edition_id=? AND asset_id=? AND extraction_key=?",
                                                    (edition_id, asset_id, extraction_key)).fetchone()
                if version:
                    version_id = version["id"]
                else:
                    version_id = self._insert_version(edition_id, asset_id, acquisition_id, extracted, profile, extraction_key)
                    self.db.execute("UPDATE editions SET current_version_id=? WHERE id=?", (version_id, edition_id))
                self.db.execute("UPDATE acquisitions SET version_id=? WHERE id=?", (version_id, acquisition_id))
                self.db.execute("UPDATE ingestion_jobs SET status=?, updated_at=? WHERE id=?",
                                ("completed" if status == "extracted" else "partial", now(), job_id))
            return {"document_id": document_id, "edition_id": edition_id, "asset_id": asset_id,
                    "version_id": version_id, "job_id": job_id, "sha256": digest,
                    "reused_asset": reused_asset, "reused_version": bool(version), "status": status}
        except Exception as error:
            with self.db:
                self.db.execute("UPDATE ingestion_jobs SET status='failed', error=?, updated_at=? WHERE id=?",
                                (f"{type(error).__name__}:{error}", now(), job_id))
            raise

    def _insert_version(self, edition_id, asset_id, acquisition_id, extracted, profile, extraction_key):
        version_id = str(uuid4())
        text = "\n\n".join(p["text"] for p in extracted["passages"])
        self.db.execute("INSERT INTO document_versions VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                        (version_id, edition_id, asset_id, acquisition_id, extraction_key, encode(profile),
                         hashlib.sha256(text.encode()).hexdigest(), text, extracted["extractor_revision"], extracted["status"], now()))
        page_ids = {}
        for page in extracted["pages"]:
            page_id = page_ids[page["page"]] = str(uuid4())
            self.db.execute("INSERT INTO extraction_pages VALUES (?,?,?,?,?,?,?,?,?,?)",
                            (page_id, version_id, page["page"], page["method"], page["engine_revision"],
                             page.get("languages"), page["status"], page["raw_text"], page["review_status"], page.get("error")))
        offset = 0
        for passage in extracted["passages"]:
            locator = passage["locator"]
            self.db.execute("INSERT INTO passages VALUES (?,?,?,?,?,?,?,?,?)",
                            (str(uuid4()), version_id, page_ids.get(locator.get("page")), passage["ordinal"], None,
                             encode(locator), offset, offset + len(passage["text"]), passage["text"]))
            offset += len(passage["text"]) + 2
        return version_id

    def list_documents(self):
        return [dict(row) for row in self.db.execute(
            "SELECT d.id, d.title, e.id AS edition_id, s.kind AS source, e.language, e.canonical_url, "
            "e.current_version_id, v.status, (SELECT count(*) FROM document_versions x WHERE x.edition_id=e.id) AS versions, "
            "(SELECT count(*) FROM passages p WHERE p.version_id=v.id) AS passages "
            "FROM documents d JOIN editions e ON e.document_id=d.id JOIN sources s ON s.id=e.source_id "
            "LEFT JOIN document_versions v ON v.id=e.current_version_id ORDER BY d.created_at")]

    def get_version(self, version_id):
        row = self.db.execute("SELECT * FROM document_versions WHERE id=?", (version_id,)).fetchone()
        if row is None:
            raise KeyError(version_id)
        return {"version": dict(row),
                "pages": [dict(p) for p in self.db.execute("SELECT * FROM extraction_pages WHERE version_id=? ORDER BY page_number", (version_id,))],
                "passages": [dict(p) for p in self.db.execute("SELECT * FROM passages WHERE version_id=? ORDER BY ordinal", (version_id,))]}

    def check(self):
        problems = []
        for row in self.db.execute("PRAGMA quick_check"):
            if row[0] != "ok":
                problems.append(str(tuple(row)))
        problems.extend(str(tuple(row)) for row in self.db.execute("PRAGMA foreign_key_check"))
        known = set()
        for row in self.db.execute("SELECT * FROM assets"):
            path = self.asset_path(row["relative_path"])
            known.add(path)
            if not path.is_file() or file_hash(path) != row["sha256"]:
                problems.append("asset_missing_or_changed:" + row["id"])
        problems.extend("untracked_asset:" + p.relative_to(self.root).as_posix()
                        for p in (self.root / "assets").rglob("*") if p.is_file() and p.resolve() not in known)
        problems.extend("unfinished_job:" + row[0] for row in self.db.execute("SELECT id FROM ingestion_jobs WHERE status='running'"))
        return {"ok": not problems, "problems": problems}
