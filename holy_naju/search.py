# 현재 원문을 키워드로 검색하고 동일 결과 재사용과 과거 검색 근거를 보존한다.
from datetime import date
import hashlib
import json
import re
from uuid import uuid4

from holy_naju.storage import SOURCE_INFO, encode, now

PIPELINE_REVISION = "keyword-trigram-1"


def _ensure_index(db):
    # ponytail: 문헌판 메타데이터 전체를 확인한다. 대규모 자료에서는 변경 카운터로 전환한다.
    manifest = [dict(row) for row in db.execute(
        "SELECT e.id,e.current_version_id,e.language,e.canonical_url,d.id AS document_id,"
        "d.title,d.document_type,d.issued_on,s.kind,v.body_sha256 FROM editions e "
        "JOIN documents d ON d.id=e.document_id JOIN sources s ON s.id=e.source_id "
        "JOIN document_versions v ON v.id=e.current_version_id WHERE v.status='extracted' ORDER BY e.id")]
    digest = hashlib.sha256(encode(manifest).encode()).hexdigest()
    current = db.execute("SELECT g.* FROM search_state s JOIN index_generations g ON g.id=s.current_generation_id").fetchone()
    if current and current["manifest_hash"] == digest and current["pipeline_revision"] == PIPELINE_REVISION:
        return current["id"]
    generation = str(uuid4())
    db.execute("DELETE FROM passage_fts")
    db.execute("INSERT INTO passage_fts(passage_id,title,body) "
               "SELECT p.id,d.title,p.text FROM passages p JOIN editions e ON e.current_version_id=p.version_id "
               "JOIN documents d ON d.id=e.document_id JOIN document_versions v ON v.id=p.version_id "
               "WHERE v.status='extracted'")
    db.execute("INSERT INTO index_generations VALUES (?,?,?,?)", (generation, digest, PIPELINE_REVISION, now()))
    db.execute("UPDATE search_state SET current_generation_id=? WHERE id=1", (generation,))
    return generation


def _filter_sql(filters):
    conditions, values = [], []
    for key, column in (("source", "s.kind"), ("language", "lower(e.language)"), ("document_type", "d.document_type")):
        if filters.get(key):
            conditions.append(column + "=?")
            values.append(filters[key])
    for key, operator in (("issued_from", ">="), ("issued_to", "<=")):
        if filters.get(key):
            conditions.append("d.issued_on" + operator + "?")
            values.append(filters[key])
    return conditions, values


def _ranked_hits(db, terms, filters, limit):
    conditions, values = _filter_sql(filters)
    long_terms = [term for term in terms if len(term) >= 3]
    if long_terms:
        expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in long_terms)
        conditions.append("passage_fts MATCH ?")
        values.append(expression)
        score = "bm25(passage_fts,0.0,5.0,1.0)"
    else:
        # ponytail: 1~2글자는 부분 문자열 검사다. 대규모 한국어 자료에서는 전용 토큰 색인을 추가한다.
        db.create_function("keyword_score", 2, lambda title, body:
                           -sum(5 * title.lower().count(t) + body.lower().count(t) for t in terms))
        score = "keyword_score(f.title,f.body)"
    for term in terms:
        conditions.append("(instr(keyword_lower(f.title),?)>0 OR instr(keyword_lower(f.body),?)>0)")
        values.extend((term, term))
    sql = ("SELECT p.id AS passage_id,p.version_id,p.text,p.locator,p.start_offset,p.end_offset,"
           "e.id AS edition_id,e.document_id,e.language,e.canonical_url,d.title,d.document_type,d.issued_on,"
           "s.kind AS source," + score + " AS score FROM passage_fts f "
           "JOIN passages p ON p.id=f.passage_id JOIN editions e ON e.id=(SELECT edition_id FROM document_versions WHERE id=p.version_id) "
           "JOIN documents d ON d.id=e.document_id JOIN sources s ON s.id=e.source_id WHERE " +
           " AND ".join(conditions) + " ORDER BY score,d.title COLLATE NOCASE,p.ordinal,p.id LIMIT ?")
    return [dict(row) for row in db.execute(sql, (*values, limit))]


def _snapshot(row, terms):
    pattern = re.compile("|".join(re.escape(t) for t in sorted(set(terms), key=len, reverse=True)), re.IGNORECASE)
    matches = list(pattern.finditer(row["text"]))
    start = max(0, matches[0].start() - 60) if matches else 0
    end = min(len(row["text"]), start + 240)
    row["excerpt"] = row["text"][start:end]
    row["excerpt_start"] = start
    row["highlight_ranges"] = [[max(m.start(), start) - start, min(m.end(), end) - start]
                               for m in matches if m.start() < end and m.end() > start]
    row["title_highlight_ranges"] = [[m.start(), m.end()] for m in pattern.finditer(row["title"])]
    row["locator"] = json.loads(row["locator"])
    del row["text"]
    return row


def get_run(library, run_id):
    row = library.db.execute("SELECT * FROM search_runs WHERE id=?", (run_id,)).fetchone()
    if row is None:
        raise KeyError(run_id)
    result = dict(row)
    result["filters"] = json.loads(result["filters"])
    result["model_profile"] = json.loads(result["model_profile"]) if result["model_profile"] else None
    result["hits"] = [json.loads(hit[0]) for hit in library.db.execute(
        "SELECT snapshot FROM search_hits WHERE run_id=? ORDER BY rank", (run_id,))]
    return result


def history(library, limit=20):
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid_limit")
    records = [dict(row) for row in library.db.execute(
        "SELECT h.*,r.query_normalized,r.filters,r.mode,r.retrieval,r.index_generation_id,r.created_at AS searched_at "
        "FROM search_history h JOIN search_runs r ON r.id=h.run_id ORDER BY h.accessed_at DESC,h.id LIMIT ?", (limit,))]
    for record in records:
        record["filters"] = json.loads(record["filters"])
    return records


def _save_run(db, query, normalized, filters, mode, limit, generation, key, pipeline, hits,
              retrieval="keyword", model_profile=None):
    run_id = str(uuid4())
    db.execute("INSERT INTO search_runs(id,cache_key,index_generation_id,query_original,query_normalized,filters,"
               "mode,result_limit,pipeline_revision,created_at,retrieval,model_profile) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
               (run_id, key, generation, query, normalized, encode(filters), mode, limit, pipeline, now(),
                retrieval, encode(model_profile) if model_profile else None))
    for rank, hit in enumerate(hits, 1):
        hit["rank"] = rank
        db.execute("INSERT INTO search_hits VALUES (?,?,?,?,?)",
                   (run_id, rank, hit["passage_id"], hit["version_id"], encode(hit)))
    return run_id


def search(library, query, *, source=None, language=None, document_type=None,
           issued_from=None, issued_to=None, mode="keyword", limit=20, refresh=False,
           retrieval="keyword", client=None, embedding_model="qwen3-embedding:0.6b"):
    if not isinstance(query, str) or not query.strip() or len(query) > 500 or "\x00" in query:
        raise ValueError("invalid_query")
    if not isinstance(mode, str) or mode not in {"keyword", "phrase"} or type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("invalid_mode_or_limit")
    if source is not None and (not isinstance(source, str) or source not in SOURCE_INFO):
        raise ValueError("invalid_source")
    if type(refresh) is not bool:
        raise ValueError("invalid_refresh")
    if not isinstance(retrieval, str) or retrieval not in {"keyword", "hybrid"}:
        raise ValueError("invalid_retrieval")
    if retrieval == "hybrid" and mode != "keyword":
        raise ValueError("hybrid_requires_keyword_mode")
    if language is not None:
        if not isinstance(language, str) or not re.fullmatch(r"[A-Za-z0-9-]{1,32}", language):
            raise ValueError("invalid_language")
        language = language.lower()
    if document_type is not None and (not isinstance(document_type, str) or not 1 <= len(document_type) <= 100):
        raise ValueError("invalid_document_type")
    for value in (issued_from, issued_to):
        if value is not None and (not isinstance(value, str) or date.fromisoformat(value).isoformat() != value):
            raise ValueError("invalid_date")
    if issued_from and issued_to and issued_from > issued_to:
        raise ValueError("invalid_date_range")
    normalized = " ".join(query.split()).lower()
    terms = [normalized] if mode == "phrase" else sorted(set(normalized.split()))
    if len(terms) > 40:
        raise ValueError("too_many_terms")
    filters = {k: v for k, v in {"source": source, "language": language, "document_type": document_type,
                                "issued_from": issued_from, "issued_to": issued_to}.items() if v is not None}
    if retrieval == "hybrid":
        from holy_naju.semantic import hybrid_search
        return hybrid_search(library, query, normalized, terms, filters, limit, refresh, client, embedding_model)
    # AND 조건의 단어 순서는 검색 의미를 바꾸지 않지만 구절 모드의 순서는 보존한다.
    effective_query = terms if mode == "keyword" else normalized
    db = library.db
    db.create_function("keyword_lower", 1, lambda text: text.lower(), deterministic=True)
    with db:
        db.execute("BEGIN IMMEDIATE")
        generation = _ensure_index(db)
        key = hashlib.sha256(encode([effective_query, filters, mode, limit, generation, PIPELINE_REVISION]).encode()).hexdigest()
        cached = None if refresh else db.execute(
            "SELECT id FROM search_runs WHERE cache_key=? ORDER BY created_at DESC,rowid DESC LIMIT 1", (key,)).fetchone()
        if cached:
            run_id = cached["id"]
        else:
            hits = [_snapshot(row, terms) for row in _ranked_hits(db, terms, filters, limit)]
            run_id = _save_run(db, query, normalized, filters, mode, limit, generation, key, PIPELINE_REVISION, hits)
        db.execute("INSERT INTO search_history VALUES (?,?,?,?,?)", (str(uuid4()), run_id, query, now(), int(bool(cached))))
    result = get_run(library, run_id)
    result["reused"] = bool(cached)
    return result
