-- 로컬 모델의 임베딩·번역과 검색 시 사용한 모델 정보를 보존한다.
ALTER TABLE search_runs ADD COLUMN retrieval TEXT NOT NULL DEFAULT 'keyword';
ALTER TABLE search_runs ADD COLUMN model_profile TEXT;
CREATE TABLE embeddings (
    id TEXT PRIMARY KEY,
    model_profile TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK (dimensions > 0),
    vector BLOB NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (model_profile, input_hash)
);
CREATE TABLE passage_embeddings (
    passage_id TEXT NOT NULL REFERENCES passages(id),
    model_profile TEXT NOT NULL,
    input_hash TEXT NOT NULL,
    embedding_id TEXT NOT NULL REFERENCES embeddings(id),
    PRIMARY KEY (passage_id, model_profile, input_hash)
);
CREATE TABLE translations (
    id TEXT PRIMARY KEY,
    passage_id TEXT NOT NULL REFERENCES passages(id),
    source_hash TEXT NOT NULL,
    target_language TEXT NOT NULL,
    model_profile TEXT NOT NULL,
    prompt_revision TEXT NOT NULL,
    text TEXT,
    status TEXT NOT NULL CHECK (status IN ('completed','failed')),
    review_status TEXT NOT NULL DEFAULT 'unreviewed',
    error TEXT,
    created_at TEXT NOT NULL
);
CREATE INDEX translations_cache ON translations(passage_id, source_hash, model_profile, prompt_revision, status);
PRAGMA user_version = 3;
