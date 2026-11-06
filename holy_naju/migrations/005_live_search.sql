-- 실시간 검색의 실행과 채택 원문 및 버전별 일치 근거를 보존한다.
CREATE TABLE live_search_runs (
    id TEXT PRIMARY KEY,
    query_original TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    status TEXT NOT NULL CHECK(status IN ('running','completed','partial','failed','interrupted')),
    snapshot TEXT NOT NULL
);
CREATE TABLE live_search_results (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES live_search_runs(id),
    rank INTEGER NOT NULL CHECK(rank > 0),
    canonical_url TEXT NOT NULL,
    language TEXT NOT NULL,
    version_id TEXT REFERENCES document_versions(id),
    status TEXT NOT NULL CHECK(status IN ('matched','no_match','failed')),
    snapshot TEXT NOT NULL,
    CHECK(status != 'matched' OR version_id IS NOT NULL),
    UNIQUE(run_id, rank),
    UNIQUE(run_id, canonical_url, language),
    UNIQUE(id, version_id)
);
CREATE TABLE live_search_evidence (
    result_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL,
    version_id TEXT NOT NULL,
    passage_id TEXT NOT NULL,
    start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK(end_offset > start_offset),
    excerpt TEXT NOT NULL,
    PRIMARY KEY(result_id, ordinal),
    FOREIGN KEY(result_id, version_id) REFERENCES live_search_results(id, version_id),
    FOREIGN KEY(version_id, passage_id) REFERENCES passages(version_id, id)
);
PRAGMA user_version = 5;
