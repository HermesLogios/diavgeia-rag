CREATE TABLE IF NOT EXISTS decisions (
    ada                 TEXT PRIMARY KEY,
    subject             TEXT NOT NULL,
    issue_date          DATE,
    organization_id     TEXT,
    organization_name   TEXT,
    decision_type_id    TEXT,
    expense_amount      NUMERIC(14, 2),
    currency            TEXT,
    document_url        TEXT,
    raw                 JSONB NOT NULL,
    fetched_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_decisions_issue_date ON decisions (issue_date);
CREATE INDEX IF NOT EXISTS idx_decisions_org ON decisions (organization_id);
CREATE INDEX IF NOT EXISTS idx_decisions_amount ON decisions (expense_amount);

CREATE TABLE IF NOT EXISTS chunks (
    id          BIGSERIAL PRIMARY KEY,
    ada         TEXT NOT NULL REFERENCES decisions(ada) ON DELETE CASCADE,
    chunk_index INT NOT NULL,
    content     TEXT NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (ada, chunk_index)
);

CREATE INDEX IF NOT EXISTS idx_chunks_ada ON chunks (ada);