-- 문헌과 파일 및 추출 버전의 근거 연결을 저장하는 초기 스키마다.
CREATE TABLE sources (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL UNIQUE CHECK (kind IN ('vatican','naju','user_import')),
    name TEXT NOT NULL,
    base_url TEXT
);
CREATE TABLE documents (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    author TEXT,
    issued_on TEXT,
    document_type TEXT NOT NULL DEFAULT 'unknown',
    metadata_status TEXT NOT NULL DEFAULT 'needs_review',
    created_at TEXT NOT NULL
);
CREATE TABLE editions (
    id TEXT PRIMARY KEY,
    document_id TEXT NOT NULL REFERENCES documents(id),
    source_id TEXT NOT NULL REFERENCES sources(id),
    language TEXT NOT NULL,
    canonical_url TEXT,
    current_version_id TEXT,
    UNIQUE (source_id, canonical_url, language),
    FOREIGN KEY (id, current_version_id) REFERENCES document_versions(edition_id, id)
);
CREATE TABLE assets (
    id TEXT PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    media_type TEXT NOT NULL,
    byte_size INTEGER NOT NULL CHECK (byte_size >= 0),
    relative_path TEXT NOT NULL UNIQUE,
    original_filename TEXT NOT NULL
);
CREATE TABLE ingestion_jobs (
    id TEXT PRIMARY KEY,
    target TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('running','completed','partial','failed')),
    asset_id TEXT REFERENCES assets(id),
    pending_path TEXT,
    error TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE acquisitions (
    id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES editions(id),
    asset_id TEXT NOT NULL REFERENCES assets(id),
    origin_kind TEXT NOT NULL CHECK (origin_kind IN ('user_import','download')),
    origin_url TEXT,
    original_path TEXT NOT NULL,
    acquired_at TEXT NOT NULL,
    job_id TEXT NOT NULL UNIQUE REFERENCES ingestion_jobs(id),
    version_id TEXT,
    FOREIGN KEY (edition_id, version_id) REFERENCES document_versions(edition_id, id)
);
CREATE INDEX acquisitions_edition_asset ON acquisitions(edition_id, asset_id);
CREATE TABLE document_versions (
    id TEXT PRIMARY KEY,
    edition_id TEXT NOT NULL REFERENCES editions(id),
    asset_id TEXT NOT NULL REFERENCES assets(id),
    acquisition_id TEXT NOT NULL REFERENCES acquisitions(id),
    extraction_key TEXT NOT NULL,
    extraction_profile TEXT NOT NULL,
    body_sha256 TEXT NOT NULL,
    extracted_text TEXT NOT NULL,
    extractor_revision TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('extracted','partial')),
    created_at TEXT NOT NULL,
    UNIQUE (edition_id, asset_id, extraction_key),
    UNIQUE (edition_id, id)
);
CREATE TABLE extraction_pages (
    id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES document_versions(id),
    page_number INTEGER NOT NULL CHECK (page_number > 0),
    method TEXT NOT NULL,
    engine_revision TEXT,
    language TEXT,
    status TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    review_status TEXT NOT NULL,
    error TEXT,
    UNIQUE (version_id, page_number)
);
CREATE TABLE passages (
    id TEXT PRIMARY KEY,
    version_id TEXT NOT NULL REFERENCES document_versions(id),
    extraction_page_id TEXT,
    ordinal INTEGER NOT NULL CHECK (ordinal > 0),
    official_number TEXT,
    locator TEXT NOT NULL,
    start_offset INTEGER NOT NULL CHECK (start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK (end_offset >= start_offset),
    text TEXT NOT NULL,
    UNIQUE (version_id, ordinal),
    FOREIGN KEY (version_id, extraction_page_id) REFERENCES extraction_pages(version_id, id)
);
CREATE UNIQUE INDEX extraction_pages_version_id ON extraction_pages(version_id, id);
PRAGMA user_version = 1;
