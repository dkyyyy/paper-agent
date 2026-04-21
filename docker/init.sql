CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS papers (
    id              VARCHAR(64) PRIMARY KEY,
    title           TEXT NOT NULL,
    authors         TEXT[] NOT NULL,
    abstract        TEXT,
    year            INTEGER,
    source          VARCHAR(20) NOT NULL,
    doi             VARCHAR(128),
    url             TEXT,
    citation_count  INTEGER DEFAULT 0,
    extracted_info  JSONB,
    pdf_path        TEXT,
    is_indexed      BOOLEAN DEFAULT FALSE,
    file_hash       VARCHAR(32),
    created_at      TIMESTAMP DEFAULT NOW(),
    updated_at      TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_papers_year ON papers(year);
CREATE INDEX IF NOT EXISTS idx_papers_source ON papers(source);
CREATE INDEX IF NOT EXISTS idx_papers_doi ON papers(doi);
CREATE INDEX IF NOT EXISTS idx_papers_file_hash ON papers(file_hash);
CREATE INDEX IF NOT EXISTS idx_papers_extracted_info ON papers USING GIN(extracted_info);

CREATE TABLE IF NOT EXISTS sessions (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    title       VARCHAR(200),
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS messages (
    id          BIGSERIAL PRIMARY KEY,
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    role        VARCHAR(20) NOT NULL,
    content     TEXT NOT NULL,
    metadata    JSONB,
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, created_at);

CREATE TABLE IF NOT EXISTS research_projects (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    topic       TEXT NOT NULL,
    status      VARCHAR(20) DEFAULT 'active',
    plan        JSONB,
    paper_ids   TEXT[],
    created_at  TIMESTAMP DEFAULT NOW(),
    updated_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_research_projects_session ON research_projects(session_id);

CREATE TABLE IF NOT EXISTS uploaded_files (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id  UUID NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
    paper_id    VARCHAR(64) REFERENCES papers(id),
    filename    VARCHAR(255) NOT NULL,
    file_path   TEXT NOT NULL,
    file_size   BIGINT NOT NULL,
    file_hash   VARCHAR(32) NOT NULL,
    status      VARCHAR(20) DEFAULT 'uploaded',
    created_at  TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_uploaded_files_session ON uploaded_files(session_id);
CREATE INDEX IF NOT EXISTS idx_uploaded_files_hash ON uploaded_files(file_hash);
