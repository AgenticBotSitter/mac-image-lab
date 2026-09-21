CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS runs (
    id TEXT PRIMARY KEY,
    family_id TEXT NOT NULL,
    parent_run_id TEXT,
    relationship TEXT NOT NULL,
    model_id TEXT NOT NULL,
    operation TEXT NOT NULL,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    profile TEXT NOT NULL,
    request_json TEXT NOT NULL,
    legacy_receipt_json TEXT NOT NULL,
    receipt_path TEXT NOT NULL,
    receipt_sha256 TEXT NOT NULL,
    output_path TEXT,
    output_sha256 TEXT,
    output_width INTEGER,
    output_height INTEGER,
    generation_state TEXT NOT NULL,
    archive_state TEXT NOT NULL,
    favorite INTEGER NOT NULL DEFAULT 0 CHECK (favorite IN (0, 1)),
    deleted_at TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_runs_created ON runs(created_at DESC, id);
CREATE INDEX IF NOT EXISTS idx_runs_family ON runs(family_id, created_at, id);
CREATE INDEX IF NOT EXISTS idx_runs_state ON runs(generation_state, archive_state);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    state TEXT NOT NULL,
    priority INTEGER NOT NULL DEFAULT 100,
    idempotency_key TEXT NOT NULL UNIQUE,
    backend_job_id TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0,
    heartbeat_at TEXT,
    cancellation_requested_at TEXT,
    error_type TEXT,
    error_message TEXT,
    created_at TEXT NOT NULL,
    started_at TEXT,
    completed_at TEXT,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_jobs_queue ON jobs(state, priority, created_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_jobs_run_kind ON jobs(run_id, kind);

CREATE TABLE IF NOT EXISTS job_retries (
    parent_job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    child_job_id TEXT NOT NULL UNIQUE REFERENCES jobs(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    PRIMARY KEY (parent_job_id, child_job_id)
);

CREATE TABLE IF NOT EXISTS job_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    detail_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS collections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    relative_path TEXT NOT NULL UNIQUE,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS run_collections (
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    collection_id INTEGER NOT NULL REFERENCES collections(id) ON DELETE CASCADE,
    PRIMARY KEY (run_id, collection_id)
);

CREATE TABLE IF NOT EXISTS run_metadata_revisions (
    run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS model_notes (
    model_id TEXT PRIMARY KEY,
    note TEXT NOT NULL,
    revision INTEGER NOT NULL DEFAULT 1,
    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS recipes (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    request_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS family_choices (
    family_id TEXT PRIMARY KEY,
    chosen_run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS archive_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
    state TEXT NOT NULL,
    manifest_json TEXT NOT NULL DEFAULT '{}',
    error_type TEXT,
    error_message TEXT,
    started_at TEXT NOT NULL,
    completed_at TEXT
);
