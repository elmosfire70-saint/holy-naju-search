-- 수집 범위와 발견한 목록/문헌 주소·처리 시도·보관 원문 연결을 보존한다.
CREATE TABLE collection_scopes (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL CHECK (source IN ('vatican','naju')),
    label TEXT NOT NULL,
    language TEXT NOT NULL,
    strategy TEXT NOT NULL,
    seed_url TEXT,
    note TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE collection_tasks (
    id TEXT PRIMARY KEY,
    scope_id TEXT NOT NULL REFERENCES collection_scopes(id),
    url TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('list','document')),
    title TEXT NOT NULL,
    discovered_from TEXT REFERENCES collection_tasks(id),
    state TEXT NOT NULL CHECK (state IN ('pending','running','done','partial','failed','blocked')),
    version_id TEXT REFERENCES document_versions(id),
    content_fingerprint TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(scope_id,url)
);
CREATE INDEX collection_tasks_queue ON collection_tasks(scope_id,kind,state,created_at);
CREATE TABLE collection_attempts (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL REFERENCES collection_tasks(id),
    state TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    body_sha256 TEXT,
    evidence_path TEXT,
    version_id TEXT REFERENCES document_versions(id),
    error TEXT
);
PRAGMA user_version = 4;
