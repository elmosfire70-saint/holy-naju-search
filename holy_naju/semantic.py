# 로컬 임베딩을 재사용하고 키워드·의미 검색의 근거 순위를 결합한다.
import hashlib
import math
import struct
from uuid import uuid4

from holy_naju.local_models import LocalModelError, OllamaClient
from holy_naju.search import _ensure_index, _filter_sql, _ranked_hits, _save_run, _snapshot, get_run
from holy_naju.storage import encode, now

HYBRID_REVISION = "hybrid-rrf-1"
EMBEDDING_REVISION = "title-passage-query-instruct-1"


def _normalize(vector):
    if not vector or any(not math.isfinite(v) for v in vector):
        raise LocalModelError("invalid_embedding")
    norm = math.sqrt(math.fsum(v * v for v in vector))
    if norm == 0 or not math.isfinite(norm):
        raise LocalModelError("zero_embedding")
    return [v / norm for v in vector]


def _cached_vectors(library, texts, client, profile):
    profile_key = encode(profile)
    hashes = [hashlib.sha256(t.encode()).hexdigest() for t in texts]
    vectors, missing = {}, {}
    for digest, text in zip(hashes, texts):
        row = library.db.execute("SELECT * FROM embeddings WHERE model_profile=? AND input_hash=?", (profile_key, digest)).fetchone()
        if row:
            vectors[digest] = list(struct.unpack(f'<{row["dimensions"]}f', row["vector"]))
        else:
            missing[digest] = text
    items = list(missing.items())
    for offset in range(0, len(items), 16):
        batch = items[offset:offset + 16]
        output = client.embed([text for _, text in batch], profile)
        if len(output) != len(batch):
            raise LocalModelError("invalid_embedding_count")
        normalized = [_normalize(v) for v in output]
        if len({len(v) for v in normalized}) != 1:
            raise LocalModelError("embedding_dimension_mismatch")
        with library.db:
            for (digest, _), vector in zip(batch, normalized):
                library.db.execute("INSERT OR IGNORE INTO embeddings VALUES (?,?,?,?,?,?)",
                                   (str(uuid4()), profile_key, digest, len(vector), struct.pack(f'<{len(vector)}f', *vector), now()))
                vectors[digest] = vector
    return hashes, [vectors[h] for h in hashes]


def _passages(db, filters):
    conditions, values = _filter_sql(filters)
    sql = ("SELECT p.id AS passage_id,p.version_id,p.text,p.locator,p.start_offset,p.end_offset,"
           "e.id AS edition_id,e.document_id,e.language,e.canonical_url,d.title,d.document_type,d.issued_on,"
           "s.kind AS source FROM passages p JOIN editions e ON e.current_version_id=p.version_id "
           "JOIN document_versions v ON v.id=p.version_id JOIN documents d ON d.id=e.document_id "
           "JOIN sources s ON s.id=e.source_id WHERE v.status='extracted'")
    if conditions:
        sql += " AND " + " AND ".join(conditions)
    return [dict(row) for row in db.execute(sql + " ORDER BY p.id", values)]


def _input(text, model, query=False):
    if model.startswith("nomic-embed-text"):
        return ("search_query: " if query else "search_document: ") + text
    if query:
        return "Instruct: Given a search query, retrieve relevant Catholic source passages that answer it.\nQuery: " + text
    return text


def prepare(library, rows, query, client, profile):
    texts = [_input(row["title"] + "\n" + row["text"], profile["name"]) for row in rows]
    hashes, vectors = _cached_vectors(library, texts, client, profile)
    with library.db:
        for row, digest in zip(rows, hashes):
            embedding_id = library.db.execute("SELECT id FROM embeddings WHERE model_profile=? AND input_hash=?", (encode(profile), digest)).fetchone()[0]
            library.db.execute("INSERT OR IGNORE INTO passage_embeddings VALUES (?,?,?,?)",
                               (row["passage_id"], encode(profile), digest, embedding_id))
    _, queries = _cached_vectors(library, [_input(query, profile["name"], query=True)], client, profile)
    query_vector = queries[0]
    if any(len(v) != len(query_vector) for v in vectors):
        raise LocalModelError("embedding_dimension_mismatch")
    # ponytail: 작은 문단 집합은 직접 코사인 유사도를 계산한다. 자료가 커지면 ANN 색인으로 전환한다.
    ranked = [(row, math.fsum(a * b for a, b in zip(vector, query_vector))) for row, vector in zip(rows, vectors)]
    return sorted(ranked, key=lambda item: (-item[1], item[0]["passage_id"]))


def _fuse(lexical, semantic, terms, limit):
    combined = {}
    for label, rows in (("keyword", [(r, None) for r in lexical]), ("semantic", semantic)):
        for rank, (row, similarity) in enumerate(rows, 1):
            item = combined.setdefault(row["passage_id"], {"row": dict(row), "rrf": 0.0, "signals": {}})
            item["rrf"] += 1 / (60 + rank)
            item["signals"][label] = {"rank": rank}
            if similarity is not None:
                item["signals"][label]["similarity"] = similarity
    hits = []
    for item in sorted(combined.values(), key=lambda r: (-r["rrf"], r["row"]["passage_id"]))[:limit]:
        row = item["row"]
        row["score"] = -item["rrf"]
        row["retrieval_signals"] = item["signals"]
        hits.append(_snapshot(row, terms))
    return hits


def hybrid_search(library, query, normalized, terms, filters, limit, refresh, client, model):
    from holy_naju.search import search
    client = client or OllamaClient()
    try:
        profile = {**client.profile(model, "embedding"), "embedding_revision": EMBEDDING_REVISION}
        db = library.db
        db.create_function("keyword_lower", 1, lambda text: text.lower(), deterministic=True)
        with db:
            db.execute("BEGIN IMMEDIATE")
            generation = _ensure_index(db)
            key = hashlib.sha256(encode([normalized, filters, limit, generation, HYBRID_REVISION, profile]).encode()).hexdigest()
            cached = None if refresh else db.execute("SELECT id FROM search_runs WHERE cache_key=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (key,)).fetchone()
            if cached:
                db.execute("INSERT INTO search_history VALUES (?,?,?,?,?)", (str(uuid4()), cached["id"], query, now(), 1))
        if cached:
            result = get_run(library, cached["id"])
            result["reused"] = True
            return result
        rows = _passages(db, filters)
        ranked = prepare(library, rows, normalized, client, profile) if rows else []
        with db:
            db.execute("BEGIN IMMEDIATE")
            if _ensure_index(db) != generation:
                raise LocalModelError("documents_changed_during_embedding")
            candidates = max(30, limit * 3)
            hits = _fuse(_ranked_hits(db, terms, filters, candidates), ranked[:candidates], terms, limit)
            run_id = _save_run(db, query, normalized, filters, "keyword", limit, generation, key,
                               HYBRID_REVISION, hits, retrieval="hybrid", model_profile=profile)
            db.execute("INSERT INTO search_history VALUES (?,?,?,?,?)", (str(uuid4()), run_id, query, now(), 0))
        result = get_run(library, run_id)
        result["reused"] = False
        return result
    except LocalModelError as error:
        result = search(library, query, limit=limit, refresh=refresh, **filters)
        result["retrieval_requested"] = "hybrid"
        result["diagnostics"] = {"semantic_status": "unavailable", "reason": str(error)}
        return result
