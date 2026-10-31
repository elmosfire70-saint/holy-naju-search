# 공식 목록에서 발견한 URL과 제한 수집·재개·원문 보관 연결을 관리한다.
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import sqlite3
from urllib.parse import parse_qs, unquote, urljoin, urlsplit, urlunsplit
from uuid import uuid4

from bs4 import BeautifulSoup, SoupStrainer

from holy_naju.extraction import extract_file
from holy_naju.public_fetch import CollectionBlocked, HOSTS, PublicClient
from holy_naju.storage import file_hash, now

CATALOG = Path(__file__).resolve().parents[1] / "config/source-catalog.json"


def _document_type(scope, title):
    if scope["strategy"] == "naju":
        return "message" if re.search(r"\d{4}년", title) else "collection_note"
    return {"vatican_ii": "council", "vatican_i": "council", "catechism": "catechism", "fixed": "encyclical"}[scope["strategy"]]


def normalize_url(scope, url):
    p = urlsplit(url)
    if (p.scheme != "https" or p.hostname != HOSTS[scope["source"]] or p.port not in (None, 443)
            or p.username or p.password or unquote(p.path) != p.path or "\\" in p.path):
        raise ValueError("outside_collection_scope")
    p = p._replace(fragment="")
    if scope["strategy"] == "naju" and p.path.rstrip("/") == "/Messages1":
        query = parse_qs(p.query, keep_blank_values=True)
        if query.get("bmode") == ["view"] and len(query.get("idx", [])) == 1 and re.fullmatch(r"[0-9]{1,20}", query["idx"][0]):
            return f"https://{p.hostname}/Messages1/?bmode=view&idx={query['idx'][0]}", "document"
        if "bmode" not in query and "idx" not in query and not (query.keys() - {"q", "page"}):
            page = query.get("page", ["1"])
            if len(page) == 1 and page[0].isdigit() and 1 <= int(page[0]) <= 5000:
                return f"https://{p.hostname}/Messages1/" + (f"?page={int(page[0])}" if int(page[0]) != 1 else ""), "list"
    elif not p.query:
        clean = urlunsplit(p)
        if clean == scope["seed_url"]:
            return clean, "list"
        patterns = {
            "vatican_ii": r"/archive/hist_councils/ii_vatican_council/documents/[^/]+_en\.html",
            "vatican_i": r"/archive/hist_councils/i-vatican-council/documents/[^/]+_it\.html",
            "catechism": r"/archive/ENG0015/__P[0-9A-Z]+\.HTM",
            "fixed": r"/content/(?:john-paul-ii|benedict-xvi)/en/encyclicals/documents/[^/]+\.html",
        }
        if re.fullmatch(patterns.get(scope["strategy"], r"(?!)"), p.path):
            return clean, "document"
    raise ValueError("outside_collection_paths")


def _enqueue(library, scope, url, title="", parent=None):
    url, kind = normalize_url(scope, url)
    db, timestamp = library.db, now()
    db.execute("INSERT OR IGNORE INTO collection_tasks(id,scope_id,url,kind,title,discovered_from,state,created_at,updated_at) "
               "VALUES (?,?,?,?,?,?,'pending',?,?)", (str(uuid4()), scope["id"], url, kind, title, parent, timestamp, timestamp))
    if title:
        db.execute("UPDATE collection_tasks SET title=? WHERE scope_id=? AND url=? AND title=''", (title, scope["id"], url))
    if kind == "document":
        existing = db.execute("SELECT v.id,v.status,e.document_id,d.title FROM editions e JOIN document_versions v ON v.id=e.current_version_id "
                              "JOIN documents d ON d.id=e.document_id JOIN sources s ON s.id=e.source_id WHERE e.canonical_url=? AND e.language=? AND s.kind=?",
                              (url, scope["language"], scope["source"])).fetchone()
        if existing:
            db.execute("UPDATE documents SET document_type=? WHERE id=? AND document_type='unknown' AND metadata_status='needs_review'",
                       (_document_type(scope, existing["title"]), existing["document_id"]))
            db.execute("UPDATE collection_tasks SET version_id=?,state=?,updated_at=? "
                       "WHERE scope_id=? AND url=? AND version_id IS NULL AND state='pending'",
                       (existing["id"], "done" if existing["status"] == "extracted" else "partial", timestamp, scope["id"], url))


def initialize(library):
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    with library.db:
        for scope in catalog["collection_scopes"]:
            library.db.execute("INSERT INTO collection_scopes VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                               "label=excluded.label,note=excluded.note", (*[scope[k] for k in ("id", "source", "label", "language", "strategy", "seed_url", "note")], now()))
            if scope["seed_url"]:
                _enqueue(library, scope, scope["seed_url"])
            if scope["strategy"] == "fixed":
                for candidate in catalog["priority_encyclicals"]:
                    _enqueue(library, scope, candidate["url"], candidate["title"])
        linked = library.db.execute(
            "SELECT DISTINCT d.id,d.title,s.strategy FROM collection_tasks t JOIN collection_scopes s ON s.id=t.scope_id "
            "JOIN document_versions v ON v.id=t.version_id JOIN editions e ON e.id=v.edition_id "
            "JOIN documents d ON d.id=e.document_id WHERE d.document_type='unknown' AND d.metadata_status='needs_review'").fetchall()
        for row in linked:
            library.db.execute("UPDATE documents SET document_type=? WHERE id=?", (_document_type(row, row["title"]), row["id"]))


def parse_listing(scope, url, raw):
    soup = BeautifulSoup(raw, "html.parser")
    found = {}
    for anchor in soup.select("a[href]"):
        try:
            normalized, kind = normalize_url(scope, urljoin(url, anchor["href"]))
        except ValueError:
            continue
        title = anchor.get_text(" ", strip=True)[:500]
        if normalized not in found or title:
            found[normalized] = (kind, title)
    documents = sorted(url for url, (kind, _) in found.items() if kind == "document")
    if not documents:
        raise ValueError("empty_or_unrecognized_listing")
    fingerprint = hashlib.sha256("\n".join(documents).encode()).hexdigest()
    return found, fingerprint


def summary(library):
    scopes = []
    for row in library.db.execute("SELECT * FROM collection_scopes ORDER BY created_at,id"):
        item = dict(row)
        rows = [dict(r) for r in library.db.execute(
            "SELECT t.*,v.status AS version_status FROM collection_tasks t LEFT JOIN document_versions v ON v.id=t.version_id "
            "WHERE t.scope_id=?", (row["id"],))]
        docs, lists = [t for t in rows if t["kind"] == "document"], [t for t in rows if t["kind"] == "list"]
        item.update(discovered=len(docs), linked=sum(t["version_id"] is not None for t in docs),
                    extracted=sum(t["version_status"] == "extracted" for t in docs),
                    pending=sum(t["state"] == "pending" for t in docs),
                    problems=sum(t["state"] in {"failed", "blocked", "partial"} for t in docs),
                    lists_done=sum(t["state"] == "done" for t in lists), lists_total=len(lists),
                    lists_pending=sum(t["state"] in {"pending", "running"} for t in lists),
                    lists_problems=sum(t["state"] in {"failed", "blocked"} for t in lists),
                    discovery_status="entry_unverified" if row["strategy"] == "unresolved" else
                    "configured_subset" if row["strategy"] == "fixed" else
                    "visible_links_processed" if lists and all(t["state"] == "done" for t in lists) else "incomplete")
        scopes.append(item)
    return {"scopes": scopes, "complete": False, "note": "발견 URL 수는 전체 문헌 수가 아닙니다. 목록 순회 완료도 전체 역사 문헌의 확보를 뜻하지 않습니다."}


def task_list(library, scope_id):
    if not library.db.execute("SELECT 1 FROM collection_scopes WHERE id=?", (scope_id,)).fetchone():
        raise KeyError(scope_id)
    rows = [dict(row) for row in library.db.execute(
        "SELECT * FROM collection_tasks WHERE scope_id=? ORDER BY "
        "CASE WHEN state IN ('failed','blocked','partial') THEN 0 ELSE 1 END,created_at,url LIMIT 200", (scope_id,))]
    return {"tasks": rows, "shown": len(rows), "total": library.db.execute("SELECT count(*) FROM collection_tasks WHERE scope_id=?", (scope_id,)).fetchone()[0]}


@contextmanager
def _worker_lock(library):
    # ponytail: 개인 보관소당 직렬 작업자 하나다. 병렬 처리 필요 시 범위별 리스로 전환한다.
    lock = sqlite3.connect(library.root / "collection-worker.sqlite3", timeout=0)
    try:
        try:
            lock.execute("BEGIN EXCLUSIVE")
        except sqlite3.OperationalError as error:
            raise ValueError("collection_worker_busy") from error
        yield
    finally:
        lock.close()


def _process(library, scope, task, client):
    db, attempt_id, timestamp = library.db, str(uuid4()), now()
    with db:
        db.execute("UPDATE collection_tasks SET state='running',error=NULL,updated_at=? WHERE id=?", (timestamp, task["id"]))
        db.execute("INSERT INTO collection_attempts(id,task_id,state,started_at) VALUES (?,?,'running',?)", (attempt_id, task["id"], timestamp))
    evidence, digest, version_id = None, None, task["version_id"]
    try:
        url, kind = normalize_url(scope, task["url"])
        raw = client.fetch(url)
        digest = hashlib.sha256(raw).hexdigest()
        evidence = Path("collection-evidence") / (digest + ".html")
        path = library.root / evidence
        path.parent.mkdir(exist_ok=True)
        if path.exists() and file_hash(path) != digest:
            raise ValueError("collection_evidence_changed")
        if not path.exists():
            path.write_bytes(raw)
        heading = BeautifulSoup(raw, "html.parser", parse_only=SoupStrainer("title")).get_text().casefold()
        if any(term in heading for term in ("just a moment", "access denied", "captcha")) or b"cf-chl-" in raw:
            raise CollectionBlocked("challenge_page")
        if kind == "list":
            links, fingerprint = parse_listing(scope, url, raw)
            repeated = db.execute("SELECT id FROM collection_tasks WHERE scope_id=? AND kind='list' "
                                  "AND state='done' AND content_fingerprint=? AND id<>?", (scope["id"], fingerprint, task["id"])).fetchone()
            if repeated:
                raise ValueError("repeated_listing_content")
            with db:
                for found_url, (_, title) in links.items():
                    _enqueue(library, scope, found_url, title, task["id"])
                db.execute("UPDATE collection_tasks SET content_fingerprint=? WHERE id=?", (fingerprint, task["id"]))
            state = "done"
        else:
            # HTML의 짧은 사전 검증으로 차단/빈 페이지를 문헌에 넣지 않는다. 대량 처리 시 가져오기 사전 검증으로 통합한다.
            extracted = extract_file(path, scope["source"])
            if extracted["status"] != "extracted" or extracted["characters"] < 40:
                raise ValueError("document_content_rejected")
            imported = library.import_file(path, source=scope["source"], origin_url=url, language=scope["language"], origin_kind="download")
            version_id = imported["version_id"]
            state = "done" if imported["status"] == "extracted" else "partial"
            with db:
                db.execute("UPDATE documents SET document_type=? WHERE id=? AND document_type='unknown' AND metadata_status='needs_review'", (_document_type(scope, extracted["title"]), imported["document_id"]))
                db.execute("UPDATE collection_tasks SET title=? WHERE id=?", (extracted["title"], task["id"]))
        error = None
    except (OSError, ValueError, RuntimeError) as failure:
        state = "blocked" if isinstance(failure, CollectionBlocked) else "failed"
        error = f"{type(failure).__name__}:{failure}"[:1000]
    with db:
        db.execute("UPDATE collection_tasks SET state=?,version_id=?,error=?,updated_at=? WHERE id=?", (state, version_id, error, now(), task["id"]))
        db.execute("UPDATE collection_attempts SET state=?,finished_at=?,body_sha256=?,evidence_path=?,version_id=?,error=? WHERE id=?",
                   (state, now(), digest, evidence.as_posix() if evidence else None, version_id, error, attempt_id))
    return {"task_id": task["id"], "url": task["url"], "kind": task["kind"], "state": state, "error": error, "version_id": version_id}


def collect(library, scope_id, *, pages=1, documents=1, retry=False, refresh=False, client=None):
    if any(type(value) is not int or not 0 <= value <= 20 for value in (pages, documents)) or not pages + documents:
        raise ValueError("invalid_collection_limits")
    if type(retry) is not bool or type(refresh) is not bool:
        raise ValueError("invalid_collection_flags")
    initialize(library)
    row = library.db.execute("SELECT * FROM collection_scopes WHERE id=?", (scope_id,)).fetchone()
    if row is None:
        raise KeyError(scope_id)
    scope, results = dict(row), []
    if scope["strategy"] == "unresolved":
        raise ValueError("collection_entry_unverified")
    with _worker_lock(library):
        with library.db:
            # 잠금 확보 후에만 이전 작업자의 미완료 상태를 재개한다. 원문/과거 시도는 삭제하지 않는다.
            library.db.execute("UPDATE collection_attempts SET state='interrupted',finished_at=?,error='previous_worker_interrupted' WHERE state='running'", (now(),))
            library.db.execute("UPDATE collection_tasks SET state='pending',error='previous_worker_interrupted' WHERE state='running'")
            if retry:
                library.db.execute("UPDATE collection_tasks SET state='pending' WHERE scope_id=? AND state IN ('failed','blocked','partial')", (scope_id,))
            if refresh:
                library.db.execute("UPDATE collection_tasks SET state='pending' WHERE scope_id=? AND state='done'", (scope_id,))
        client = client or PublicClient(library.root / "collection-evidence")
        for kind, limit in (("list", pages), ("document", documents)):
            for _ in range(limit):
                task = library.db.execute("SELECT * FROM collection_tasks WHERE scope_id=? AND kind=? AND state='pending' ORDER BY created_at,url LIMIT 1", (scope_id, kind)).fetchone()
                if not task:
                    break
                result = _process(library, scope, dict(task), client)
                results.append(result)
                if result["state"] == "blocked":
                    return {"results": results, "summary": summary(library), "stopped": "access_or_policy_blocked"}
    return {"results": results, "summary": summary(library), "stopped": "batch_limit_or_queue_end"}
