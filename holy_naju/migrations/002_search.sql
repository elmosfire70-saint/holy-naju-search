-- 현재 문헌 검색 색인과 당시 근거를 보존하는 검색 실행·기록을 추가한다.
CREATE TABLE index_generations (
    id TEXT PRIMARY KEY,
    manifest_hash TEXT NOT NULL,
    pipeline_revision TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE search_state (
    id INTEGER PRIMARY KEY CHECK (id=1),
    current_generation_id TEXT REFERENCES index_generations(id)
);
INSERT INTO search_state VALUES (1, NULL);
CREATE VIRTUAL TABLE passage_fts USING fts5(
    passage_id UNINDEXED, title, body, tokenize='trigram'
);
CREATE TABLE search_runs (
    id TEXT PRIMARY KEY,
    cache_key TEXT NOT NULL,
    index_generation_id TEXT NOT NULL REFERENCES index_generations(id),
    query_original TEXT NOT NULL,
    query_normalized TEXT NOT NULL,
    filters TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('keyword','phrase')),
    result_limit INTEGER NOT NULL CHECK (result_limit BETWEEN 1 AND 100),
    pipeline_revision TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX search_runs_cache ON search_runs(cache_key, created_at);
CREATE UNIQUE INDEX passages_version_id ON passages(version_id, id);
CREATE TABLE search_hits (
    run_id TEXT NOT NULL REFERENCES search_runs(id),
    rank INTEGER NOT NULL CHECK (rank > 0),
    passage_id TEXT NOT NULL,
    version_id TEXT NOT NULL,
    snapshot TEXT NOT NULL,
    PRIMARY KEY (run_id, rank),
    FOREIGN KEY (version_id, passage_id) REFERENCES passages(version_id, id)
);
CREATE TABLE search_history (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES search_runs(id),
    query_original TEXT NOT NULL,
    accessed_at TEXT NOT NULL,
    reused INTEGER NOT NULL CHECK (reused IN (0,1))
);
PRAGMA user_version = 2;
